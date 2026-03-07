# tests/test_synthetic.py
import pytest
from valg.models import get_connection, init_db
from valg.plugins import load_plugins
from tests.synthetic.generator import generate_election, load_into_db

SEED = 42

@pytest.fixture(autouse=True)
def plugins():
    load_plugins()

@pytest.fixture
def election():
    return generate_election(n_parties=4, n_storkredse=3, n_districts=12, seed=SEED)

@pytest.fixture
def db_night(election):
    conn = get_connection(":memory:")
    init_db(conn)
    load_into_db(conn, election, phase="preliminary")
    return conn, election

@pytest.fixture
def db_final(election):
    conn = get_connection(":memory:")
    init_db(conn)
    load_into_db(conn, election, phase="preliminary")
    load_into_db(conn, election, phase="final")
    return conn, election


# --- generate_election structure ---

def test_generate_election_has_parties(election):
    assert len(election["parties"]) == 4

def test_generate_election_has_storkredse(election):
    assert len(election["storkredse"]) == 3

def test_generate_election_has_districts(election):
    assert len(election["afstemningsomraader"]) == 12

def test_generate_election_has_candidates(election):
    assert len(election["candidates"]) > 0

def test_generate_election_is_deterministic(election):
    election2 = generate_election(n_parties=4, n_storkredse=3, n_districts=12, seed=SEED)
    assert [p["id"] for p in election["parties"]] == [p["id"] for p in election2["parties"]]

def test_generate_election_candidates_have_party_id(election):
    for c in election["candidates"]:
        assert "party_id" in c
        assert c["party_id"] in {p["id"] for p in election["parties"]}


# --- load_into_db: preliminary phase ---

def test_load_preliminary_inserts_party_votes(db_night):
    conn, election = db_night
    count = conn.execute("SELECT COUNT(*) FROM party_votes").fetchone()[0]
    assert count > 0

def test_load_preliminary_sets_count_type_preliminary(db_night):
    conn, _ = db_night
    types = {r[0] for r in conn.execute("SELECT DISTINCT count_type FROM results").fetchall()}
    assert "preliminary" in types
    assert "final" not in types

def test_load_preliminary_inserts_geography(db_night):
    conn, election = db_night
    count = conn.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0]
    assert count == 3


# --- load_into_db: final phase ---

def test_load_final_adds_final_results(db_final):
    conn, _ = db_final
    count = conn.execute(
        "SELECT COUNT(*) FROM results WHERE count_type = 'final' AND candidate_id IS NOT NULL"
    ).fetchone()[0]
    assert count > 0

def test_load_final_does_not_erase_preliminary(db_final):
    conn, _ = db_final
    prelim = conn.execute(
        "SELECT COUNT(*) FROM results WHERE count_type = 'preliminary'"
    ).fetchone()[0]
    assert prelim > 0

def test_generate_election_has_opstillingskredse(election):
    assert len(election["opstillingskredse"]) == 3  # one per storkreds

def test_load_preliminary_party_results_have_null_candidate_id(db_night):
    conn, _ = db_night
    count = conn.execute(
        "SELECT COUNT(*) FROM results WHERE count_type = 'preliminary' AND candidate_id IS NOT NULL"
    ).fetchone()[0]
    assert count == 0, "Preliminary results should have no candidate-level rows"

def test_load_final_does_not_reload_geography(db_final):
    conn, election = db_final
    # Geography should be loaded exactly once (from preliminary phase)
    count = conn.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0]
    assert count == len(election["storkredse"])
