import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

TURNS_KEPT = 5


class SessionManager:
    """A conversation's two memories, in this process (one uvicorn worker, ADR-005):
    - `history`: the answered turns, question and answer, for the answer prompt (SYS-97: only
      an ok answer enters it);
    - `questions`: every question asked, for retrieving a follow-up with its thread (SYS-104).
      A follow-up keeps its subject when the answers failed or the page has no provider."""

    def __init__(self, ttl_seconds: int = 1800, max_sessions: int = 200):
        self._sessions: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_sessions

    def get_history(self, session_id: Optional[str]) -> List[dict]:
        return self._read(session_id, "history")

    def get_questions(self, session_id: Optional[str]) -> List[dict]:
        """The questions asked in this session, oldest first, as [{"question": ...}]."""
        return [{"question": q} for q in self._read(session_id, "questions")]

    def update(self, session_id: str, question: str, answer: str) -> None:
        with self._lock:
            session = self._session(session_id)
            session["history"].append({"question": question, "answer": answer})
            session["history"] = session["history"][-TURNS_KEPT:]

    def record_question(self, session_id: str, question: str) -> None:
        with self._lock:
            session = self._session(session_id)
            session["questions"].append(question)
            session["questions"] = session["questions"][-TURNS_KEPT:]

    def new_session_id(self) -> str:
        return str(uuid.uuid4())

    def _read(self, session_id: Optional[str], key: str) -> list:
        if not session_id:
            return []
        with self._lock:
            self._evict_expired()
            session = self._sessions.get(session_id)
            if session:
                session["last_access"] = datetime.utcnow()
                return list(session[key])
        return []

    def _session(self, session_id: str) -> dict:
        """The session, created when new; the caller holds the lock."""
        self._evict_expired()
        if session_id not in self._sessions:
            if len(self._sessions) >= self._max:
                self._evict_oldest()
            self._sessions[session_id] = {"history": [], "questions": [], "last_access": datetime.utcnow()}
        session = self._sessions[session_id]
        session["last_access"] = datetime.utcnow()
        return session

    def _evict_expired(self):
        now = datetime.utcnow()
        expired = [
            sid for sid, s in self._sessions.items()
            if (now - s["last_access"]).total_seconds() > self._ttl
        ]
        for sid in expired:
            del self._sessions[sid]

    def _evict_oldest(self):
        if not self._sessions:
            return
        oldest = min(self._sessions, key=lambda sid: self._sessions[sid]["last_access"])
        del self._sessions[oldest]
