import time
import pytest
from pathlib import Path
from valg.sessions import SessionManager

SID1 = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
SID2 = "b2c3d4e5-f6a7-8901-bcde-f01234567891"
SID3 = "c3d4e5f6-a7b8-9012-cdef-012345678902"
SID4 = "d4e5f6a7-b8c9-0123-def0-123456789013"
SID_OLD = "aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"
SID_ACTIVE = "bbbbcccc-dddd-eeee-ffff-aaaabbbbcccc"
SID_UNKNOWN = "ccccdddd-eeee-ffff-aaaa-bbbbccccdddd"


@pytest.fixture
def mgr(tmp_path):
    return SessionManager(base_dir=tmp_path / "sessions", max_sessions=3)


def test_get_or_create_creates_session(mgr, tmp_path):
    s = mgr.get_or_create(SID1)
    assert s is not None
    assert s.session_id == SID1
    assert s.db_path.exists()
    assert s.data_dir.exists()
    assert s.runner is not None
    assert s.runner.commit_enabled is False


def test_get_or_create_returns_same_session(mgr):
    s1 = mgr.get_or_create(SID1)
    s2 = mgr.get_or_create(SID1)
    assert s1 is s2


def test_get_or_create_returns_none_at_cap(mgr):
    mgr.get_or_create(SID1)
    mgr.get_or_create(SID2)
    mgr.get_or_create(SID3)
    assert mgr.get_or_create(SID4) is None


def test_existing_session_bypasses_cap(mgr):
    mgr.get_or_create(SID1)
    mgr.get_or_create(SID2)
    mgr.get_or_create(SID3)
    # SID1 already exists — should return it even though cap is reached
    assert mgr.get_or_create(SID1) is not None


def test_get_returns_none_for_unknown(mgr):
    assert mgr.get(SID_UNKNOWN) is None


def test_get_returns_existing_session(mgr):
    mgr.get_or_create(SID1)
    s = mgr.get(SID1)
    assert s is not None
    assert s.session_id == SID1


def test_cleanup_removes_expired_sessions(mgr, tmp_path):
    s = mgr.get_or_create(SID_OLD)
    session_dir = s.db_path.parent
    # Force expiry by backdating last_seen
    s.last_seen = time.time() - mgr.TIMEOUT_SECONDS - 1
    mgr._cleanup()
    assert mgr.get(SID_OLD) is None
    assert not session_dir.exists()


def test_cleanup_keeps_active_sessions(mgr):
    mgr.get_or_create(SID_ACTIVE)
    mgr._cleanup()
    assert mgr.get(SID_ACTIVE) is not None


def test_get_or_create_rejects_path_traversal(mgr):
    assert mgr.get_or_create("../evil") is None
    assert mgr.get_or_create("../../etc/passwd") is None
    assert mgr.get_or_create("/absolute/path") is None


def test_get_rejects_path_traversal(mgr):
    assert mgr.get("../evil") is None
    assert mgr.get("../../etc/passwd") is None
    assert mgr.get("/absolute/path") is None


def test_switch_all_to_live_sets_live_flag(mgr):
    s1 = mgr.get_or_create(SID1)
    s2 = mgr.get_or_create(SID2)
    mgr.switch_all_to_live()
    assert s1.live is True
    assert s2.live is True


def test_switch_all_to_live_signals_stop_event(mgr):
    s1 = mgr.get_or_create(SID1)
    mgr.switch_all_to_live()
    assert s1.runner._stop_event.is_set()


def test_switch_all_to_live_preserves_session_directories(mgr):
    s1 = mgr.get_or_create(SID1)
    session_dir = s1.db_path.parent
    mgr.switch_all_to_live()
    assert session_dir.exists()
    assert s1.db_path.exists()


def test_switch_all_to_live_is_idempotent(mgr):
    s1 = mgr.get_or_create(SID1)
    mgr.switch_all_to_live()
    mgr.switch_all_to_live()  # second call must not raise
    assert s1.live is True
