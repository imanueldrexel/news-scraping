"""
NewsAggregator RAG Search Web UI

Run with:
    uvicorn newscrawler.web.app:app --reload --port 8000
"""

# Load .env BEFORE importing newscrawler modules: core.constants reads GEMINI_MODEL
# (and other settings) via os.getenv at import time. override=True so the .env value
# wins over any stale variable left in the shell environment (e.g. an old GEMINI_MODEL).
import os
from dotenv import load_dotenv
load_dotenv(
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"),
    override=True,
)

import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import (
    ChunkFAISSDatasource,
)
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
    SQLAlchemyNewsletterDataSource,
)
from newscrawler.core import web_copy
from newscrawler.core.constants import RAG_QUESTION_MAX_CHARS, RAG_WARM_AT_STARTUP
from newscrawler.core.newsletter_copy import tanggal
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
from newscrawler.web import filters as web_filters
from newscrawler.web.query_processor import FAILED, OK, AnswerResult, QueryProcessor, card
from newscrawler.web.session_manager import SessionManager
from newscrawler.web.site_stats import SiteStatsCache
from newscrawler.web.turn_store import TurnStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
# Under uvicorn the root logger is already configured, so basicConfig above is a no-op and
# this module's INFO lines (the warm-up time, SYS-102) would be dropped at WARNING.
logger.setLevel(logging.INFO)

# ── App setup ────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(_app):
    # SYS-102: load the embedding model and the FAISS indexes while the server starts
    # accepting requests, so the first question is not the slow one. A thread: start-up
    # does not wait for it, and a request that arrives first waits on _singleton_lock.
    if RAG_WARM_AT_STARTUP:
        threading.Thread(target=_warm_up, name="rag-warm-up", daemon=True).start()
    yield


app = FastAPI(title="NewsAggregator RAG Search", version="2.0.0", lifespan=_lifespan)

_BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_BASE / "templates"))
# SYS-101: every reader-facing string comes from the copy table.
templates.env.globals["copy"] = web_copy
templates.env.globals["max_chars"] = RAG_QUESTION_MAX_CHARS
app.mount("/static", StaticFiles(directory=str(_BASE / "static")), name="static")

# ── Singletons (initialised on first request to avoid slow startup) ───────────

_db_client: Optional[SQLAlchemyClient]       = None
_faiss_ds:  Optional[ChunkFAISSDatasource]   = None
_processor: Optional[QueryProcessor]         = None
_stats_ds:  Optional[SQLAlchemyNewsletterDataSource] = None
_site_stats: Optional[SiteStatsCache] = None
_sessions = SessionManager()
_turns = TurnStore()

# DBT-15 (#50): guards _processor/_stats_ds/_db_client construction. Without
# it, two simultaneous first requests each pass the `is None` check before
# either finishes constructing, so both build a ChunkFAISSDatasource (two
# embedding-model loads, two FAISS index loads, ~1 GB RAM) and one is
# discarded. Double-checked locking: the lock is only taken while the
# singleton is still None, so every call after warm-up is lock-free.
_singleton_lock = threading.Lock()


def _get_processor() -> QueryProcessor:
    global _db_client, _faiss_ds, _processor
    if _processor is None:
        with _singleton_lock:
            if _processor is None:
                if _db_client is None:
                    _db_client = SQLAlchemyClient()
                _faiss_ds  = ChunkFAISSDatasource()
                _processor = QueryProcessor(_faiss_ds, _db_client)
    return _processor


def _warm_up() -> None:
    start = time.monotonic()
    try:
        _get_processor().faiss_ds.search_l2("pemanasan", k=1)
        logger.info(f"RAG warm-up done in {time.monotonic() - start:.1f}s: the embedding model and FAISS are loaded.")
    except Exception as e:  # noqa: BLE001 -- the first request then loads them, as before
        logger.error(f"RAG warm-up failed after {time.monotonic() - start:.1f}s: {type(e).__name__}: {e}")


