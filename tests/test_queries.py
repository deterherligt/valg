import pytest
from valg.models import get_connection, init_db
from valg.queries import query_status, query_flip, query_party, query_kreds, query_api_party_detail
from tests.synthetic.generator import generate_election, load_into_db


@pytest.fixture
def db_night():
    conn = get_connection(":memory:")
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    return conn


@pytest.fixture
def db_final(db_night):
    e = generate_election(seed=42)
    load_into_db(db_night, e, phase="final")
    return db_night


def test_query_status_returns_list_of_dicts(db_night):
    rows = query_status(db_night)
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert all({"party", "votes", "pct", "seats"} <= r.keys() for r in rows)


def test_query_status_sorted_by_votes_descending(db_night):
    rows = query_status(db_night)
    votes = [r["votes"] for r in rows]
    assert votes == sorted(votes, reverse=True)


def test_query_status_empty_db_returns_empty_list():
    conn = get_connection(":memory:")
    init_db(conn)
    assert query_status(conn) == []


def test_query_flip_returns_top_10(db_night):
    rows = query_flip(db_night)
    assert len(rows) <= 10
    assert all({"party", "seats", "votes_to_gain", "votes_to_lose"} <= r.keys() for r in rows)


def test_query_party_returns_dict_for_known_party(db_night):
    rows = query_party(db_night, "A")
    assert len(rows) == 1
    assert rows[0]["party"] is not None
    assert "votes" in rows[0]
    assert "seats" in rows[0]


def test_query_party_returns_empty_for_unknown(db_night):
    assert query_party(db_night, "Z") == []


def test_query_kreds_returns_candidates_after_final(db_final):
    rows = query_kreds(db_final, "Opstillingskreds 1")
    assert len(rows) > 0
    assert all({"candidate", "party", "votes"} <= r.keys() for r in rows)


def test_query_kreds_returns_empty_for_unknown(db_final):
    assert query_kreds(db_final, "nonexistent") == []


def test_get_seat_data_importable_from_queries():
    from valg.queries import get_seat_data  # noqa: F401 — just checking it exists here


def test_api_party_detail_candidates_preliminary(db_night):
    """During preliminary, candidates are sorted by ballot_position with has_votes=False."""
    party_id = db_night.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    result = query_api_party_detail(db_night, [party_id])
    assert len(result) == 1
    p = result[0]
    assert "candidates" in p
    assert "has_votes" in p
    assert "cutoff_margin" in p
    assert p["has_votes"] is False
    assert p["cutoff_margin"] is None
    positions = [c["ballot_position"] for c in p["candidates"]]
    assert positions == sorted(positions)
    assert all(c["votes"] is None for c in p["candidates"])


def test_api_party_detail_candidates_final(db_final):
    """During fintælling, candidates sorted by votes DESC with cutoff_margin computed."""
    party_id = db_final.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    result = query_api_party_detail(db_final, [party_id])
    assert len(result) == 1
    p = result[0]
    assert p["has_votes"] is True
    assert all(c["votes"] is not None for c in p["candidates"])
    votes = [c["votes"] for c in p["candidates"]]
    assert votes == sorted(votes, reverse=True)
    seats = p["seats_total"]
    if seats >= 1 and len(p["candidates"]) > seats:
        assert p["cutoff_margin"] is not None
        assert p["cutoff_margin"] >= 0
