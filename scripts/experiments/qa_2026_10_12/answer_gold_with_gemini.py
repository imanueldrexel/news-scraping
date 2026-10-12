"""QA 2026-10-12 (SYS-107): the Done-when 'the gold question, unfiltered, cites an article of that day'
needs an answer, and the SumoPod key is blocked (401 since 2026-10-11). This asks it once in-process
with RAG_LLM_PROVIDER=gemini (free tier, one call, counted under web:gemini-*); retrieval is the
production path. Prints the answer, its citations and each cited card's date.

    venv\Scripts\python.exe scripts\experiments\qa_2026_10_12\answer_gold_with_gemini.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
os.environ["RAG_LLM_PROVIDER"] = "gemini"

from newscrawler.infrastructure.datasource.dataflow.write.faiss.chunk_faiss_data_source import ChunkFAISSDatasource  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402
from newscrawler.web.query_processor import QueryProcessor  # noqa: E402

Q = sys.argv[1] if len(sys.argv) > 1 else "Berapa harga emas Antam hari ini?"
qp = QueryProcessor(ChunkFAISSDatasource(), SQLAlchemyClient())
r = qp.query(question=Q, session_history=[], filters=None, thread=[])
print("status:", r.get("answer_status"))
print("answer:", r.get("answer"))
for i, s in enumerate(r.get("sources", []), 1):
    print(f"[{i}] {s.get('posted_at')} {s.get('source')} {s.get('title', '')[:80]}")