def _get_site_stats() -> SiteStatsCache:
    global _db_client, _site_stats
    if _site_stats is None:
        with _singleton_lock:
            if _site_stats is None:
                if _db_client is None:
                    _db_client = SQLAlchemyClient()
                _site_stats = SiteStatsCache(_db_client)
    return _site_stats


def _get_stats_ds() -> SQLAlchemyNewsletterDataSource:
    global _db_client, _stats_ds
    if _stats_ds is None:
        with _singleton_lock:
            if _stats_ds is None:
                if _db_client is None:
                    _db_client = SQLAlchemyClient()
                _stats_ds = SQLAlchemyNewsletterDataSource(_db_client)
    return _stats_ds


# DBT-16 (#51): the crawler is another process and saves NEWS_L1/L2 after
# every source; this process loads them once. Before a query, at most every
# FAISS_RELOAD_CHECK_S, the on-disk generation is compared with the loaded one
# (two stats) and a changed level is reloaded. One thread reloads at a time;
# the others keep searching the index they have.
FAISS_RELOAD_CHECK_S = float(os.getenv("FAISS_RELOAD_CHECK_S", 30))
_reload_lock = threading.Lock()
_last_reload_check = 0.0


def _refresh_faiss_if_stale() -> None:
    global _last_reload_check
    if _faiss_ds is None or time.monotonic() - _last_reload_check < FAISS_RELOAD_CHECK_S:
        return
    if not _reload_lock.acquire(blocking=False):
        return
    try:
        _last_reload_check = time.monotonic()
        _faiss_ds.refresh_stale()
    except Exception as e:  # noqa: BLE001 -- a failed reload must not fail the query
        logger.error(f"FAISS reload failed; still serving the index loaded at "
                     f"{getattr(_faiss_ds, 'loaded_at', {})}: {type(e).__name__}: {e}")
    finally:
        _reload_lock.release()


def _retrieve(question: str, filters, history: list) -> list:
    """DBT-15 (#50): the sync entry points handed to run_in_threadpool. _get_processor()
    itself must run inside the threadpool too -- calling it before the dispatch would block
    the event loop for the full model/index load if the warm-up has not finished."""
    processor = _get_processor()
    _refresh_faiss_if_stale()
    return processor.retrieve(question, filters, history=history)


def _answer(question: str, hits: list, history: list) -> AnswerResult:
    return _get_processor().answer(question, hits, history)


def _run_query(**kwargs) -> dict:
    processor = _get_processor()
    _refresh_faiss_if_stale()
    return processor.query(**kwargs)


def _question_notice(question: str) -> Optional[str]:
    if not question.strip():
        return web_copy.QUESTION_EMPTY
    if len(question) > RAG_QUESTION_MAX_CHARS:
        return web_copy.QUESTION_TOO_LONG.format(n=RAG_QUESTION_MAX_CHARS)
    return None


# ── Request/response models ───────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query:      str
    topic:      Optional[str] = None
    source:     Optional[str] = None
    rentang:    Optional[str] = None    # "", "7", "30", "custom"; without it the dates decide
    date_from:  Optional[str] = None    # YYYY-MM-DD
    date_to:    Optional[str] = None
    session_id: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    stats = await run_in_threadpool(lambda: _get_site_stats().get())
    today = date.today()
    return templates.TemplateResponse(request, "index.html", {
        "dateline": tanggal(today),
        "hero_line": web_copy.hero_line(stats.articles, stats.portals, stats.updated_wib, today),
        "topics": [(t, web_copy.topic_name(t)) for t in web_filters.TOPIC_CHOICES],
        "portals": stats.portal_options,
    })


