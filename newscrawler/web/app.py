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
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
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
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
from newscrawler.web.query_processor import QueryProcessor
from newscrawler.web.session_manager import SessionManager

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="NewsAggregator RAG Search", version="1.0.0")

_BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_BASE / "templates"))
app.mount("/static", StaticFiles(directory=str(_BASE / "static")), name="static")

# ── Singletons (initialised on first request to avoid slow startup) ───────────

_db_client: Optional[SQLAlchemyClient]       = None
_faiss_ds:  Optional[ChunkFAISSDatasource]   = None
_processor: Optional[QueryProcessor]         = None
_stats_ds:  Optional[SQLAlchemyNewsletterDataSource] = None
_sessions = SessionManager()


def _get_processor() -> QueryProcessor:
    global _db_client, _faiss_ds, _processor
    if _processor is None:
        _db_client = SQLAlchemyClient()
        _faiss_ds  = ChunkFAISSDatasource()
        _processor = QueryProcessor(_faiss_ds, _db_client)
    return _processor


def _get_stats_ds() -> SQLAlchemyNewsletterDataSource:
    global _db_client, _stats_ds
    if _stats_ds is None:
        if _db_client is None:
            _db_client = SQLAlchemyClient()
        _stats_ds = SQLAlchemyNewsletterDataSource(_db_client)
    return _stats_ds


# ── Request/response models ───────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query:      str
    date_from:  Optional[str] = None
    date_to:    Optional[str] = None
    category:   Optional[str] = None
    source:     Optional[str] = None
    session_id: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/query")
async def api_query(request: Request, body: QueryRequest):
    session_id = body.session_id or _sessions.new_session_id()
    history    = _sessions.get_history(session_id)

    date_from = _parse_date(body.date_from)
    date_to   = _parse_date(body.date_to)

    result = _get_processor().query(
        question=body.query,
        session_history=history,
        date_from=date_from,
        date_to=date_to,
        category=body.category or None,
        source=body.source or None,
    )

    _sessions.update(session_id, body.query, result["answer"])
    result["session_id"] = session_id

    # Return HTML fragment for HTMX, JSON for direct API calls
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "result_fragment.html",
            {"request": request, "result": result, "question": body.query},
        )
    return JSONResponse(content=result)


@app.post("/api/query/form", response_class=HTMLResponse)
async def api_query_form(
    request: Request,
    query:      str          = Form(...),
    date_from:  str          = Form(""),
    date_to:    str          = Form(""),
    category:   str          = Form(""),
    source:     str          = Form(""),
    session_id: str          = Form(""),
):
    """Form-based endpoint for HTMX form submissions."""
    sid     = session_id or _sessions.new_session_id()
    history = _sessions.get_history(sid)

    result = _get_processor().query(
        question=query,
        session_history=history,
        date_from=_parse_date(date_from or None),
        date_to=_parse_date(date_to or None),
        category=category or None,
        source=source or None,
    )
    _sessions.update(sid, query, result["answer"])
    result["session_id"] = sid

    return templates.TemplateResponse(
        "result_fragment.html",
        {"request": request, "result": result, "question": query},
    )


@app.get("/api/health")
async def api_health():
    # OPS-14: the payload is Postgres + file I/O. Run it in the threadpool so a
    # poller hitting this endpoint never stalls the event loop that serves
    # /api/query (the handler is async; sync work here would block everything).
    # DBT-15 (#50) covers the same problem for the other routes.
    return await run_in_threadpool(_health_payload)


def _health_payload() -> dict:
    try:
        stats = _get_stats_ds().get_stats()
        return {
            "status":           "ok",
            "articles_indexed": stats.get("total_articles", 0),
            "chunks_indexed":   stats.get("total_chunks", 0),
            "last_crawl":       stats.get("last_crawl"),
            "digests_generated": stats.get("digests_generated", 0),
            # OPS-04: a gap between this and chunks_indexed is exactly the silent
            # divergence check_store_consistency.py exists to catch.
            "faiss_docs":       _faiss_doc_counts(),
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


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
    try:
        return _get_stats_ds().get_stats()
    except Exception as e:
        return {"error": str(e)}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
