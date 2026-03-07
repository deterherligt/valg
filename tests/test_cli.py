# tests/test_cli.py
import subprocess
import sys
import pytest
from pathlib import Path
from valg.models import get_connection, init_db
from valg.plugins import load_plugins
from tests.synthetic.generator import generate_election, load_into_db

@pytest.fixture(autouse=True)
def plugins():
    load_plugins()

@pytest.fixture
def night_db(tmp_path):
    db = tmp_path / "valg.db"
    conn = get_connection(db)
    init_db(conn)
    e = generate_election(n_parties=6, n_storkredse=3, n_districts=20, seed=42)
    load_into_db(conn, e, phase="preliminary")
    conn.close()
    return db, e

@pytest.fixture
def final_db(tmp_path):
    db = tmp_path / "valg.db"
    conn = get_connection(db)
    init_db(conn)
    e = generate_election(n_parties=6, n_storkredse=3, n_districts=20, seed=42)
    load_into_db(conn, e, phase="preliminary")
    load_into_db(conn, e, phase="final")
    conn.close()
    return db, e

def _run(args: list[str], db: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "valg", "--db", str(db)] + args,
        capture_output=True, text=True,
        cwd=str(Path(__file__).parent.parent),
    )

# --- status ---

def test_status_empty_db_shows_no_data(tmp_path):
    db = tmp_path / "empty.db"
    conn = get_connection(db); init_db(conn); conn.close()
    r = _run(["status"], db)
    assert r.returncode == 0
    assert "no data" in r.stdout.lower() or "0" in r.stdout

def test_status_night_shows_preliminary_count(night_db):
    db, _ = night_db
    r = _run(["status"], db)
    assert r.returncode == 0

def test_status_final_shows_both_counts(final_db):
    db, _ = final_db
    r = _run(["status"], db)
    assert r.returncode == 0

# --- flip ---

def test_flip_shows_output(night_db):
    db, _ = night_db
    r = _run(["flip"], db)
    assert r.returncode == 0
    assert len(r.stdout) > 0

def test_flip_shows_party_letters(night_db):
    db, election = night_db
    r = _run(["flip"], db)
    assert any(p["letter"] in r.stdout for p in election["parties"])

def test_flip_empty_db_does_not_crash(tmp_path):
    db = tmp_path / "empty.db"
    conn = get_connection(db); init_db(conn); conn.close()
    r = _run(["flip"], db)
    assert r.returncode == 0

# --- party ---

def test_party_shows_votes(night_db):
    db, election = night_db
    letter = election["parties"][0]["letter"]
    r = _run(["party", letter], db)
    assert r.returncode == 0
    assert len(r.stdout) > 0

def test_party_unknown_letter_does_not_crash(night_db):
    db, _ = night_db
    r = _run(["party", "Z"], db)
    assert r.returncode == 0

# --- candidate ---

def test_candidate_found_in_final_db(final_db):
    db, election = final_db
    name = election["candidates"][0]["name"]
    r = _run(["candidate", name], db)
    assert r.returncode == 0

def test_candidate_unknown_name_does_not_crash(night_db):
    db, _ = night_db
    r = _run(["candidate", "Ikke En Rigtig Kandidat"], db)
    assert r.returncode == 0

# --- feed ---

def test_feed_empty_returns_zero(tmp_path):
    db = tmp_path / "empty.db"
    conn = get_connection(db); init_db(conn); conn.close()
    r = _run(["feed"], db)
    assert r.returncode == 0

# --- commentary ---

def test_commentary_no_api_key_shows_message(night_db, monkeypatch):
    db, _ = night_db
    import os
    env = {k: v for k, v in os.environ.items() if k != "VALG_AI_API_KEY"}
    r = subprocess.run(
        [sys.executable, "-m", "valg", "--db", str(db), "commentary"],
        capture_output=True, text=True, env=env,
        cwd=str(Path(__file__).parent.parent),
    )
    assert r.returncode == 0
    # Should show a message about AI not being configured, not crash

# --- kreds ---

def test_kreds_shows_output(final_db):
    db, election = final_db
    ok_name = election["opstillingskredse"][0]["name"]
    r = _run(["kreds", ok_name], db)
    assert r.returncode == 0
