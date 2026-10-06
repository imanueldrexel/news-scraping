"""Turns waiting for their answer (ADR-005, SYS-102's two-step loading).

The page asks in two requests: retrieval renders the question and its sources
at once, then the answer placeholder asks for the answer by turn id. In between,
the retrieved articles wait here. A turn leaves the store when its answer is
final; a failed answer keeps it, so "Coba lagi" can ask again. In memory, one
process: the app runs as a single uvicorn worker (OPERATIONS.md).
"""
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Turn:
    turn_id: str
    question: str
    session_id: str
    hits: List[dict]
    created: float = field(default_factory=time.monotonic)


class TurnStore:
    def __init__(self, ttl_seconds: int = 900, max_turns: int = 500, clock=time.monotonic):
        self._turns: Dict[str, Turn] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max = max_turns
        self._clock = clock

    def put(self, question: str, session_id: str, hits: List[dict]) -> Turn:
        turn = Turn(uuid.uuid4().hex[:12], question, session_id, hits, self._clock())
        with self._lock:
            self._evict()
            if len(self._turns) >= self._max:
                del self._turns[min(self._turns, key=lambda t: self._turns[t].created)]
            self._turns[turn.turn_id] = turn
        return turn

    def get(self, turn_id: str) -> Optional[Turn]:
        with self._lock:
            self._evict()
            return self._turns.get(turn_id)

    def done(self, turn_id: str) -> None:
        with self._lock:
            self._turns.pop(turn_id, None)

    def _evict(self) -> None:
        now = self._clock()
        for turn_id in [t for t, turn in self._turns.items() if now - turn.created > self._ttl]:
            del self._turns[turn_id]
