"""
End-to-end tests using synthetic data.
Each test corresponds directly to a use case in the design doc.
All tests load data into an in-memory SQLite DB via the synthetic generator,
then call the calculator and query functions that back the CLI commands.
"""
import pytest
from valg.models import get_connection, init_db
from valg.plugins import load_plugins
from valg import calculator
from tests.synthetic.generator import generate_election, load_into_db

SEED = 42


@pytest.fixture(autouse=True)
def plugins():
    load_plugins()


@pytest.fixture
def election():
    return generate_election(
        n_parties=8, n_storkredse=5, n_districts=50, seed=SEED
    )


@pytest.fixture
def db_night(election):
    """Election night DB — foreløbig optælling (party votes only)."""
    conn = get_connection(":memory:")
    init_db(conn)
    load_into_db(conn, election, phase="preliminary")
    return conn, election


@pytest.fixture
def db_final(election):
    """Fintælling DB — candidate votes available."""
    conn = get_connection(":memory:")
    init_db(conn)
    load_into_db(conn, election, phase="preliminary")
    load_into_db(conn, election, phase="final")
    return conn, election


# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_national_votes(conn):
    rows = conn.execute(
        "SELECT party_id, SUM(votes) as v FROM party_votes GROUP BY party_id"
    ).fetchall()
    if rows:
        return {r["party_id"]: r["v"] for r in rows}
    rows = conn.execute(
        "SELECT party_id, SUM(votes) as v FROM results "
        "WHERE candidate_id IS NULL GROUP BY party_id"
    ).fetchall()
    return {r["party_id"]: r["v"] for r in rows}


def _load_storkreds_votes(conn):
    rows = conn.execute(
        "SELECT pv.party_id, ok.storkreds_id, SUM(pv.votes) as v "
        "FROM party_votes pv "
        "JOIN opstillingskredse ok ON ok.id = pv.opstillingskreds_id "
        "GROUP BY pv.party_id, ok.storkreds_id"
    ).fetchall()
    result = {}
    for r in rows:
        result.setdefault(r["storkreds_id"], {})[r["party_id"]] = r["v"]
    return result


def _load_kredsmandat_seats(conn):
    rows = conn.execute("SELECT id, n_kredsmandater FROM storkredse").fetchall()
    return {r["id"]: (r["n_kredsmandater"] or 0) for r in rows}


# ─── UC1: Election night — party seats and flip margins ─────────────────────