@app.post("/api/query/form", response_class=HTMLResponse)
async def api_query_form(
    request: Request,
    query:      str = Form(""),
    topic:      str = Form(""),
    source:     str = Form(""),
    rentang:    str = Form(""),
    date_from:  str = Form(""),
    date_to:    str = Form(""),
    session_id: str = Form(""),
):
    """Step one of a turn (ADR-005): find the articles and render the question with its
    sources; the answer placeholder then asks /api/answer/{turn_id}. The search box sends
    no session id, so it always starts a new conversation; the follow-up form sends one
    (SYS-97), and the follow-up is retrieved with the conversation's questions (SYS-104)."""
    question = query.strip()
    filters = web_filters.parse(topic, source, rentang, date_from, date_to)
    context = {"question": question, "filters": filters, "cards": [], "result": None,
               "notice": _question_notice(query), "session_id": session_id or None, "turn_id": "notice"}
    if context["notice"] is None:
        sid = session_id or _sessions.new_session_id()
        hits = await run_in_threadpool(_retrieve, question, filters, _sessions.get_history(session_id))
        turn = _turns.put(question, sid, hits)
        context.update(session_id=sid, turn_id=turn.turn_id, cards=[card(h["n"], h) for h in hits])
    return templates.TemplateResponse(request, "_turn.html", context)


@app.post("/api/answer/{turn_id}", response_class=HTMLResponse)
async def api_answer(request: Request, turn_id: str):
    """Step two: the answer of a retrieved turn. A failed answer keeps the turn for
    "Coba lagi"; a final one (ok / unavailable / no_hits) releases it. Only an ok answer
    enters the conversation's history."""
    turn = _turns.get(turn_id)
    if turn is None:
        result = AnswerResult("expired")
    else:
        history = _sessions.get_history(turn.session_id)
        result = await run_in_threadpool(_answer, turn.question, turn.hits, history)
        if result.status != FAILED:
            _turns.done(turn_id)
        if result.status == OK:
            _sessions.update(turn.session_id, turn.question, result.text)
    return templates.TemplateResponse(request, "_answer.html", {"result": result, "turn_id": turn_id})


@app.post("/api/query")
async def api_query(body: QueryRequest):
    """The JSON API: retrieval and answer in one call."""
    notice = _question_notice(body.query)
    if notice is not None:
        return JSONResponse(status_code=422, content={"error": notice})
    session_id = body.session_id or _sessions.new_session_id()
    history = _sessions.get_history(session_id)
    filters = web_filters.parse(body.topic, body.source, body.rentang, body.date_from, body.date_to)
    # DBT-15 (#50): blocking work (FAISS, the encoder, psycopg2, the model's HTTP call) runs
    # in the threadpool, never on the event loop that also serves /api/health.
    result = await run_in_threadpool(_run_query, question=body.query.strip(), session_history=history,
                                     filters=filters)
    if result["answer_status"] == OK:
        _sessions.update(session_id, body.query.strip(), result["answer"])
    result["session_id"] = session_id
    return JSONResponse(content=result)


@app.get("/api/health")
async def api_health():
    # OPS-14: the payload is Postgres + file I/O. Run it in the threadpool so a
    # poller hitting this endpoint never stalls the event loop that serves
    # /api/query (the handler is async; sync work here would block everything).
    # DBT-15 (#50) covers the same problem for the other routes.
    payload = await run_in_threadpool(_health_payload)
    # OPS-06: a monitor keyed on the HTTP code has to see the failure too, not
    # only one keyed on the body.
    status_code = 200 if payload.get("status") == "ok" else 503
    return JSONResponse(content=jsonable_encoder(payload), status_code=status_code)


