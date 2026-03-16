# valg/queries.py
"""
Pure query functions returning list[dict] for CSV export and web display.
No Rich, no console output.
"""
from valg import calculator


def get_seat_data(conn):
    """Return (national_votes, storkreds_votes, kredsmandater) for the calculator."""
    national = {
        r["party_id"]: r["v"]
        for r in conn.execute("""
            SELECT pv.party_id, SUM(pv.votes) as v
            FROM party_votes pv
            INNER JOIN (
                SELECT opstillingskreds_id, party_id, MAX(snapshot_at) as latest
                FROM party_votes
                GROUP BY opstillingskreds_id, party_id
            ) lat ON pv.opstillingskreds_id = lat.opstillingskreds_id
                  AND pv.party_id = lat.party_id
                  AND pv.snapshot_at = lat.latest
            GROUP BY pv.party_id
        """).fetchall()
    }
    if not national:
        national = {
            r["party_id"]: r["v"]
            for r in conn.execute(
                "SELECT party_id, SUM(votes) as v FROM results "
                "WHERE candidate_id IS NULL GROUP BY party_id"
            ).fetchall()
        }

    sk_rows = conn.execute("""
        SELECT pv.party_id, ok.storkreds_id, SUM(pv.votes) as v
        FROM party_votes pv
        INNER JOIN (
            SELECT opstillingskreds_id, party_id, MAX(snapshot_at) as latest
            FROM party_votes
            GROUP BY opstillingskreds_id, party_id
        ) lat ON pv.opstillingskreds_id = lat.opstillingskreds_id
              AND pv.party_id = lat.party_id
              AND pv.snapshot_at = lat.latest
        JOIN opstillingskredse ok ON ok.id = pv.opstillingskreds_id
        GROUP BY pv.party_id, ok.storkreds_id
    """).fetchall()
    storkreds: dict = {}
    for r in sk_rows:
        storkreds.setdefault(r["storkreds_id"], {})[r["party_id"]] = r["v"]

    kredsmandater = {
        r["id"]: (r["n_kredsmandater"] or 0)
        for r in conn.execute("SELECT id, n_kredsmandater FROM storkredse").fetchall()
    }
    return national, storkreds, kredsmandater


def query_status(conn) -> list[dict]:
    total_ao = conn.execute("SELECT COUNT(*) FROM afstemningsomraader").fetchone()[0]
    prelim_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type='preliminary'"
    ).fetchone()[0]
    final_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type='final'"
    ).fetchone()[0]

    national, storkreds, kredsmandater = get_seat_data(conn)
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
    national, storkreds, kredsmandater = get_seat_data(conn)
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

    national, storkreds, kredsmandater = get_seat_data(conn)
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


def query_api_status(conn) -> dict:
    districts_reported = conn.execute(
        "SELECT COUNT(DISTINCT opstillingskreds_id) FROM party_votes"
    ).fetchone()[0]
    districts_total = conn.execute(
        "SELECT COUNT(*) FROM opstillingskredse"
    ).fetchone()[0]
    return {
        "districts_reported": districts_reported,
        "districts_total": districts_total,
    }


def query_api_parties(conn) -> list[dict]:
    national, storkreds, kredsmandater = get_seat_data(conn)
    if not national:
        return []

    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    total_votes = sum(national.values()) or 1

    party_rows = {
        r["id"]: {"id": r["id"], "letter": r["letter"], "name": r["name"]}
        for r in conn.execute("SELECT id, letter, name FROM parties").fetchall()
    }

    result = []
    for party_id, votes in sorted(national.items(), key=lambda x: -x[1]):
        info = party_rows.get(party_id, {"id": party_id, "letter": None, "name": party_id})
        seat_count = seats.get(party_id, 0)
        gain = calculator.votes_to_gain_seat(party_id, national, storkreds, kredsmandater)
        lose = calculator.votes_to_lose_seat(party_id, national, storkreds, kredsmandater)
        result.append({
            "id": party_id,
            "letter": info["letter"],
            "name": info["name"],
            "votes": votes,
            "seats": seat_count,
            "pct": round(votes / total_votes * 100, 1),
            "gain": gain,
            "lose": lose,
        })
    return result


def query_api_candidates(conn, party_ids: list[str]) -> list[dict]:
    if not party_ids:
        return []
    placeholders = ",".join("?" * len(party_ids))
    rows = conn.execute(
        f"SELECT c.id, c.name, c.party_id, p.letter as party_letter, "
        f"ok.name as opstillingskreds, c.ballot_position "
        f"FROM candidates c "
        f"JOIN parties p ON c.party_id = p.id "
        f"JOIN opstillingskredse ok ON c.opstillingskreds_id = ok.id "
        f"WHERE c.party_id IN ({placeholders}) "
        f"ORDER BY c.party_id, c.ballot_position",
        party_ids,
    ).fetchall()
    return [dict(r) for r in rows]


