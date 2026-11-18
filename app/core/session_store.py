"""In-memory, single-process session store.

Only works with a single uvicorn worker (see design.md 6.1) — a plain dict
is not shared across processes. Swap this module for a Redis-backed
implementation behind the same interface if multi-worker scaling is needed.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Optional

import pandas as pd

MAX_CONCURRENT_SESSIONS = 50
SESSION_TTL_SECONDS = 30 * 60


@dataclass
class SessionData:
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    df: Optional[pd.DataFrame] = None
    cleaning_stats: dict[str, Any] = field(default_factory=dict)
    category_overrides: dict[str, str] = field(default_factory=dict)
    evaluation_examples: list[dict[str, str]] = field(default_factory=list)
    custom_categories: list[str] = field(default_factory=list)
    detected_columns: Optional[list[str]] = None
    needs_mapping: bool = False
    column_mapping: Optional[dict[str, str]] = None
    raw_files: dict[str, bytes] = field(default_factory=dict)


class SessionLimitExceeded(Exception):
    pass


class SessionStore:
    def __init__(self, max_sessions: int = MAX_CONCURRENT_SESSIONS, ttl_seconds: int = SESSION_TTL_SECONDS):
        self._store: dict[str, SessionData] = {}
        self._lock = Lock()
        self.max_sessions = max_sessions
        self.ttl_seconds = ttl_seconds

    def create(self) -> SessionData:
        with self._lock:
            self._purge_expired_locked()
            if len(self._store) >= self.max_sessions:
                raise SessionLimitExceeded(
                    f"Server is at capacity ({self.max_sessions} concurrent sessions). Please try again shortly."
                )
            session_id = str(uuid.uuid4())
            data = SessionData(session_id=session_id)
            self._store[session_id] = data
            return data

    def get(self, session_id: str) -> Optional[SessionData]:
        with self._lock:
            data = self._store.get(session_id)
            if data is None:
                return None
            if time.time() - data.last_active > self.ttl_seconds:
                del self._store[session_id]
                return None
            data.last_active = time.time()
            return data

    def touch(self, session_id: str) -> None:
        with self._lock:
            data = self._store.get(session_id)
            if data:
                data.last_active = time.time()

    def delete(self, session_id: str) -> bool:
        with self._lock:
            return self._store.pop(session_id, None) is not None

    def _purge_expired_locked(self) -> None:
        now = time.time()
        expired = [sid for sid, d in self._store.items() if now - d.last_active > self.ttl_seconds]
        for sid in expired:
            del self._store[sid]

    def purge_expired(self) -> int:
        with self._lock:
            before = len(self._store)
            self._purge_expired_locked()
            return before - len(self._store)

    def count(self) -> int:
        with self._lock:
            return len(self._store)


session_store = SessionStore()
