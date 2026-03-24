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


def test_api_party_detail_storkreds_fields_present(db_night):
    """All four storkreds fields are present on every candidate in preliminary."""
    party_id = db_night.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    result = query_api_party_detail(db_night, [party_id])
    p = result[0]
    for c in p["candidates"]:
        assert "storkreds" in c, f"missing storkreds on {c['name']}"
        assert "sk_rank" in c, f"missing sk_rank on {c['name']}"
        assert "sk_seats" in c, f"missing sk_seats on {c['name']}"
        assert "elected" in c, f"missing elected on {c['name']}"
    # Preliminary: elected is always False
    assert all(c["elected"] is False for c in p["candidates"])


def test_api_party_detail_sk_rank_is_local(db_final):
    """sk_rank is 1-based and local to each storkreds, not global."""
    party_id = db_final.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    result = query_api_party_detail(db_final, [party_id])
    p = result[0]
    # Group by storkreds, check ranks start at 1 and are contiguous
    from collections import defaultdict
    by_sk = defaultdict(list)
    for c in p["candidates"]:
        by_sk[c["storkreds"]].append(c["sk_rank"])
    for sk_name, ranks in by_sk.items():
        assert min(ranks) == 1, f"sk_rank does not start at 1 in {sk_name}"
        assert sorted(ranks) == list(range(1, len(ranks) + 1)), \
            f"sk_ranks not contiguous in {sk_name}: {sorted(ranks)}"


def test_api_party_detail_cross_storkreds_elected():
    """Core scenario: candidate elected with fewer votes because they are in a smaller storkreds."""
    from valg.models import get_connection, init_db
    conn = get_connection(":memory:")
    init_db(conn)

    # Two storkredse: SK_A gets 2 kredsmandater, SK_B gets 5
    conn.execute("INSERT OR REPLACE INTO storkredse (id, name, n_kredsmandater) VALUES ('SK_A','Storkreds A',2)")
    conn.execute("INSERT OR REPLACE INTO storkredse (id, name, n_kredsmandater) VALUES ('SK_B','Storkreds B',5)")
    conn.execute("INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES ('OK_A','Kreds A','SK_A')")
    conn.execute("INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES ('OK_B','Kreds B','SK_B')")
    conn.execute("INSERT OR REPLACE INTO parties (id, letter, name) VALUES ('A','A','Parti A')")

    # Candidates: two in SK_A, one in SK_B
    conn.execute("INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES ('ca1','A1','A','OK_A',1)")
    conn.execute("INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES ('ca2','A2','A','OK_A',2)")
    conn.execute("INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES ('cb1','B1','A','OK_B',1)")

    snap = "2024-11-05T22:00:00"
    # Party votes: 1000 in SK_A, 0 in SK_B → D'Hondt gives party 2 seats in SK_A, 0 in SK_B
    conn.execute("INSERT INTO party_votes (opstillingskreds_id,party_id,votes,snapshot_at) VALUES ('OK_A','A',1000,?)", (snap,))

    # Fintælling results — B1 has more votes than A2, but B1 is in SK_B (0 seats)
    for cand_id, votes in [("ca1", 600), ("ca2", 300), ("cb1", 800)]:
        conn.execute(
            "INSERT INTO results (candidate_id,party_id,votes,count_type,snapshot_at) "
            "VALUES (?,?,?,'final',?)",
            (cand_id, "A", votes, snap),
        )
    conn.commit()

    result = query_api_party_detail(conn, ["A"])
    assert len(result) == 1
    p = result[0]
    by_id = {c["id"]: c for c in p["candidates"]}

    # A2 has fewer votes than B1 but is elected (SK_A has 2 seats, A2 is ranked #2)
    assert by_id["ca2"]["elected"] in ("kreds", "tillaeg"),  "A2 should be elected (SK_A seat #2)"
    assert by_id["cb1"]["elected"] is False, "B1 should not be elected (SK_B has 0 seats for party)"
    assert by_id["ca2"]["sk_rank"] == 2
    assert by_id["ca2"]["sk_seats"] == 2
    assert by_id["cb1"]["sk_rank"] == 1
    assert by_id["cb1"]["sk_seats"] == 0