def _health_payload() -> dict:
    """OPS-06 (#54): a failed stats query must not read as a healthy zero.

    `get_stats` never raised -- it returned `{}` (now `None` per metric), so every
    `.get(key, 0)` below resolved to its default and the endpoint answered
    `{"status": "ok", "articles_indexed": 0, ...}` with HTTP 200 while the
    database was unreachable or a table was missing. The `degraded` branch was
    unreachable for the failure it was written for. It now reports which metrics
    failed, and the caller turns that into a non-200."""
    try:
        stats = _get_stats_ds().get_stats()
        errors = stats.get(SQLAlchemyNewsletterDataSource.ERRORS_KEY) or {}
        payload = {
            "status":           "degraded" if errors else "ok",
            "articles_indexed": stats.get("total_articles"),
            "chunks_indexed":   stats.get("total_chunks"),
            "last_crawl":       stats.get("last_crawl"),
            "digests_generated": stats.get("digests_generated"),
            # OPS-04: a gap between this and chunks_indexed is exactly the silent
            # divergence check_store_consistency.py exists to catch.
            "faiss_docs":       _faiss_doc_counts(),
            # DBT-16 (#51): what THIS process searches. When faiss_docs has moved
            # on and this has not, the process is serving an older snapshot.
            "faiss_in_memory":  _faiss_in_memory(),
        }
        if errors:
            # Named per metric: "which number is missing" is the operator's first
            # question, and it distinguishes one absent table from a dead DB.
            payload["errors"] = errors
        return payload
    except Exception as e:
        return {"status": "degraded", "error": f"{type(e).__name__}: {e}"}


def _faiss_in_memory() -> Optional[dict]:
    """{"NEWS_L1": {"loaded_at", "docs"}, ...} for the indexes this process
    has in memory; None before the first query loads them."""
    ds = _faiss_ds
    if ds is None:
        return None
    from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2
    loaded_at = getattr(ds, "loaded_at", {})
    return {name: {"loaded_at": loaded_at.get(db_name), "docs": vs.index.ntotal}
            for name, db_name, vs in (("NEWS_L1", VECTOR_DB_NAME_L1, ds.vs_l1),
                                      ("NEWS_L2", VECTOR_DB_NAME_L2, ds.vs_l2))}


# OPS-14: (index.faiss path) -> ((mtime_ns, size), ntotal). The pipeline rewrites
# index.faiss on every save_local, so a changed stat is the only invalidation needed.
_faiss_count_cache: dict = {}


def _faiss_doc_counts() -> dict:
    """{"NEWS_L1": n, "NEWS_L2": n} vector counts, None for an index that can't be
    read. Never raises -- a broken FAISS dir must not turn a working /api/health
    into a 500.

    OPS-14: counts come from the FAISS index header (`read_index` with
    IO_FLAG_MMAP maps the file and reads `ntotal`; ~13 ms + ~44 ms on the
    2026-09-18 corpus, no allocation), cached on the file's (mtime, size) so a
    poller pays nothing until the pipeline writes a new index. The previous
    version unpickled both docstores (37 MB + 83 MB) to call len() -- 2.1 s and
    304 MB per request, growing with the corpus. ntotal == docstore length for a
    LangChain FAISS store (add_documents/delete keep them in step), which is also
    what check_store_consistency.py's "total vectors" line reports.
    """
    from newscrawler.core.constants import VECTOR_DB_NAME_L1, VECTOR_DB_NAME_L2
    counts = {}
    for name, db_name in (("NEWS_L1", VECTOR_DB_NAME_L1), ("NEWS_L2", VECTOR_DB_NAME_L2)):
        path = os.path.join(db_name, "index.faiss")
        try:
            counts[name] = _faiss_ntotal(path)
        except Exception as e:
            counts[name] = None
            logger.warning(f"Could not read {name} vector count: {e}")
    return counts


def _faiss_ntotal(path: str) -> int:
    st = os.stat(path)
    stamp = (st.st_mtime_ns, st.st_size)
    cached = _faiss_count_cache.get(path)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    import faiss
    ntotal = faiss.read_index(path, faiss.IO_FLAG_MMAP | faiss.IO_FLAG_READ_ONLY).ntotal
    _faiss_count_cache[path] = (stamp, ntotal)
    return ntotal


@app.get("/api/stats")
async def api_stats():
    # DBT-15 (#50): get_stats() is a blocking Postgres call (and, on the
    # first request, blocking SQLAlchemyClient/SQLAlchemyNewsletterDataSource
    # construction) -- off the event loop, same as /api/health (OPS-14).
    return await run_in_threadpool(_stats_payload)


def _stats_payload() -> dict:
    try:
        return _get_stats_ds().get_stats()
    except Exception as e:
        return {"error": str(e)}
