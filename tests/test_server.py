import json
import pytest
from unittest.mock import patch, MagicMock
from valg.server import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "test.db", data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"valg" in resp.data
    assert b"<pre" in resp.data


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
