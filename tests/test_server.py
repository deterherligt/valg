import json
import pytest
from unittest.mock import patch, MagicMock
from valg.server import create_app
from tests.synthetic.generator import generate_election, load_into_db
from valg.models import get_connection, init_db


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "test.db", data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def client_with_data(tmp_path):
    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    conn.close()
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def client_with_final_data(tmp_path):
    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    load_into_db(conn, e, phase="final")
    conn.close()
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"valg" in resp.data
    assert b"alpine" in resp.data.lower()


def test_index_serves_alpine_app(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"x-data" in resp.data  # Alpine.js component marker
    assert b"alpine" in resp.data.lower()


def test_sync_status_returns_json(client):
    resp = client.get("/sync-status")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "last_sync" in data


def test_run_status_returns_text(client):
    resp = client.post("/run", json={"cmd": "status"})
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/plain")


def test_run_unknown_command_returns_400(client):
    resp = client.post("/run", json={"cmd": "nonexistent"})
    assert resp.status_code == 400


def test_csv_status_returns_csv(client):
    resp = client.get("/csv/status")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type


def test_csv_unsupported_command_returns_404(client):
    resp = client.get("/csv/feed")
    assert resp.status_code == 404


def test_run_party_with_letter(client):
    resp = client.post("/run", json={"cmd": "party", "letter": "A"})
    assert resp.status_code == 200


def test_run_candidate_with_name(client):
    resp = client.post("/run", json={"cmd": "candidate", "name": "Test"})
    assert resp.status_code == 200


def test_run_kreds_with_name(client):
    resp = client.post("/run", json={"cmd": "kreds", "name": "Test"})
    assert resp.status_code == 200


def test_api_status_returns_json(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "districts_reported" in data
    assert "districts_total" in data
    assert "last_sync" in data
    assert "just_synced" in data


def test_api_status_districts_reported_is_int(client):
    resp = client.get("/api/status")
    data = resp.get_json()
    assert isinstance(data["districts_reported"], int)
    assert isinstance(data["districts_total"], int)


def test_api_parties_returns_list(client):
    resp = client.get("/api/parties")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)


def test_api_parties_empty_db_returns_empty_list(client):
    resp = client.get("/api/parties")
    assert resp.get_json() == []


def test_api_parties_shape_when_data_present(client_with_data):
    resp = client_with_data.get("/api/parties")
    data = resp.get_json()
    assert len(data) > 0
    party = data[0]
    assert all(k in party for k in ["id", "letter", "name", "votes", "seats", "pct", "gain", "lose"])
    assert data == sorted(data, key=lambda p: -p["votes"])


def test_api_candidates_returns_list(client):
    resp = client.get("/api/candidates?party_ids=")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_api_candidates_shape(client_with_data):
    # Get a valid party id first
    parties = client_with_data.get("/api/parties").get_json()
    assert len(parties) > 0
    party_id = parties[0]["id"]

    resp = client_with_data.get(f"/api/candidates?party_ids={party_id}")
    data = resp.get_json()
    assert len(data) > 0
    c = data[0]
    assert all(k in c for k in ["id", "name", "party_id", "party_letter", "opstillingskreds", "ballot_position"])
    assert all(r["party_id"] == party_id for r in data)


def test_api_candidates_grouped_by_storkreds(client_with_data):
    parties = client_with_data.get("/api/parties").get_json()
    ids = ",".join(p["id"] for p in parties[:2])
    data = client_with_data.get(f"/api/candidates?party_ids={ids}").get_json()
    storkreds_seen = [r["storkreds"] for r in data]
    # Rows should be grouped by storkreds name
    assert storkreds_seen == sorted(storkreds_seen)


def test_api_party_detail_empty_ids_returns_empty(client):
    resp = client.get("/api/party-detail?party_ids=")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_api_party_detail_shape(client_with_data):
    parties = client_with_data.get("/api/parties").get_json()
    party_id = parties[0]["id"]
    resp = client_with_data.get(f"/api/party-detail?party_ids={party_id}")
    data = resp.get_json()
    assert len(data) == 1
    p = data[0]
    assert all(k in p for k in ["id", "letter", "name", "votes", "pct", "seats_total", "seats_by_storkreds"])
    assert isinstance(p["seats_by_storkreds"], list)


def test_api_candidate_unknown_returns_404(client):
    resp = client.get("/api/candidate/nonexistent")
    assert resp.status_code == 404


def test_api_candidate_before_fintaelling_returns_unavailable(client_with_data):
    # preliminary phase only — no candidate results
    parties = client_with_data.get("/api/parties").get_json()
    candidates = client_with_data.get(
        f"/api/candidates?party_ids={parties[0]['id']}"
    ).get_json()
    cid = candidates[0]["id"]
    resp = client_with_data.get(f"/api/candidate/{cid}")
    data = resp.get_json()
    assert data["available"] is False
    assert "name" in data
    assert "party_letter" in data
    assert "by_district" not in data


def test_api_candidate_after_fintaelling_returns_districts(client_with_final_data):
    parties = client_with_final_data.get("/api/parties").get_json()
    candidates = client_with_final_data.get(
        f"/api/candidates?party_ids={parties[0]['id']}"
    ).get_json()
    cid = candidates[0]["id"]
    resp = client_with_final_data.get(f"/api/candidate/{cid}")
    data = resp.get_json()
    assert data["available"] is True
    assert "total_votes" in data
    assert "by_district" in data
    assert "polling_districts_reported" in data
    assert "polling_districts_total" in data
    # votes=null means unreported, votes>=0 means reported
    for d in data["by_district"]:
        assert d["votes"] is None or isinstance(d["votes"], int)


def test_api_candidate_feed_returns_list(client):
    resp = client.get("/api/candidate-feed/nonexistent")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_api_candidate_feed_shape_after_multiple_snapshots(tmp_path):
    """Feed requires >=2 snapshots to produce deltas."""
    from valg.models import get_connection, init_db
    from tests.synthetic.generator import generate_election, load_into_db

    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    load_into_db(conn, e, phase="final")  # snapshot 2

    # Load a second final snapshot with different snapshot_at to get deltas
    import random
    rng = random.Random(99)
    snapshot2 = "2024-11-06T12:00:00"
    for ao in e["afstemningsomraader"]:
        for party in e["parties"]:
            for c in [c for c in e["candidates"]
                      if c["opstillingskreds_id"] == ao["opstillingskreds_id"]
                      and c["party_id"] == party["id"]]:
                votes = rng.randint(10, 600)
                conn.execute(
                    "INSERT OR IGNORE INTO results "
                    "(afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (ao["id"], party["id"], c["id"], votes, "final", snapshot2),
                )
    conn.commit()

    candidate_id = e["candidates"][0]["id"]

    from valg.server import create_app
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as client:
        resp = client.get(f"/api/candidate-feed/{candidate_id}")
        data = resp.get_json()
        assert isinstance(data, list)
        for item in data:
            assert "occurred_at" in item
            assert "district" in item
            assert "delta" in item
            assert item["delta"] > 0


def test_demo_state_not_enabled(client):
    """Without demo_runner, /demo/state returns 404."""
    resp = client.get("/demo/state")
    assert resp.status_code == 404


def test_demo_control_not_enabled(client):
    resp = client.post("/demo/control", json={"action": "pause"})
    assert resp.status_code == 404


def test_demo_state_enabled(tmp_path):
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=tmp_path / "repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/demo/state")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["enabled"] is True
        assert data["state"] == "idle"
        assert "Election Night" in data["scenarios"]