def test_api_candidates_storkreds_fields(db_night):
    """query_api_candidates returns storkreds and storkreds_id on every candidate."""
    party_id = db_night.execute("SELECT id FROM parties LIMIT 1").fetchone()[0]
    from valg.queries import query_api_candidates
    rows = query_api_candidates(db_night, [party_id])
    assert len(rows) > 0
    for r in rows:
        assert "storkreds" in r, f"missing storkreds on {r['name']}"
        assert "storkreds_id" in r, f"missing storkreds_id on {r['name']}"
        assert isinstance(r["storkreds"], str)
        assert isinstance(r["storkreds_id"], str)


def test_api_party_detail_zero_seat_storkreds():
    """Candidates in a storkreds where party wins 0 seats have sk_seats=0 and elected=False."""
    from valg.models import get_connection, init_db
    conn = get_connection(":memory:")
    init_db(conn)

    conn.execute("INSERT OR REPLACE INTO storkredse (id, name, n_kredsmandater) VALUES ('SK_X','Storkreds X',3)")
    conn.execute("INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) VALUES ('OK_X','Kreds X','SK_X')")
    conn.execute("INSERT OR REPLACE INTO parties (id, letter, name) VALUES ('B','B','Parti B')")
    conn.execute("INSERT OR REPLACE INTO parties (id, letter, name) VALUES ('C','C','Parti C')")
    conn.execute("INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id, ballot_position) VALUES ('bx1','BX1','B','OK_X',1)")
    snap = "2024-11-05T22:00:00"
    # Party B has small votes; party C dominates — D'Hondt gives all 3 seats to C, 0 to B
    conn.execute("INSERT INTO party_votes (opstillingskreds_id,party_id,votes,snapshot_at) VALUES ('OK_X','B',100,?)", (snap,))
    conn.execute("INSERT INTO party_votes (opstillingskreds_id,party_id,votes,snapshot_at) VALUES ('OK_X','C',5000,?)", (snap,))
    conn.execute(
        "INSERT INTO results (candidate_id,party_id,votes,count_type,snapshot_at) "
        "VALUES ('bx1','B',500,'final',?)", (snap,)
    )
    conn.commit()

    result = query_api_party_detail(conn, ["B"])
    assert len(result) == 1
    c = result[0]["candidates"][0]
    assert c["sk_seats"] == 0
    assert c["elected"] is False


def test_party_votes_joined_by_nummer_when_dagi_id_differs():
    """party_votes using Nummer as ok_id still joins correctly via opstillingskredse.nummer."""
    from valg.models import get_connection, init_db
    from valg.queries import get_seat_data, get_reporting_progress
    conn = get_connection(":memory:")
    init_db(conn)

    conn.execute("INSERT OR REPLACE INTO storkredse (id, name, n_kredsmandater) VALUES ('1','København',18)")
    # Dagi_id is 403564 but Nummer is 1
    conn.execute("INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id, nummer) VALUES ('403564','Østerbro','1',1)")
    conn.execute("INSERT OR REPLACE INTO afstemningsomraader (id, name, opstillingskreds_id, eligible_voters) VALUES ('ao1','AO1','403564',10000)")
    conn.execute("INSERT OR REPLACE INTO parties (id, letter, name) VALUES ('A','A','Parti A')")

    snap = "2026-03-24T21:00:00"
    # party_votes references Nummer ("1"), NOT Dagi_id ("403564")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("INSERT INTO party_votes (opstillingskreds_id, party_id, votes, snapshot_at) VALUES ('1','A',5000,?)", (snap,))
    conn.commit()

    national, storkreds, kredsmandater = get_seat_data(conn)
    assert national.get("A", 0) == 5000, "national votes must come from party_votes"
    assert storkreds, "storkreds votes must not be empty (JOIN via nummer fallback)"
    assert storkreds.get("1", {}).get("A", 0) == 5000

    progress, national_pct = get_reporting_progress(conn)
    assert national_pct > 0, "reporting progress must not be zero"
