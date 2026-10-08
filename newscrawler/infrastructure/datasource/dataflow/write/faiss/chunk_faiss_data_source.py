import json
import logging
import os
import shutil
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.schema import Document

from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2, EMBEDDING_MODEL_HF
from newscrawler.core.utils.hf_cache import EncoderRevisionError, cached_revision, check_revision, resolve_model
from newscrawler.domain.dtos.dataflow.details.chunk_dto import ChunkDTO
from newscrawler.infrastructure.datasource.dataflow.write.faiss import index_generation
from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import StaleIndexError

logger = logging.getLogger(__name__)


class ChunkFAISSDatasource:
    # SYS-61 (#198): {"model", "revision"} of the encoder this process embeds
    # with; each save commits it with the pair (index_generation.ENCODER_FILE).
    encoder_record: Optional[dict] = None

    def __init__(self):
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL_HF}")
        self.embedding_model = HuggingFaceEmbeddings(
            # OPS-32: from the local cache when it is there, so a worker respawn
            # during a network outage does not wait on huggingface.co.
            model_name=resolve_model(EMBEDDING_MODEL_HF),
            encode_kwargs={'batch_size': 64, 'normalize_embeddings': True},
        )
        self.encoder_record = {"model": EMBEDDING_MODEL_HF, "revision": cached_revision(EMBEDDING_MODEL_HF)}
        self.vs_l1 = self._load_or_create(VECTOR_DB_NAME_L1)
        self.vs_l2 = self._load_or_create(VECTOR_DB_NAME_L2)
        logger.info("ChunkFAISSDatasource ready (L1 + L2 indexes loaded)")

    def save(self, chunks: List[ChunkDTO]) -> List[ChunkDTO]:
        """Embed chunks into L1/L2 FAISS indexes. Returns chunks with embedding_id populated."""
        l1_chunks = [c for c in chunks if c.chunk_level == 1]
        l2_chunks = [c for c in chunks if c.chunk_level == 2]

        updated: List[ChunkDTO] = []
        if l1_chunks:
            updated.extend(self._embed_batch(l1_chunks, self.vs_l1, VECTOR_DB_NAME_L1))
        if l2_chunks:
            updated.extend(self._embed_batch(l2_chunks, self.vs_l2, VECTOR_DB_NAME_L2))
        return updated

    def _embed_batch(self, chunks: List[ChunkDTO], vs: FAISS, db_name: str) -> List[ChunkDTO]:
        # SYS-17: key on (sitemap_id, chunk_level, chunk_index), not sitemap_id alone,
        # so a chunk already present in FAISS is matched to its *real* embedding_id
        # (the docstore key it was originally added under) instead of being returned
        # with embedding_id=None. This is what makes save_chunk_data's SQL-based
        # dedup (see DataFlowRepositoryImpl.save_chunk_data) self-healing: a sitemap
        # whose SQL insert failed after FAISS already had its vectors gets retried,
        # finds those exact vectors here, and reuses their ids instead of either
        # skipping the SQL insert (the old bug) or adding duplicate vectors.
        existing = self._existing_ids(vs, db_name)
        result = []
        new_chunks = []
        seen_this_batch = set()
        for c in chunks:
            key = (c.sitemap_id, c.chunk_level, c.chunk_index)
            if key in seen_this_batch:
                # SYS-26: DBT-09 only guarded the new-chunk branch below, so two
                # chunks sharing a key where that key is ALREADY in FAISS (the
                # SYS-17 recovery path) both fell into the `if key in existing`
                # branch and both landed in `result` -- two rows appended to
                # `result` for one logical chunk, which then violated
                # chunks_sitemap_level_index_uq on the SQL insert and aborted the
                # whole batch. Drop any repeat of an already-seen key up front,
                # before either branch, so both the new-chunk and the
                # already-embedded path are covered by one guard.
                continue
            seen_this_batch.add(key)
            if key in existing:
                result.append(replace(c, embedding_id=existing[key], chunk_status='embedded'))
            else:
                new_chunks.append(c)

        if not new_chunks:
            logger.info(f"  {db_name}: all {len(chunks)} chunks already embedded, skipping")
            return result

        docs = [self._to_document(c) for c in new_chunks]
        embedding_ids = vs.add_documents(docs)  # LangChain returns list of UUID strings
        for chunk, eid in zip(new_chunks, embedding_ids):
            existing[(chunk.sitemap_id, chunk.chunk_level, chunk.chunk_index)] = eid
        self._remember_size(vs, db_name)
        if self.is_deferred:
            # DBT-10: persisted once, by flush() at the end of the deferred block.
            self._dirty().add(db_name)
        else:
            self._persist(vs, db_name)
        logger.info(f"  {db_name}: embedded {len(new_chunks)} new chunks")

        for chunk, eid in zip(new_chunks, embedding_ids):
            result.append(replace(chunk, embedding_id=eid, chunk_status='embedded'))
        return result

    def discard(self, sitemap_ids) -> int:
        """SYS-54: delete every vector of these sitemaps from both indexes. Inside
        a deferred block the deletions reach disk with the block's flush;
        outside one, each touched level is saved now. Scans the docstores rather
        than the key cache, so duplicate vectors of one key go too. Returns the
        number of vectors deleted."""
        sids = {int(s) for s in sitemap_ids}
        deleted = 0
        for db_name in (VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2):
            vs = self._store(db_name)
            ids = [doc_id for doc_id, doc in vs.docstore._dict.items()
                   if doc.metadata.get("sitemap_id") is not None and int(doc.metadata["sitemap_id"]) in sids]
            if not ids:
                continue
            vs.delete(ids)
            self.__dict__.get("_key_caches", {}).pop(db_name, None)
            if self.is_deferred:
                self._dirty().add(db_name)
            else:
                self._persist(vs, db_name)
            deleted += len(ids)
        return deleted

    # ── DBT-10 (#45): write frequency ────────────────────────────────────────
    # Every batch used to rewrite the whole index pair (L1 ~68 MB + L2 ~204 MB,
    # plus the same again for the .bak copy): about 10 saves per level per source,
    # ~150-220 GB of writes per scheduled run. Inside `deferred()` the adds stay in
    # memory and flush() persists each touched level ONCE. Outside it (every
    # script) behaviour is unchanged: save after every add.
    #
    # Deferring is only safe together with DataFlowRepositoryImpl.deferred_
    # embeddings, which writes the SQL chunk rows with embedding_id NULL until
    # the flush has happened. That way a process killed mid-block (OPS-22's
    # timeout kill) leaves rows that say "not embedded", not rows that point at
    # vectors which never reached disk.

    @property
    def is_deferred(self) -> bool:
        return getattr(self, "_defer_depth", 0) > 0

    def _dirty(self):
        if not hasattr(self, "_dirty_dbs"):
            self._dirty_dbs = set()
        return self._dirty_dbs

    def begin_deferred(self) -> bool:
        """Enter a deferred block; True when it is the outermost one."""
        self._defer_depth = getattr(self, "_defer_depth", 0) + 1
        return self._defer_depth == 1

    def end_deferred(self) -> bool:
        """Leave a deferred block. The outermost one flushes and returns True
        once the flush has succeeded; a failed flush raises instead."""
        self._defer_depth -= 1
        if self._defer_depth > 0:
            return False
        self.flush()
        return True

    @contextmanager
    def deferred(self):
        """Batch persistence: flush once when the outermost block exits, also on
        an exception (the batches before it were committed to SQL and must not be
        left unsaved). Only a hard kill skips the flush."""
        self.begin_deferred()
        try:
            yield self
        finally:
            self.end_deferred()

    def flush(self) -> None:
        """Persist every level touched in the block. A level refused as stale
        (SYS-53) has been reloaded; the other level is still saved, and the
        refusal is raised at the end, so the block assigns no ids."""
        refused = None
        for db_name in sorted(self._dirty()):
            try:
                self._persist(self._store(db_name), db_name)
                logger.info(f"  {db_name}: index saved (deferred flush)")
            except StaleIndexError as e:
                refused = refused or e
            self._dirty().discard(db_name)
        if refused:
            raise refused

    def _store(self, db_name: str) -> FAISS:
        return self.vs_l1 if db_name == VECTOR_DB_NAME_L1 else self.vs_l2

    def _persist(self, vs: FAISS, db_name: str) -> None:
        """Save one level. SYS-53: when another process saved it after this one
        loaded it, this copy can never be saved again. Drop it and reload, so
        this process's next block builds on the current index. The dropped
        vectors' chunk rows are embedding_id NULL (deferred block) or were never
        written (outside one); the next deferred block of their source re-embeds
        NULL rows."""
        try:
            self._atomic_save_local(vs, db_name, encoder=self.encoder_record)
        except StaleIndexError:
            logger.error(f"  {db_name}: another process saved this index after this one loaded it; "
                         f"dropping this process's unsaved vectors and reloading the index")
            self._reload(db_name)
            raise

    def _reload(self, db_name: str) -> None:
        vs = self._load_or_create(db_name)
        if db_name == VECTOR_DB_NAME_L1:
            self.vs_l1 = vs
        else:
            self.vs_l2 = vs
        self.__dict__.get("_key_caches", {}).pop(db_name, None)

    def refresh_stale(self) -> List[str]:
        """DBT-16 (#51): for a READER (the web UI) -- reload each level whose
        files another process saved since this one read them, and return the
        levels reloaded. A search already running keeps the object it started
        with. A writer must never call this: reloading discards its unsaved
        vectors (SYS-53 raises instead, at save time)."""
        reloaded = []
        for db_name in (VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2):
            if not index_generation.is_current(self._store(db_name), db_name):
                self._reload(db_name)
                reloaded.append(db_name)
        if reloaded:
            logger.info(f"Reloaded FAISS index(es) saved by another process: {', '.join(reloaded)}")
        return reloaded

    def _existing_ids(self, vs, db_name) -> Dict[Tuple[int, int, int], str]:
        """(sitemap_id, level, index) -> embedding_id, built once per index instead
        of walking the whole docstore on every batch. Rebuilt whenever the
        docstore's size differs from the size it was built at, so an add or a
        delete made outside this class (dedupe_chunks.py) cannot leave it stale."""
        caches = self.__dict__.setdefault("_key_caches", {})
        cached = caches.get(db_name)
        size = len(vs.docstore._dict)
        if cached is None or cached[0] != size:
            cached = [size, self._get_existing_embedding_ids(vs)]
            caches[db_name] = cached
        return cached[1]

    def _remember_size(self, vs, db_name) -> None:
        cached = self.__dict__.get("_key_caches", {}).get(db_name)
        if cached is not None:
            cached[0] = len(vs.docstore._dict)

    @staticmethod
    def _atomic_save_local(vs: FAISS, db_name: str, encoder: Optional[dict] = None) -> None:
        """DBT-10 (#45): FAISS.save_local writes index.faiss then index.pkl
        directly into db_name, with no temp-file + rename -- a crash, OOM, or
        disk-full mid-write leaves the only copy truncated. So the new pair is
        written to a sibling staging directory first; the live files are never
        touched while save_local runs.

        SYS-56 (#190): replacing the live pair file by file is not enough. A
        kill between the two replaces used to leave (old index.faiss, new
        index.pkl), which DBT-10 called stale-but-consistent because the crawl
        only appended. FAISS.delete (SYS-54's discard, the repair and dedupe
        scripts) renumbers index_to_docstore_id, so that pair maps positions to
        the wrong documents, silently. The staged pair is now committed as a
        whole by one directory rename (index_generation.commit_staged) and
        rolled forward from that journal; a kill at any point leaves the old
        pair or a journal that the next load finishes. The previous pair is
        staged as *.bak in the same commit, so the backup is one pair too.

        SYS-61 (#198): `encoder` ({"model", "revision"}) is committed with the
        pair as index_generation.ENCODER_FILE. A caller that embeds nothing (a
        repair or dedupe script that only deletes) passes None, and the pair
        keeps the record it had.
        """
        from newscrawler.tools.run_lock import refuse_foreign_writer

        with index_generation.save_lock(db_name):
            # OPS-26 (#175): while a scheduled crawl runs, its worker holds this
            # index in memory and its next flush would overwrite any other
            # writer's save. Every FAISS save goes through here, so the refusal
            # is here too. It is checked under the save lock because the
            # worker's load takes that lock as well: a save either finishes
            # before the worker reads the index, or sees the run lock.
            refuse_foreign_writer()
            # SYS-56: a save a kill interrupted after its commit point is the
            # newest generation; finish it before judging freshness against it.
            # If this copy committed it (its own roll-forward failed), it
            # already tracks that generation (SYS-60, below).
            index_generation.recover(db_name)
            # SYS-53 (#182): only a copy of the generation on disk may replace
            # it, which also covers a save made after the run lock is released.
            # Under the lock nobody else saves between this check and the swap,
            # and the staging directory below is ours alone.
            index_generation.check_fresh(vs, db_name)
            # A failure before the commit leaves the disk unchanged, and with
            # it the generation this copy is based on.
            committed = ChunkFAISSDatasource._stage_and_commit(vs, db_name, encoder)
            # SYS-60 (#197): from the commit point on, this copy is based on
            # the generation it committed, whoever finishes the roll-forward:
            # this call, or another process's load when this one fails (a
            # scanner holding index.faiss open).
            index_generation.track(vs, db_name, committed)
            index_generation.roll_forward(db_name)

    @staticmethod
    def _stage_and_commit(vs: FAISS, db_name: str, encoder: Optional[dict] = None) -> index_generation.Generation:
        """Stage the new pair, a copy of the old one and the encoder record, then
        commit them. Returns the generation committed (index_generation.commit_staged)."""
        staged = index_generation.staging_dir(db_name)
        if os.path.exists(staged):
            shutil.rmtree(staged)
        vs.save_local(staged)
        for fname in index_generation.INDEX_FILES:
            live_path = os.path.join(db_name, fname)
            if os.path.exists(live_path):
                # Copy, not move: the live pair must stay whole until the
                # commit, so a failure before it changes nothing.
                shutil.copy2(live_path, os.path.join(staged, fname + index_generation.BACKUP_SUFFIX))
        if encoder is not None:
            # Without one, the roll-forward leaves the pair's record in place:
            # it moves only what the journal holds.
            with open(os.path.join(staged, index_generation.ENCODER_FILE), "w", encoding="utf-8") as f:
                json.dump(encoder, f)
        return index_generation.commit_staged(db_name)

    def _to_document(self, chunk: ChunkDTO) -> Document:
        return Document(
            page_content=chunk.text_content,
            metadata={
                'sitemap_id': chunk.sitemap_id,
                'chunk_level': chunk.chunk_level,
                'chunk_index': chunk.chunk_index,
                'title': chunk.title,
                'source': chunk.source,
                'category': chunk.category or '',
                'posted_at': str(chunk.posted_at or ''),
            },
        )

    def _check_encoder(self, db_name: str) -> None:
        """SYS-61 (#198): refuse an index embedded with another encoder revision
        than the one this process loaded. New vectors would land in a different
        space from the stored ones, and RAG, the SYS-17 key reuse and the
        newsletter's DBSCAN all assume one space."""
        recorded = index_generation.read_encoder(db_name)
        loaded = self.encoder_record or {}
        if recorded is None:
            logger.warning(f"{db_name} records no encoder revision (saved before SYS-61); "
                           f"its next save records {loaded.get('model')} {loaded.get('revision')}")
            return
        if recorded.get("model") != loaded.get("model"):
            raise EncoderRevisionError(
                f"{db_name} was embedded with {recorded.get('model')}, this process loads {loaded.get('model')}")
        check_revision(loaded.get("model"), recorded.get("revision"), loaded.get("revision"), db_name)

    def _load_or_create(self, db_name: str) -> FAISS:
        # DBT-16 (#51): when each level was last read from disk, for /api/health.
        self.__dict__.setdefault("loaded_at", {})[db_name] = datetime.now(timezone.utc)
        if index_generation.has_index(db_name):
            logger.info(f"Loading existing FAISS index: {db_name}")
            vs = index_generation.load_index(db_name, self.embedding_model)
            self._check_encoder(db_name)
            return vs

        logger.info(f"Creating new FAISS index: {db_name}")
        dummy = Document(page_content="init", metadata={})
        vs = FAISS.from_documents([dummy], self.embedding_model)
        vs.index.reset()
        vs.docstore._dict.clear()
        vs.index_to_docstore_id.clear()
        # SYS-53: a new index may be saved only where no index has appeared since.
        index_generation.track(vs, db_name, None)
        return vs

    def search_l2(self, query_text: str, k: int = 20) -> List[dict]:
        """Semantic search against the L2 (paragraph) index. Returns top-k hits."""
        try:
            results = self.vs_l2.similarity_search_with_score(query_text, k=k)
        except Exception as e:
            logger.warning(f"FAISS search failed: {e}")
            return []

        hits = []
        for doc, score in results:
            # similarity_search_with_score returns faiss's IndexFlatL2 distance, which is the
            # SQUARED L2 distance (lower = more similar). Embeddings are unit-normalized, so
            # d = 2 - 2*cos and cos = 1 - d / 2. SYS-110 (#284): this read 1 - d^2/2, as if d
            # were the plain distance (cos 0.82 read 0.93, cos 0.29 read 0), and could not be
            # compared with the cosine of a keyword-only paragraph (SYS-106).
            semantic_score = max(0.0, 1.0 - float(score) / 2.0)
            hits.append({
                "text_content": doc.page_content,
                "semantic_score": semantic_score,
                "sitemap_id":  doc.metadata.get("sitemap_id"),
                "source":      doc.metadata.get("source", ""),
                "posted_at":   doc.metadata.get("posted_at", ""),
                "title":       doc.metadata.get("title", ""),
                "category":    doc.metadata.get("category", ""),
                "chunk_level": doc.metadata.get("chunk_level"),
            })
        return hits

    def similarity(self, query_text: str, texts: List[str],
                   embedding_ids: Optional[List[Optional[str]]] = None) -> List[float]:
        """SYS-106 (#276): each paragraph's similarity to the query on search_l2's `semantic_score`
        scale, for a paragraph the keyword search found and FAISS did not return. A paragraph in
        NEWS_L2 (its chunk row's `embedding_id`) is scored with its stored vector, which is the one
        search_l2 compares (one encoder revision, SYS-61) and costs nothing; any other is embedded
        (~25 ms each on CPU). Vectors are unit-normalised: the cosine is the dot product
        (= 1 - d^2/2 for search_l2's distance)."""
        if not texts:
            return []
        import numpy as np
        query = np.asarray(self.embedding_model.embed_query(query_text), dtype="float32")
        positions = self._l2_positions()
        vectors: List = [None] * len(texts)
        for i, embedding_id in enumerate(embedding_ids or []):
            position = positions.get(embedding_id) if embedding_id else None
            if position is not None:
                vectors[i] = self.vs_l2.index.reconstruct(int(position))
        missing = [i for i, v in enumerate(vectors) if v is None]
        if missing:
            for i, v in zip(missing, self.embedding_model.embed_documents([texts[i] for i in missing])):
                vectors[i] = np.asarray(v, dtype="float32")
        return [max(0.0, float(np.dot(v, query))) for v in vectors]

    def _l2_positions(self) -> Dict[str, int]:
        """docstore id -> position in NEWS_L2, built once per loaded index (a reload replaces vs_l2).
        Two threads may build it at once; the second result simply replaces the first."""
        vs = self.vs_l2
        cached = self.__dict__.get("_positions")
        if cached is None or cached[0] is not vs:
            cached = (vs, {doc_id: pos for pos, doc_id in vs.index_to_docstore_id.items()})
            self._positions = cached
        return cached[1]

    @staticmethod
    def _get_existing_embedding_ids(vs: FAISS) -> Dict[Tuple[int, int, int], str]:
        """Maps (sitemap_id, chunk_level, chunk_index) -> the docstore key (embedding_id)
        it was stored under, for every document already in this index."""
        result = {}
        for doc_id, doc in vs.docstore._dict.items():
            meta = doc.metadata
            if {'sitemap_id', 'chunk_level', 'chunk_index'} <= meta.keys():
                result[(int(meta['sitemap_id']), int(meta['chunk_level']), int(meta['chunk_index']))] = doc_id
        return result