def query_api_party_detail(conn, party_ids: list[str]) -> list[dict]:
    if not party_ids:
        return []

    national, storkreds_votes, kredsmandater = get_seat_data(conn)
    if not national:
        return []

    seats = calculator.allocate_seats_total(national, storkreds_votes, kredsmandater)
    total_votes = sum(national.values()) or 1

    storkreds_names = {
        r["id"]: r["name"]
        for r in conn.execute("SELECT id, name FROM storkredse").fetchall()
    }

    placeholders = ",".join("?" * len(party_ids))
    party_rows = {
        r["id"]: r
        for r in conn.execute(
            f"SELECT id, letter, name FROM parties WHERE id IN ({placeholders})",
            party_ids,
        ).fetchall()
    }

    result = []
    for party_id in party_ids:
        if party_id not in national:
            continue

        # Kredsmandater breakdown per storkreds (D'Hondt per storkreds)
        seats_breakdown = []
        for sk_id, sk_votes in storkreds_votes.items():
            n = kredsmandater.get(sk_id, 0)
            if n <= 0:
                continue
            sk_seats = calculator.dhondt(sk_votes, n)
            s = sk_seats.get(party_id, 0)
            if s > 0:
                seats_breakdown.append({
                    "name": storkreds_names.get(sk_id, sk_id),
                    "seats": s,
                })

        info = party_rows.get(party_id, {"id": party_id, "letter": None, "name": party_id})
        result.append({
            "id": party_id,
            "letter": info["letter"],
            "name": info["name"],
            "votes": national[party_id],
            "pct": round(national[party_id] / total_votes * 100, 1),
            "seats_total": seats.get(party_id, 0),
            "seats_by_storkreds": seats_breakdown,
        })
    return result


def query_api_candidate(conn, candidate_id: str) -> dict | None:
    row = conn.execute(
        "SELECT c.id, c.name, c.opstillingskreds_id, p.letter as party_letter "
        "FROM candidates c JOIN parties p ON c.party_id = p.id WHERE c.id = ?",
        (candidate_id,),
    ).fetchone()
    if not row:
        return None

    has_data = conn.execute(
        "SELECT 1 FROM results WHERE candidate_id = ? LIMIT 1", (candidate_id,)
    ).fetchone()
    if not has_data:
        return {"name": row["name"], "party_letter": row["party_letter"], "available": False}

    latest = conn.execute(
        "SELECT MAX(snapshot_at) FROM results WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()[0]

    districts = conn.execute(
        """
        SELECT ao.name, r.votes
        FROM afstemningsomraader ao
        LEFT JOIN results r
            ON r.afstemningsomraade_id = ao.id
            AND r.candidate_id = ?
            AND r.snapshot_at = ?
        WHERE ao.opstillingskreds_id = ?
        ORDER BY COALESCE(r.votes, -1) DESC
        """,
        (candidate_id, latest, row["opstillingskreds_id"]),
    ).fetchall()

    by_district = [{"name": d["name"], "votes": d["votes"]} for d in districts]
    reported = sum(1 for d in by_district if d["votes"] is not None)
    total_votes = sum(d["votes"] for d in by_district if d["votes"] is not None)

    return {
        "name": row["name"],
        "party_letter": row["party_letter"],
        "available": True,
        "total_votes": total_votes,
        "polling_districts_reported": reported,
        "polling_districts_total": len(by_district),
        "by_district": by_district,
    }


def query_api_feed(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT occurred_at, description FROM events ORDER BY occurred_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"occurred_at": r["occurred_at"], "description": r["description"]} for r in rows]


def query_api_candidate_feed(conn, candidate_id: str, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """
        WITH ordered AS (
            SELECT r.afstemningsomraade_id,
                   r.votes,
                   r.snapshot_at,
                   ao.name AS district_name
            FROM results r
            JOIN afstemningsomraader ao ON ao.id = r.afstemningsomraade_id
            WHERE r.candidate_id = ?
        ),
        deltas AS (
            SELECT district_name,
                   snapshot_at,
                   votes - LAG(votes, 1, 0) OVER (
                       PARTITION BY afstemningsomraade_id ORDER BY snapshot_at
                   ) AS delta
            FROM ordered
        )
        SELECT district_name, snapshot_at AS occurred_at, delta
        FROM deltas
        WHERE delta > 0
        ORDER BY occurred_at DESC
        LIMIT ?
        """,
        (candidate_id, limit),
    ).fetchall()
    return [
        {"occurred_at": r["occurred_at"], "district": r["district_name"], "delta": r["delta"]}
        for r in rows
    ]
