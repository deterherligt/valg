from __future__ import annotations

import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_VALID_SESSION_ID = re.compile(r'^[a-f0-9\-]{1,64}$')


@dataclass
class SessionState:
    session_id: str
    db_path: Path
    data_dir: Path
    runner: object  # DemoRunner — avoid circular import
    last_seen: float = field(default_factory=time.time)


class SessionManager:
    TIMEOUT_SECONDS = 1800   # 30 minutes
    CLEANUP_INTERVAL = 300   # 5 minutes

    def __init__(self, base_dir: Path, max_sessions: int = 5) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._max_sessions = max_sessions
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._start_cleanup_thread()

    def get_or_create(self, session_id: str) -> Optional[SessionState]:
        if not _VALID_SESSION_ID.match(session_id):
            return None
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].last_seen = time.time()
                return self._sessions[session_id]
            if len(self._sessions) >= self._max_sessions:
                return None
        # Create session outside the lock (I/O)
        session = self._create_session(session_id)
        with self._lock:
            # Re-check in case of concurrent creation
            if session_id in self._sessions:
                # Another thread beat us — clean up and return existing
                shutil.rmtree(session.db_path.parent, ignore_errors=True)
                self._sessions[session_id].last_seen = time.time()
                return self._sessions[session_id]
            if len(self._sessions) >= self._max_sessions:
                # Cap filled while we were creating — clean up
                shutil.rmtree(session.db_path.parent, ignore_errors=True)
                return None
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> Optional[SessionState]:
        if not _VALID_SESSION_ID.match(session_id):
            return None
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.last_seen = time.time()
            return session

    def _create_session(self, session_id: str) -> SessionState:
        from valg.demo import DemoRunner
        from valg.models import get_connection, init_db
        session_dir = self._base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        db_path = session_dir / "valg.db"
        data_dir = session_dir / "data"
        data_dir.mkdir(exist_ok=True)
        conn = get_connection(db_path)
        init_db(conn)
        conn.close()
        runner = DemoRunner(commit_enabled=False)
        return SessionState(
            session_id=session_id,
            db_path=db_path,
            data_dir=data_dir,
            runner=runner,
        )

    def _cleanup(self) -> None:
        """Remove expired sessions. Call with lock NOT held (stops runners outside lock)."""
        now = time.time()
        with self._lock:
            expired = [
                s for s in self._sessions.values()
                if now - s.last_seen > self.TIMEOUT_SECONDS
            ]
            for s in expired:
                del self._sessions[s.session_id]
        for s in expired:
            self._stop_and_delete(s)

    def _stop_and_delete(self, session: SessionState) -> None:
        runner = session.runner
        try:
            if hasattr(runner, "_stop_event"):
                runner._stop_event.set()
            if hasattr(runner, "_pause_event"):
                runner._pause_event.set()  # unblock if paused
            if hasattr(runner, "_thread") and runner._thread.is_alive():
                runner._thread.join(timeout=5.0)
        except Exception:
            pass
        shutil.rmtree(session.db_path.parent, ignore_errors=True)

    def _start_cleanup_thread(self) -> None:
        def loop() -> None:
            while True:
                time.sleep(self.CLEANUP_INTERVAL)
                self._cleanup()
        t = threading.Thread(target=loop, daemon=True)
        t.start()
