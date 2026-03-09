# valg/queries.py
"""
Pure query functions returning list[dict] for CSV export and web display.
No Rich, no console output.
"""
from valg.cli import _get_seat_data
from valg import calculator


def query_status(conn) -> list[dict]:
    total_ao = conn.execute("SELECT COUNT(*) FROM afstemningsomraader").fetchone()[0]
    prelim_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type='preliminary'"
    ).fetchone()[0]
    final_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type='final'"
    ).fetchone()[0]

    national, storkreds, kredsmandater = _get_seat_data(conn)
    if not national:
        return []

    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    total_votes = sum(national.values()) or 1

    return [
        {
            "party": party,
            "votes": votes,
            "pct": round(votes / total_votes * 100, 1),
            "seats": seats.get(party, 0),
            "districts_prelim": prelim_ao,
            "districts_final": final_ao,
            "districts_total": total_ao,
        }
        for party, votes in sorted(national.items(), key=lambda x: -x[1])
    ]


def query_flip(conn) -> list[dict]:
    national, storkreds, kredsmandater = _get_seat_data(conn)
    if not national:
        return []

    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    rows = []
    for party in national:
        if seats.get(party, 0) > 0:
            gain = calculator.votes_to_gain_seat(party, national, storkreds, kredsmandater)
            lose = calculator.votes_to_lose_seat(party, national, storkreds, kredsmandater)
            rows.append({
                "party": party,
                "seats": seats[party],
                "votes_to_gain": gain,
                "votes_to_lose": lose,
            })

    return sorted(rows, key=lambda r: min(r["votes_to_gain"], r["votes_to_lose"]))[:10]


def query_party(conn, letter: str) -> list[dict]:
    letter = letter.upper()
    row = conn.execute(
        "SELECT id, name FROM parties WHERE letter = ? OR id = ?", (letter, letter)
    ).fetchone()
    if not row:
        return []

    national, storkreds, kredsmandater = _get_seat_data(conn)
    votes = national.get(row["id"], 0)
    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    gain = calculator.votes_to_gain_seat(row["id"], national, storkreds, kredsmandater)
    lose = calculator.votes_to_lose_seat(row["id"], national, storkreds, kredsmandater)

    return [{
        "party": row["name"],
        "votes": votes,
        "seats": seats.get(row["id"], 0),
        "votes_to_gain": gain,
        "votes_to_lose": lose,
    }]


def query_kreds(conn, name: str) -> list[dict]:
    ok = conn.execute(
        "SELECT id, name FROM opstillingskredse WHERE name LIKE ?", (f"%{name}%",)
    ).fetchone()
    if not ok:
        return []

    rows = conn.execute(
        "SELECT c.name, c.party_id, SUM(r.votes) as total "
        "FROM results r JOIN candidates c ON c.id = r.candidate_id "
        "WHERE c.opstillingskreds_id = ? AND r.count_type = 'final' "
        "GROUP BY c.id ORDER BY total DESC LIMIT 20",
        (ok["id"],),
    ).fetchall()
    return [{"candidate": r["name"], "party": r["party_id"], "votes": r["total"]} for r in rows]
