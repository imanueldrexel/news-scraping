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

SYS-56 (#190): the two files of a pair are replaced one at a time, and no
filesystem replaces two files atomically. A save therefore commits through a
journal: the new pair, and the backup of the old one, are staged in
`<index>.tmp`, and one directory rename to `<index>.commit` is the commit
point. Only then are the files moved into place. A kill before the rename
leaves the old pair; a kill after it leaves a journal that the next reader or
writer rolls forward (`roll_forward`, under the save lock) before it looks at
the files. No reader that takes the save lock ever sees a mixed pair. That
matters since FAISS.delete renumbers index_to_docstore_id: an old index.faiss
with a new index.pkl maps positions to the wrong documents, silently.

SYS-60 (#197): from its commit point on, a save's generation is the one it
committed, whoever moves the files into place. A same-volume rename keeps a
file's id, mtime_ns and size, so commit_staged reads the generation off the
staged files before the rename, and the writer tracks that. When its own
roll-forward fails (a scanner holding index.faiss) and another process's load
finishes the journal, the writer's next save still finds its own generation
on disk instead of refusing itself as stale.
"""
import json
import logging
import os
import shutil
import time
from typing import Optional, Tuple

from filelock import FileLock

logger = logging.getLogger(__name__)

INDEX_FILES = ("index.pkl", "index.faiss")
BACKUP_SUFFIX = ".bak"
# SYS-61 (#198): the encoder (Hub id and revision) the pair's vectors were
# embedded with. Committed with the pair, so it can never describe another one.
ENCODER_FILE = "encoder.json"
# A save of the full L2 index takes tens of seconds; waiting longer than this
# for another writer means something is wrong with it, not that it is slow.
SAVE_LOCK_TIMEOUT_S = 600
_ATTR = "_news_index_generation"

Generation = Optional[Tuple]

# SYS-64 (#208): on Windows a rename fails with PermissionError (WinError 5)
# while any process holds a handle on a file inside the directory, which a
# virus scanner or the search indexer does for a moment right after the files
# are written. Three runs lost a source that way (2026-09-29/30). A rename
# either happens or not, so it is retried: 0.2, 0.4, 0.8, 1.6, 3.2 s.
RENAME_RETRIES = int(os.getenv("FAISS_RENAME_RETRIES", 5))
RENAME_BACKOFF_S = float(os.getenv("FAISS_RENAME_BACKOFF_S", 0.2))
_sleep = time.sleep  # patched by the tests


def _retry_on_permission_error(op, src: str, dst: str):
    """op(src, dst), retried on PermissionError; the last one is raised."""
    for attempt in range(RENAME_RETRIES + 1):
        try:
            return op(src, dst)
        except PermissionError as e:
            if attempt == RENAME_RETRIES:
                raise
            delay = RENAME_BACKOFF_S * (2 ** attempt)
            logger.warning(f"{getattr(op, '__name__', 'rename')}({src} -> {dst}) denied ({e}); retry {attempt + 1}/{RENAME_RETRIES} "
                           f"in {delay:.1f}s (SYS-64)")
            _sleep(delay)


class StaleIndexError(RuntimeError):
    """The index on disk is not the one this process loaded or last saved:
    saving would overwrite someone else's vectors."""


class CorruptIndexError(RuntimeError):
    """The index.faiss and index.pkl on disk are not one pair: searching it
    would return the wrong documents."""


def staging_dir(db_name: str) -> str:
    """Where a save writes its files before the commit point. Anything found
    here was not committed and is thrown away."""
    return f"{db_name}.tmp"


def journal_dir(db_name: str) -> str:
    """A committed save whose files are not all in place yet."""
    return f"{db_name}.commit"


def has_index(db_name: str) -> bool:
    """An index exists: live files, or a committed save not rolled forward yet
    (a first save killed after its commit point has no live files)."""
    return os.path.exists(os.path.join(db_name, "index.faiss")) or os.path.isdir(journal_dir(db_name))


def _journal_order():
    # The old pair's backup goes in before the new pair replaces it. Any order
    # would do, since an interrupted roll-forward is finished by the next one.
    return tuple(name + BACKUP_SUFFIX for name in INDEX_FILES) + (ENCODER_FILE,) + INDEX_FILES


def read_encoder(db_name: str) -> Optional[dict]:
    """SYS-61: the encoder record committed with the pair at db_name, or None
    when the pair has none (saved before SYS-61)."""
    try:
        with open(os.path.join(db_name, ENCODER_FILE), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _fsync_files(directory: str) -> None:
    """Put the staged files on disk before the rename that commits them, so a
    power loss cannot leave a committed journal of empty or partial files."""
    for name in os.listdir(directory):
        with open(os.path.join(directory, name), "rb+") as f:
            os.fsync(f.fileno())


def commit_staged(db_name: str) -> Generation:
    """Commit the pair staged in staging_dir(db_name): the directory rename is
    the commit point. Returns the generation the files will have in db_name
    (SYS-60), read before the rename, since moving them keeps their identity.
    The caller moves them into place with roll_forward. Call it with the save
    lock held."""
    staged = staging_dir(db_name)
    _fsync_files(staged)
    committed = disk_generation(staged)
    _retry_on_permission_error(os.rename, staged, journal_dir(db_name))
    return committed


def roll_forward(db_name: str) -> bool:
    """Finish a committed save: move every file left in the journal into
    db_name, then drop the journal. Idempotent, so a kill during it is finished
    by the next call. Returns whether there was a journal. Call it with the
    save lock held, before reading or replacing the files."""
    journal = journal_dir(db_name)
    if not os.path.isdir(journal):
        return False
    os.makedirs(db_name, exist_ok=True)
    for name in _journal_order():
        src = os.path.join(journal, name)
        if os.path.exists(src):
            _retry_on_permission_error(os.replace, src, os.path.join(db_name, name))
    shutil.rmtree(journal, ignore_errors=True)
    return True


def recover(db_name: str) -> None:
    """Make the files at db_name one whole pair: roll a committed save forward
    and drop an uncommitted one. Call it with the save lock held."""
    if roll_forward(db_name):
        logger.warning(f"{db_name}: finished a save that was interrupted after its commit point (SYS-56)")
    shutil.rmtree(staging_dir(db_name), ignore_errors=True)


def pair_problem(ntotal: int, index_to_docstore_id, stored_ids) -> Optional[str]:
    """Why (index.faiss, index.pkl) is not one pair, or None. Pure. Position i
    of index.faiss must map to a stored document for every i < ntotal, and no
    other position may be mapped."""
    if set(index_to_docstore_id) != set(range(ntotal)):
        return ("index.faiss holds %d vectors but index.pkl maps %d positions"
                % (ntotal, len(index_to_docstore_id)))
    missing = sum(1 for doc_id in index_to_docstore_id.values() if doc_id not in stored_ids)
    if missing:
        return "%d mapped positions point at no stored document" % missing
    return None


def read_disk_pair(db_name: str):
    """(ntotal, docstore, index_to_docstore_id) of the files on disk, read
    without an embedding model: only the header of index.faiss is mapped, and
    index.pkl is unpickled. None when there is no index. Read-only. Call it
    with the save lock held, or a save in progress can be read half done."""
    import pickle

    import faiss

    faiss_path = os.path.join(db_name, "index.faiss")
    if not os.path.exists(faiss_path):
        return None
    ntotal = faiss.read_index(faiss_path, faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY).ntotal
    with open(os.path.join(db_name, "index.pkl"), "rb") as f:
        docstore, index_to_docstore_id = pickle.load(f)
    return ntotal, docstore, index_to_docstore_id


def disk_pair_problem(db_name: str, pair=None) -> Optional[str]:
    """pair_problem for the files on disk (`pair` from read_disk_pair, read
    here when not given), plus a journal an interrupted save left behind.
    Read-only: it never rolls anything forward."""
    if os.path.isdir(journal_dir(db_name)):
        return "a save interrupted after its commit point was not rolled forward (%s)" % journal_dir(db_name)
    pair = pair if pair is not None else read_disk_pair(db_name)
    if pair is None:
        return None
    ntotal, docstore, index_to_docstore_id = pair
    return pair_problem(ntotal, index_to_docstore_id, docstore._dict)


def disk_generation(db_name: str) -> Generation:
    """The identity of the index files in the directory db_name now; None when
    there is no index."""
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


def is_current(vs, db_name: str) -> bool:
    """DBT-16 (#51): does the disk still hold the generation `vs` was read
    from? Two stats and no lock: a reader's cheap "should I reload?" check. A
    writer decides with check_fresh under the save lock instead."""
    recorded = getattr(vs, _ATTR, None)
    return (recorded is not None and recorded[0] == os.path.abspath(db_name)
            and recorded[1] == disk_generation(db_name))


def track_disk(vs, db_name: str) -> None:
    """Record that `vs` is based on whatever is on disk at `db_name` now.

    Only for an index built in memory to replace what is there (tests, a new
    index); a writer that read the index must use load_index, which records
    the generation it actually read."""
    track(vs, db_name, disk_generation(db_name))


def load_index(db_name: str, embeddings):
    """FAISS.load_local, recording the generation read. Taken under the save
    lock, so the two files are read as one consistent pair: a save a kill
    interrupted after its commit point is finished first (SYS-56). A pair that
    still does not line up (a hand copy of one file, a pre-SYS-56 torn save) is
    refused with CorruptIndexError instead of being searched."""
    from langchain_community.vectorstores import FAISS
    with save_lock(db_name):
        recover(db_name)
        generation = disk_generation(db_name)
        vs = FAISS.load_local(db_name, embeddings, allow_dangerous_deserialization=True)
    problem = pair_problem(vs.index.ntotal, vs.index_to_docstore_id, vs.docstore._dict)
    if problem:
        raise CorruptIndexError(
            "refusing to use %s: %s. Searches would return the wrong documents. Restore the "
            "index.faiss.bak/index.pkl.bak pair (OPERATIONS.md) and run check_store_consistency.py"
            % (db_name, problem))
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