def test_demo_control_set_speed(tmp_path):
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=tmp_path / "repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post("/demo/control", json={"action": "set_speed", "speed": 5.0})
        assert resp.status_code == 200
        assert runner.speed == 5.0


def test_demo_state_accessible_without_demo_flag(tmp_path):
    """DemoRunner is always created; /demo/state must be reachable."""
    from valg.demo import DemoRunner
    app = create_app(
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "data",
        demo_runner=DemoRunner(),
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/demo/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["state"] == "idle"


def test_demo_control_unknown_action(tmp_path):
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=tmp_path / "repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post("/demo/control", json={"action": "explode"})
        assert resp.status_code == 400


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    monkeypatch.setenv("VALG_ADMIN_TOKEN", "test-secret")
    from valg.demo import DemoRunner
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=tmp_path / "data-repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, runner


def test_admin_demo_no_token_configured_returns_503(tmp_path, monkeypatch):
    monkeypatch.delenv("VALG_ADMIN_TOKEN", raising=False)
    from valg.demo import DemoRunner
    app = create_app(
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "data",
        demo_runner=DemoRunner(),
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post("/admin/demo", json={"scenario": "kv2025"})
    assert resp.status_code == 503


def test_admin_demo_wrong_token_returns_401(admin_client):
    c, _ = admin_client
    resp = c.post(
        "/admin/demo",
        json={"scenario": "kv2025"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_admin_demo_missing_token_returns_401(admin_client):
    c, _ = admin_client
    resp = c.post("/admin/demo", json={"scenario": "kv2025"})
    assert resp.status_code == 401


def test_admin_demo_unknown_scenario_returns_400(admin_client):
    c, _ = admin_client
    resp = c.post(
        "/admin/demo",
        json={"scenario": "nonexistent"},
        headers={"Authorization": "Bearer test-secret"},
    )
    assert resp.status_code == 400


def test_admin_demo_valid_starts_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("VALG_ADMIN_TOKEN", "test-secret")
    from valg.demo import DemoRunner, SCENARIOS
    from unittest.mock import patch
    runner = DemoRunner()
    scenario_name = next(iter(SCENARIOS))
    db = tmp_path / "test.db"
    data_repo = tmp_path / "data-repo"
    app = create_app(
        db_path=db,
        data_dir=tmp_path / "data",
        demo_runner=runner,
        data_repo=data_repo,
    )
    app.config["TESTING"] = True
    with patch.object(runner, "set_scenario") as mock_set, \
         patch.object(runner, "start") as mock_start:
        with app.test_client() as c:
            resp = c.post(
                "/admin/demo",
                json={"scenario": scenario_name},
                headers={"Authorization": "Bearer test-secret"},
            )
        assert resp.status_code == 200
        mock_set.assert_called_once_with(scenario_name)
        mock_start.assert_called_once_with(db_path=db, data_repo=data_repo)


def test_admin_demo_stop_valid_pauses_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("VALG_ADMIN_TOKEN", "test-secret")
    from valg.demo import DemoRunner
    from unittest.mock import patch
    runner = DemoRunner()
    app = create_app(
        db_path=tmp_path / "test.db",
        data_dir=tmp_path / "data",
        demo_runner=runner,
    )
    app.config["TESTING"] = True
    with patch.object(runner, "pause") as mock_pause:
        with app.test_client() as c:
            resp = c.post(
                "/admin/demo/stop",
                headers={"Authorization": "Bearer test-secret"},
            )
        assert resp.status_code == 200
        mock_pause.assert_called_once()


def test_admin_demo_stop_wrong_token_returns_401(admin_client):
    c, _ = admin_client
    resp = c.post(
        "/admin/demo/stop",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_demo_state_has_scenario_and_scenarios_fields(tmp_path):
    """Frontend demo bar needs scenario (current) and scenarios (list) fields."""
    from valg.demo import DemoRunner
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        demo_runner=DemoRunner(),
        data_repo=tmp_path / "repo",
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get("/demo/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "scenario" in data
    assert "scenarios" in data
    assert isinstance(data["scenarios"], list)
    assert len(data["scenarios"]) > 0
    assert "speed" in data
    assert "enabled" in data
    assert "state" in data


@pytest.fixture
def client_with_events(tmp_path):
    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    # Manually insert district_reported events
    ao_ids = [ao["id"] for ao in e["afstemningsomraader"]]
    for i, ao_id in enumerate(ao_ids[:3]):
        conn.execute(
            "INSERT INTO events (occurred_at, event_type, subject, description) "
            "VALUES (?,?,?,?)",
            (f"2024-11-05T21:0{i}:00", "district_reported", ao_id, "preliminary results"),
        )
    conn.commit()
    conn.close()
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_feed_places_empty(client):
    resp = client.get("/api/feed/places")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_feed_places_returns_newest_first(client_with_events):
    resp = client_with_events.get("/api/feed/places")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 3
    # newest first (highest event id first)
    assert data[0]["occurred_at"] > data[-1]["occurred_at"]
    item = data[0]
    assert "event_id" in item
    assert "place_id" in item      # afstemningsomraade id for /api/place/<id>
    assert "name" in item          # place name from afstemningsomraader
    assert "count_type" in item    # "foreløbig" or "fintælling"
    assert "occurred_at" in item
    assert item["count_type"] == "foreløbig"


def test_place_detail_one_snapshot_no_delta(client_with_data):
    # client_with_data has preliminary results loaded
    # Find an afstemningsomraade that has results
    e = generate_election(seed=42)
    ao_id = e["afstemningsomraader"][0]["id"]
    resp = client_with_data.get(f"/api/place/{ao_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "parties" in data
    assert "candidates" in data
    assert "name" in data
    assert "opstillingskreds" in data
    assert "count_type" in data
    assert "occurred_at" in data
    assert len(data["parties"]) > 0
    assert data["candidates"] == []  # no final data
    # Delta must be null for all parties (only one snapshot)
    for p in data["parties"]:
        assert p["delta"] is None


def test_place_detail_two_snapshots_has_delta(tmp_path):
    from valg.models import get_connection, init_db
    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    # Insert a second preliminary snapshot with different snapshot_at
    ao = e["afstemningsomraader"][0]
    party_id = e["parties"][0]["id"]
    conn.execute(
        "INSERT OR IGNORE INTO results "
        "(afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) "
        "VALUES (?,?,NULL,999,'preliminary','2024-11-05T23:00:00')",
        (ao["id"], party_id),
    )
    conn.commit()
    conn.close()

    from valg.server import create_app
    app = create_app(db_path=db, data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.get(f"/api/place/{ao['id']}")
        data = resp.get_json()
    # At least one party should have a non-null delta
    deltas = [p["delta"] for p in data["parties"]]
    assert any(d is not None for d in deltas)


def test_place_detail_with_final_has_candidates(client_with_final_data):
    e = generate_election(seed=42)
    ao_id = e["afstemningsomraader"][0]["id"]
    resp = client_with_final_data.get(f"/api/place/{ao_id}")
    data = resp.get_json()
    assert len(data["candidates"]) > 0
    for c in data["candidates"]:
        assert "name" in c
        assert "party_letter" in c
        assert "votes" in c


def test_place_detail_not_found(client):
    resp = client.get("/api/place/nonexistent-id")
    assert resp.status_code == 404


def test_feed_places_returns_all(client_with_events):
    resp = client_with_events.get("/api/feed/places")
    data = resp.get_json()
    assert len(data) == 3


import uuid
from valg.sessions import SessionManager


@pytest.fixture
def session_client(tmp_path):
    mgr = SessionManager(base_dir=tmp_path / "sessions", max_sessions=5)
    app = create_app(
        db_path=tmp_path / "valg.db",
        data_dir=tmp_path / "data",
        session_manager=mgr,
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, mgr


def test_index_sets_session_cookie(session_client):
    c, _ = session_client
    resp = c.get("/")
    assert resp.status_code == 200
    assert "valg_session" in resp.headers.get("Set-Cookie", "")


def test_index_reuses_existing_cookie(session_client):
    c, mgr = session_client
    sid = str(uuid.uuid4())
    mgr.get_or_create(sid)
    c.set_cookie("valg_session", sid)
    resp = c.get("/")
    assert resp.status_code == 200
    # No new session created — still just 1
    assert len(mgr._sessions) == 1


def test_api_parties_uses_session_db(session_client):
    c, mgr = session_client
    sid = str(uuid.uuid4())
    session = mgr.get_or_create(sid)
    # Write data into the session's DB
    from valg.models import get_connection, init_db
    from tests.synthetic.generator import generate_election, load_into_db
    conn = get_connection(session.db_path)
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    conn.close()
    c.set_cookie("valg_session", sid)
    resp = c.get("/api/parties")
    assert resp.status_code == 200
    parties = resp.get_json()
    assert len(parties) > 0


def test_demo_state_returns_unavailable_without_session(session_client):
    c, _ = session_client
    # No cookie set — no session
    resp = c.get("/demo/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is False
    assert data["state"] == "unavailable"


def test_demo_state_returns_runner_state_with_session(session_client):
    c, mgr = session_client
    sid = str(uuid.uuid4())
    mgr.get_or_create(sid)
    c.set_cookie("valg_session", sid)
    resp = c.get("/demo/state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["enabled"] is True
    assert data["state"] == "idle"


def test_demo_control_dispatches_to_session_runner(session_client):
    c, mgr = session_client
    sid = str(uuid.uuid4())
    mgr.get_or_create(sid)
    c.set_cookie("valg_session", sid)
    resp = c.post("/demo/control", json={"action": "set_speed", "speed": 5.0})
    assert resp.status_code == 200
    assert mgr.get(sid).runner.speed == 5.0


def test_demo_control_returns_404_without_session(session_client):
    c, _ = session_client
    resp = c.post("/demo/control", json={"action": "set_speed", "speed": 2.0})
    assert resp.status_code == 404


def test_two_sessions_see_independent_data(tmp_path):
    """Two sessions with different data in their DBs see only their own data."""
    from valg.sessions import SessionManager
    from valg.server import create_app
    from valg.models import get_connection, init_db
    from tests.synthetic.generator import generate_election, load_into_db

    mgr = SessionManager(base_dir=tmp_path / "sessions", max_sessions=5)
    app = create_app(
        db_path=tmp_path / "valg.db",
        data_dir=tmp_path / "data",
        session_manager=mgr,
    )
    app.config["TESTING"] = True

    sid_a = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())
    session_a = mgr.get_or_create(sid_a)
    session_b = mgr.get_or_create(sid_b)

    # Load data into session A only
    conn_a = get_connection(session_a.db_path)
    init_db(conn_a)
    e = generate_election(seed=1)
    load_into_db(conn_a, e, phase="preliminary")
    conn_a.close()

    # Session B has empty DB (init_db only, no data)
    with app.test_client() as c:
        c.set_cookie("valg_session", sid_a)
        resp_a = c.get("/api/parties")
        parties_a = resp_a.get_json()

    with app.test_client() as c:
        c.set_cookie("valg_session", sid_b)
        resp_b = c.get("/api/parties")
        parties_b = resp_b.get_json()

    assert len(parties_a) > 0, "Session A should see parties"
    assert len(parties_b) == 0, "Session B should see no parties (empty DB)"


def test_get_conn_uses_shared_db_when_session_live(tmp_path):
    """When session.live=True, _get_conn routes to the shared db, not the session db."""
    from valg.sessions import SessionManager
    from valg.models import get_connection, init_db
    from tests.synthetic.generator import generate_election, load_into_db

    shared_db = tmp_path / "shared.db"
    conn = get_connection(str(shared_db))
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    conn.close()

    sid = "aa000000-0000-0000-0000-000000000001"
    mgr = SessionManager(base_dir=tmp_path / "sessions", max_sessions=5)
    app = create_app(db_path=shared_db, data_dir=tmp_path / "data", session_manager=mgr)
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.set_cookie("valg_session", sid)
        c.get("/")
        # Session db is empty; shared db has parties
        session = mgr.get(sid)
        assert session is not None
        resp_before = c.get("/api/parties")
        assert resp_before.get_json() == []  # session db is empty

        session.live = True  # switch to live
        resp_after = c.get("/api/parties")
        assert len(resp_after.get_json()) > 0  # now reads from shared db


def test_demo_state_returns_disabled_when_session_live(tmp_path):
    """/demo/state returns enabled=false when session.live=True."""
    from valg.sessions import SessionManager

    sid = "aa000000-0000-0000-0000-000000000002"
    mgr = SessionManager(base_dir=tmp_path / "sessions", max_sessions=5)
    app = create_app(
        db_path=tmp_path / "v.db",
        data_dir=tmp_path / "data",
        session_manager=mgr,
    )
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.set_cookie("valg_session", sid)
        c.get("/")
        session = mgr.get(sid)
        assert session is not None
        # Before live switch: enabled=True
        resp = c.get("/demo/state")
        assert resp.get_json()["enabled"] is True

        session.live = True
        resp = c.get("/demo/state")
        assert resp.get_json()["enabled"] is False


def test_maybe_switch_to_live_triggers_once_on_real_results(tmp_path, monkeypatch):
    """switch_all_to_live is called exactly once even if _maybe_switch_to_live runs twice."""
    from unittest.mock import MagicMock
    import valg.server as srv
    from valg.server import _maybe_switch_to_live
    from valg.models import get_connection, init_db

    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO results (party_id, votes, count_type, snapshot_at) "
        "VALUES ('A', 100, 'preliminary', '2026-03-24T21:00:00')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(srv, "_live_data_available", False)
    mock_sm = MagicMock()
    _maybe_switch_to_live(db, mock_sm)
    _maybe_switch_to_live(db, mock_sm)  # second call must be a no-op
    mock_sm.switch_all_to_live.assert_called_once()


def test_api_candidates_includes_storkreds_fields(client_with_data):
    """GET /api/candidates returns storkreds and storkreds_id fields."""
    import json
    resp = client_with_data.get("/api/parties")
    parties = json.loads(resp.data)
    assert len(parties) > 0
    party_id = parties[0]["id"]

    resp = client_with_data.get(f"/api/candidates?party_ids={party_id}")
    assert resp.status_code == 200
    rows = json.loads(resp.data)
    assert len(rows) > 0
    assert "storkreds" in rows[0]
    assert "storkreds_id" in rows[0]


def test_maybe_switch_to_live_no_op_without_real_results(tmp_path, monkeypatch):
    """switch_all_to_live is NOT called when the shared db has no preliminary results."""
    from unittest.mock import MagicMock
    import valg.server as srv
    from valg.server import _maybe_switch_to_live
    from valg.models import get_connection, init_db

    db = tmp_path / "test.db"
    conn = get_connection(str(db))
    init_db(conn)
    conn.close()

    monkeypatch.setattr(srv, "_live_data_available", False)
    mock_sm = MagicMock()
    _maybe_switch_to_live(db, mock_sm)
    mock_sm.switch_all_to_live.assert_not_called()
