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
