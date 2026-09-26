"""SYS-53 (#182): a whole-index save may only replace the index it was loaded from.

`ChunkFAISSDatasource._atomic_save_local` writes the whole in-memory index over
the files on disk. OPS-26's run lock refuses that save while a scheduled crawl
runs, but a process that loaded NEWS_L1/L2 before or during the run and saves
after it ends would still write its stale copy over the run's vectors, and two
manual crawls can do the same to each other.

So every index a writer holds carries the *generation* of the files it was
read from, and a save is refused (StaleIndexError) when the files on disk are
no longer that generation. After its own save the writer holds the new
generation, so it can keep saving. The check and the swap run under a
per-index OS file lock, which also serialises the shared `<index>.tmp`
directory; the OS releases it when the holder dies, so it can never go stale.

The generation is the identity of the two files (inode/file id, mtime_ns,
size). Every save swaps in new files with os.replace, so it always changes,
and so does any other change to the files (a restore from backup, a hand
copy), which a counter file written only by this code would miss.
"""
import os
from typing import Optional, Tuple

from filelock import FileLock

INDEX_FILES = ("index.pkl", "index.faiss")
# A save of the full L2 index takes tens of seconds; waiting longer than this
# for another writer means something is wrong with it, not that it is slow.
SAVE_LOCK_TIMEOUT_S = 600
_ATTR = "_news_index_generation"

Generation = Optional[Tuple]


class StaleIndexError(RuntimeError):
    """The index on disk is not the one this process loaded or last saved:
    saving would overwrite someone else's vectors."""


def disk_generation(db_name: str) -> Generation:
    """The identity of the index files on disk now; None when there is no index."""
    parts = []
    for name in INDEX_FILES:
        try:
            st = os.stat(os.path.join(db_name, name))
        except FileNotFoundError:
            parts.append(None)
            continue
        parts.append((st.st_ino, st.st_mtime_ns, st.st_size))
    return None if all(p is None for p in parts) else tuple(parts)


def save_lock(db_name: str) -> FileLock:
    """The per-index lock held while an index is read for writing or saved.
    Waiting past the timeout raises filelock.Timeout."""
    path = os.path.abspath(db_name)
    # SYS-55 (#189): the lock sits next to the index directory, and filelock
    # does not create parents; a first save under a new nested path needs it.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return FileLock(path + ".lock", timeout=SAVE_LOCK_TIMEOUT_S)


def track(vs, db_name: str, generation: Generation) -> None:
    """Record that `vs` is based on `generation` of the index at `db_name`."""
    setattr(vs, _ATTR, (os.path.abspath(db_name), generation))


def track_disk(vs, db_name: str) -> None:
    """Record that `vs` is based on whatever is on disk at `db_name` now.

    Only for an index built in memory to replace what is there (tests, a new
    index); a writer that read the index must use load_index, which records
    the generation it actually read."""
    track(vs, db_name, disk_generation(db_name))


def load_index(db_name: str, embeddings):
    """FAISS.load_local, recording the generation read. Taken under the save
    lock, so the two files are read as one consistent pair."""
    from langchain_community.vectorstores import FAISS
    with save_lock(db_name):
        generation = disk_generation(db_name)
        vs = FAISS.load_local(db_name, embeddings, allow_dangerous_deserialization=True)
    track(vs, db_name, generation)
    return vs


def check_fresh(vs, db_name: str) -> None:
    """Raise StaleIndexError unless the disk still holds the generation `vs`
    is based on. Call it with the save lock held."""
    recorded = getattr(vs, _ATTR, None)
    path = os.path.abspath(db_name)
    if recorded is None or recorded[0] != path:
        raise StaleIndexError(
            "refusing to save %s: this in-memory index was not loaded from it through "
            "index_generation.load_index, so nothing says it is newer than what is on disk" % db_name)
    if disk_generation(db_name) != recorded[1]:
        raise StaleIndexError(
            "refusing to save %s: another process saved it after this one loaded it, and saving "
            "this copy would erase that process's vectors. Reload the index and redo the write." % db_name)