def test_uc1_all_parties_have_vote_totals(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    assert len(national) == len(election["parties"])
    assert all(v > 0 for v in national.values())


def test_uc1_seat_projection_sums_to_175_or_less(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    assert sum(seats.values()) <= 175
    assert sum(seats.values()) > 0


def test_uc1_threshold_parties_get_zero_seats(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    total = sum(national.values())
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    for party, votes in national.items():
        if votes / total < 0.02:
            assert seats.get(party, 0) == 0


def test_uc1_flip_margins_are_positive_ints(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    # Test flip margin for the party with the most seats
    top_party = max(seats, key=seats.get)
    delta = calculator.votes_to_gain_seat(top_party, national, storkreds, ks)
    assert isinstance(delta, int)
    assert delta > 0


# ─── UC2: Storkreds breakdown ─────────────────────────────────────────────────

def test_uc2_storkreds_votes_queryable(db_night):
    conn, election = db_night
    storkreds = _load_storkreds_votes(conn)
    assert len(storkreds) == len(election["storkredse"])


def test_uc2_each_storkreds_has_all_parties(db_night):
    conn, election = db_night
    storkreds = _load_storkreds_votes(conn)
    party_ids = {p["id"] for p in election["parties"]}
    for sk_id, votes in storkreds.items():
        assert set(votes.keys()) == party_ids


def test_uc2_storkreds_kredsmandater_available(db_night):
    conn, election = db_night
    ks = _load_kredsmandat_seats(conn)
    assert sum(ks.values()) > 0


# ─── UC3: Seat flip margins per party ────────────────────────────────────────

def test_uc3_votes_to_gain_seat_for_each_party(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    for party in election["parties"]:
        pid = party["id"]
        if seats.get(pid, 0) > 0:
            delta = calculator.votes_to_gain_seat(pid, national, storkreds, ks)
            assert delta > 0

def test_uc3_votes_to_lose_seat_for_each_party(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    for party in election["parties"]:
        pid = party["id"]
        if seats.get(pid, 0) > 0:
            delta = calculator.votes_to_lose_seat(pid, national, storkreds, ks)
            assert delta > 0


# ─── UC4: Constituency flip feasibility ──────────────────────────────────────

def test_uc4_flip_feasibility_close_race_is_feasible(db_final):
    result = calculator.constituency_flip_feasibility(
        leader_votes=500,
        challenger_votes=450,
        uncounted_eligible_voters=300,
        historical_turnout_rate=0.75,
    )
    assert result["feasible"] is True
    assert result["gap"] == 50
    assert result["max_remaining"] == 225


def test_uc4_flip_feasibility_blowout_is_not_feasible(db_final):
    result = calculator.constituency_flip_feasibility(
        leader_votes=1000,
        challenger_votes=100,
        uncounted_eligible_voters=100,
        historical_turnout_rate=0.5,
    )
    assert result["feasible"] is False


# ─── UC5: Party list rankings ─────────────────────────────────────────────────

def test_uc5_candidate_rankings_ordered_by_votes(db_final):
    conn, election = db_final
    pid = election["parties"][0]["id"]
    rows = conn.execute(
        "SELECT c.id, c.name, SUM(r.votes) as total "
        "FROM results r "
        "JOIN candidates c ON c.id = r.candidate_id "
        "WHERE c.party_id = ? AND r.candidate_id IS NOT NULL AND r.count_type = 'final' "
        "GROUP BY c.id ORDER BY total DESC",
        (pid,),
    ).fetchall()
    assert len(rows) > 0
    totals = [r["total"] for r in rows]
    assert totals == sorted(totals, reverse=True)


def test_uc5_in_bubble_out_classification(db_final):
    conn, election = db_final
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)

    for party in election["parties"]:
        pid = party["id"]
        projected = seats.get(pid, 0)
        rows = conn.execute(
            "SELECT c.id, SUM(r.votes) as total "
            "FROM results r "
            "JOIN candidates c ON c.id = r.candidate_id "
            "WHERE c.party_id = ? AND r.candidate_id IS NOT NULL AND r.count_type='final' "
            "GROUP BY c.id ORDER BY total DESC",
            (pid,),
        ).fetchall()
        if len(rows) == 0 or projected == 0:
            continue
        in_candidates = rows[:projected]
        bubble = rows[projected] if len(rows) > projected else None
        assert all(r["total"] >= (bubble["total"] if bubble else 0)
                   for r in in_candidates)


# ─── UC6: Candidate tracking ─────────────────────────────────────────────────

def test_uc6_candidate_total_votes_queryable(db_final):
    conn, election = db_final
    candidate = election["candidates"][0]
    row = conn.execute(
        "SELECT SUM(votes) as total FROM results WHERE candidate_id = ? "
        "AND count_type = 'final'",
        (candidate["id"],),
    ).fetchone()
    assert row["total"] is not None
    assert row["total"] >= 0


def test_uc6_candidate_rank_within_party(db_final):
    conn, election = db_final
    pid = election["parties"][0]["id"]
    target_candidate = next(
        c for c in election["candidates"] if c["party_id"] == pid
    )
    all_candidates = conn.execute(
        "SELECT candidate_id, SUM(votes) as total FROM results "
        "WHERE party_id = ? AND candidate_id IS NOT NULL AND count_type='final' "
        "GROUP BY candidate_id ORDER BY total DESC",
        (pid,),
    ).fetchall()
    ids = [r["candidate_id"] for r in all_candidates]
    assert target_candidate["id"] in ids


def test_uc6_no_candidate_votes_before_fintaelling(db_night):
    conn, election = db_night
    count = conn.execute(
        "SELECT COUNT(*) FROM results WHERE candidate_id IS NOT NULL AND count_type='final'"
    ).fetchone()[0]
    assert count == 0, "Final candidate votes should not exist on election night"
