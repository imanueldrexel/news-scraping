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
    try:
        stats = _get_stats_ds().get_stats()
        return {
            "status":           "ok",
            "articles_indexed": stats.get("total_articles", 0),
            "chunks_indexed":   stats.get("total_chunks", 0),
            "last_crawl":       stats.get("last_crawl"),
            "digests_generated": stats.get("digests_generated", 0),
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


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
