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


def test_api_candidates_grouped_by_party(client_with_data):
    parties = client_with_data.get("/api/parties").get_json()
    ids = ",".join(p["id"] for p in parties[:2])
    data = client_with_data.get(f"/api/candidates?party_ids={ids}").get_json()
    party_ids_seen = [r["party_id"] for r in data]
    # Rows should be grouped (all of party 1 before all of party 2)
    assert party_ids_seen == sorted(party_ids_seen)


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


def test_api_feed_returns_list(client):
    resp = client.get("/api/feed")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


def test_api_feed_shape_when_events_exist(client_with_data):
    # We can't easily test shape without events — just check the structure is a list
    resp = client_with_data.get("/api/feed")
    data = resp.get_json()
    assert isinstance(data, list)
    # Each item should have occurred_at and description if list is non-empty
    for item in data:
        assert "occurred_at" in item
        assert "description" in item


def test_api_feed_respects_limit(client):
    resp = client.get("/api/feed?limit=5")
    assert resp.status_code == 200


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


def test_feed_places_cursor_pagination(client_with_events):
    # Get all 3, then fetch with before_id of the second item
    all_resp = client_with_events.get("/api/feed/places")
    all_data = all_resp.get_json()
    assert len(all_data) == 3
    second_id = all_data[1]["event_id"]
    page2 = client_with_events.get(f"/api/feed/places?before_id={second_id}")
    page2_data = page2.get_json()
    # Only entries older than second_id (id < second_id)
    assert len(page2_data) == 1
    assert all(item["event_id"] < second_id for item in page2_data)
