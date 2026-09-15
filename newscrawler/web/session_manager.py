import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional


class SessionManager:
    def __init__(self, ttl_seconds: int = 1800, max_sessions: int = 200):
        self._sessions: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_sessions

    def get_history(self, session_id: Optional[str]) -> List[dict]:
        if not session_id:
            return []
        with self._lock:
            self._evict_expired()
            session = self._sessions.get(session_id)
            if session:
                session["last_access"] = datetime.utcnow()
                return list(session["history"])
        return []

    def update(self, session_id: str, question: str, answer: str) -> None:
        with self._lock:
            self._evict_expired()
            if session_id not in self._sessions:
                if len(self._sessions) >= self._max:
                    self._evict_oldest()
                self._sessions[session_id] = {"history": [], "last_access": datetime.utcnow()}
            session = self._sessions[session_id]
            session["history"].append({"question": question, "answer": answer})
            session["history"] = session["history"][-5:]  # keep last 5 turns
            session["last_access"] = datetime.utcnow()

    def new_session_id(self) -> str:
        return str(uuid.uuid4())

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
