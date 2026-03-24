from __future__ import annotations
# valg/queries.py
"""
Pure query functions returning list[dict] for CSV export and web display.
No Rich, no console output.
"""
from collections import defaultdict

from valg import calculator
from valg.calculator import TURNOUT_ESTIMATE


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
    # Also get national + storkreds from results table
    results_national = {
        r["party_id"]: r["v"]
        for r in conn.execute("""
            SELECT r.party_id, SUM(r.votes) as v
            FROM results r
            INNER JOIN (
                SELECT afstemningsomraade_id, party_id, MAX(snapshot_at) as latest
                FROM results
                WHERE candidate_id IS NULL
                GROUP BY afstemningsomraade_id, party_id
            ) lat ON r.afstemningsomraade_id = lat.afstemningsomraade_id
                  AND r.party_id = lat.party_id
                  AND r.snapshot_at = lat.latest
            WHERE r.candidate_id IS NULL AND r.votes > 0
            GROUP BY r.party_id
        """).fetchall()
    }
    results_storkreds: dict = {}
    for r in conn.execute("""
        SELECT r.party_id, ok.storkreds_id, SUM(r.votes) as v
        FROM results r
        INNER JOIN (
            SELECT afstemningsomraade_id, party_id, MAX(snapshot_at) as latest
            FROM results
            WHERE candidate_id IS NULL
            GROUP BY afstemningsomraade_id, party_id
        ) lat ON r.afstemningsomraade_id = lat.afstemningsomraade_id
              AND r.party_id = lat.party_id
              AND r.snapshot_at = lat.latest
        JOIN afstemningsomraader ao ON ao.id = r.afstemningsomraade_id
        JOIN opstillingskredse ok ON ok.id = ao.opstillingskreds_id
        WHERE r.candidate_id IS NULL AND r.votes > 0
        GROUP BY r.party_id, ok.storkreds_id
    """).fetchall():
        results_storkreds.setdefault(r["storkreds_id"], {})[r["party_id"]] = r["v"]

    # Use whichever source has more total votes (results wins on election night)
    pv_total = sum(national.values())
    results_total = sum(results_national.values())
    if results_total > pv_total:
        national = results_national

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

    # Use results storkreds if it has more data
    pv_sk_total = sum(v for sk in storkreds.values() for v in sk.values())
    results_sk_total = sum(v for sk in results_storkreds.values() for v in sk.values())
    if results_sk_total > pv_sk_total:
        storkreds = results_storkreds

    # Hardcoded fallback — Folketingsvalglov bilag 3
    _KREDS_FALLBACK = {
        "1": 18, "2": 12, "3": 9, "4": 2, "5": 18,
        "6": 12, "7": 19, "8": 16, "9": 16, "10": 13,
    }
    kredsmandater = {}
    for r in conn.execute("SELECT id, n_kredsmandater FROM storkredse").fetchall():
        kredsmandater[r["id"]] = r["n_kredsmandater"] or _KREDS_FALLBACK.get(r["id"], 0)
    # If storkredse table is empty or has no kredsmandater, use hardcoded values
    if sum(kredsmandater.values()) == 0:
        kredsmandater = dict(_KREDS_FALLBACK)
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

    progress, national_pct = get_reporting_progress(conn)
    projected = calculator.project_storkreds_votes(storkreds, progress)
    projected_national = {}
    for sk_votes in projected.values():
        for party, votes in sk_votes.items():
            projected_national[party] = projected_national.get(party, 0) + votes

    detail = calculator.allocate_seats_detail(projected_national, projected, kredsmandater)
    total_votes = sum(national.values()) or 1

    return [
        {
            "party": party,
            "votes": votes,
            "pct": round(votes / total_votes * 100, 1),
            "seats": detail.get(party, {}).get("total", 0),
            "kreds_seats": detail.get(party, {}).get("kreds", 0),
            "tillaeg_seats": detail.get(party, {}).get("tillaeg", 0),
            "reporting_pct": round(national_pct * 100, 1),
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
    preliminary_places = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM turnout"
    ).fetchone()[0]
    final_places = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type = 'final'"
    ).fetchone()[0]
    total_places = conn.execute(
        "SELECT COUNT(*) FROM afstemningsomraader"
    ).fetchone()[0]
    return {
        "districts_reported": districts_reported,
        "districts_total": districts_total,
        "preliminary_places": preliminary_places,
        "final_places": final_places,
        "total_places": total_places,
    }


def query_api_parties(conn) -> list[dict]:
    national, storkreds, kredsmandater = get_seat_data(conn)
    if not national:
        return []

    progress, national_pct = get_reporting_progress(conn)
    projected = calculator.project_storkreds_votes(storkreds, progress)
    projected_national = {}
    for sk_votes in projected.values():
        for party, votes in sk_votes.items():
            projected_national[party] = projected_national.get(party, 0) + votes

    detail = calculator.allocate_seats_detail(projected_national, projected, kredsmandater)
    total_votes = sum(national.values()) or 1

    party_rows = {
        r["id"]: {"id": r["id"], "letter": r["letter"], "name": r["name"]}
        for r in conn.execute("SELECT id, letter, name FROM parties").fetchall()
    }

    result = []
    for party_id, votes in sorted(national.items(), key=lambda x: -x[1]):
        info = party_rows.get(party_id, {"id": party_id, "letter": None, "name": party_id})
        d = detail.get(party_id, {})
        seat_count = d.get("total", 0)
        gain = calculator.votes_to_gain_seat(party_id, national, storkreds, kredsmandater)
        lose = calculator.votes_to_lose_seat(party_id, national, storkreds, kredsmandater)
        result.append({
            "id": party_id,
            "letter": info["letter"],
            "name": info["name"],
            "votes": votes,
            "seats": seat_count,
            "kreds_seats": d.get("kreds", 0),
            "tillaeg_seats": d.get("tillaeg", 0),
            "reporting_pct": round(national_pct * 100, 1),
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
        f"ok.name as opstillingskreds, c.ballot_position, "
        f"sk.name as storkreds, sk.id as storkreds_id "
        f"FROM candidates c "
        f"JOIN parties p ON c.party_id = p.id "
        f"JOIN opstillingskredse ok ON c.opstillingskreds_id = ok.id "
        f"JOIN storkredse sk ON sk.id = ok.storkreds_id "
        f"WHERE c.party_id IN ({placeholders}) "
        f"ORDER BY sk.name, c.party_id, c.ballot_position",
        party_ids,
    ).fetchall()
    # Deduplicate: same person can have one candidacy per opstillingskreds.
    # Rows are already ordered by ballot_position ASC, so first occurrence = best position.
    seen: set[tuple] = set()
    result = []
    for r in rows:
        key = (r["name"], r["party_id"])
        if key not in seen:
            seen.add(key)
            result.append(dict(r))
    return result


def query_api_party_detail(conn, party_ids: list[str]) -> list[dict]:
    if not party_ids:
        return []

    national, storkreds_votes, kredsmandater = get_seat_data(conn)
    if not national:
        return []

    progress, national_pct = get_reporting_progress(conn)
    projected = calculator.project_storkreds_votes(storkreds_votes, progress)
    projected_national = {}
    for sk_votes in projected.values():
        for party, votes in sk_votes.items():
            projected_national[party] = projected_national.get(party, 0) + votes

    seats_detail = calculator.allocate_seats_detail(projected_national, projected, kredsmandater)
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

    # Check if fintælling candidate data exists (global for this election)
    has_votes = bool(
        conn.execute(
            "SELECT 1 FROM results WHERE candidate_id IS NOT NULL AND count_type = 'final' LIMIT 1"
        ).fetchone()
    )

    result = []
    for party_id in party_ids:
        if party_id not in national:
            continue

        # Seat breakdown from allocate_seats_detail
        party_detail = seats_detail.get(party_id, {})
        kreds_by_sk = party_detail.get("kreds_by_storkreds", {})
        tillaeg_by_sk = party_detail.get("tillaeg_by_storkreds", {})
        sk_seats_for_party: dict[str, int] = {}
        sk_kreds_for_party: dict[str, int] = {}
        seats_breakdown = []
        all_sk_ids = set(kreds_by_sk.keys()) | set(tillaeg_by_sk.keys())
        for sk_id in all_sk_ids:
            kreds_s = kreds_by_sk.get(sk_id, 0)
            tillaeg_s = tillaeg_by_sk.get(sk_id, 0)
            sk_seats_for_party[sk_id] = kreds_s + tillaeg_s
            sk_kreds_for_party[sk_id] = kreds_s
            if kreds_s > 0 or tillaeg_s > 0:
                seats_breakdown.append({
                    "name": storkreds_names.get(sk_id, sk_id),
                    "seats": kreds_s,
                    "tillaeg": tillaeg_s,
                })

        # Candidate breakdown
        if has_votes:
            cand_rows = conn.execute(
                """
                SELECT c.id, c.name, ok.name AS opstillingskreds, c.ballot_position,
                       SUM(r.votes) AS votes, ok.storkreds_id, sk.name AS storkreds_name
                FROM candidates c
                JOIN opstillingskredse ok ON ok.id = c.opstillingskreds_id
                JOIN storkredse sk ON sk.id = ok.storkreds_id
                JOIN results r ON r.candidate_id = c.id
                WHERE c.party_id = ? AND r.count_type = 'final'
                GROUP BY c.id
                ORDER BY votes DESC
                """,
                (party_id,),
            ).fetchall()
        else:
            cand_rows = conn.execute(
                """
                SELECT c.id, c.name, ok.name AS opstillingskreds, c.ballot_position,
                       NULL AS votes, ok.storkreds_id, sk.name AS storkreds_name
                FROM candidates c
                JOIN opstillingskredse ok ON ok.id = c.opstillingskreds_id
                JOIN storkredse sk ON sk.id = ok.storkreds_id
                WHERE c.party_id = ?
                ORDER BY c.ballot_position
                """,
                (party_id,),
            ).fetchall()

        raw_candidates = [
            {
                "id": r["id"],
                "name": r["name"],
                "opstillingskreds": r["opstillingskreds"],
                "ballot_position": r["ballot_position"],
                "votes": r["votes"],
                "storkreds": r["storkreds_name"],
                "_sk_id": r["storkreds_id"],
            }
            for r in cand_rows
        ]

        # Merge multi-kreds candidacies: the same person can appear on the ballot
        # in multiple opstillingskredse within a storkreds (each gets a unique ID
        # in the source data). Deduplicate by (name, storkreds), summing votes and
        # keeping the opstillingskreds/ballot_position of their best-performing entry.
        merged: dict[tuple, dict] = {}
        for c in raw_candidates:
            key = (c["name"], c["_sk_id"])
            if key not in merged:
                merged[key] = c.copy()
            else:
                existing = merged[key]
                c_votes = c["votes"] or 0
                ex_votes = existing["votes"] or 0
                if has_votes:
                    existing["votes"] = ex_votes + c_votes
                    if c_votes > ex_votes:
                        existing["opstillingskreds"] = c["opstillingskreds"]
                        existing["ballot_position"] = c["ballot_position"]
                else:
                    if c["ballot_position"] < existing["ballot_position"]:
                        existing["opstillingskreds"] = c["opstillingskreds"]
                        existing["ballot_position"] = c["ballot_position"]
        candidates = sorted(
            merged.values(),
            key=lambda c: (c["votes"] or 0) if has_votes else c["ballot_position"],
            reverse=has_votes,
        )

        # Annotate each candidate with per-storkreds rank and election status.
        # Candidates are already in national order (votes DESC or ballot_position ASC).
        # Ranks are computed within each storkreds independently.
        sk_groups: dict = defaultdict(list)
        for c in candidates:
            sk_groups[c["_sk_id"]].append(c)

        for sk_id, group in sk_groups.items():
            sk_party_seats = sk_seats_for_party.get(sk_id, 0)
            sk_kreds = sk_kreds_for_party.get(sk_id, 0)
            if has_votes:
                ranked = sorted(group, key=lambda c: (c["votes"] or 0), reverse=True)
            else:
                ranked = sorted(group, key=lambda c: c["ballot_position"])
            for rank, c in enumerate(ranked, 1):
                c["sk_rank"] = rank
                c["sk_seats"] = sk_party_seats
                c["sk_kreds_seats"] = sk_kreds
                if has_votes and rank <= sk_party_seats:
                    c["elected"] = "kreds" if rank <= sk_kreds else "tillaeg"
                else:
                    c["elected"] = False

        for c in candidates:
            del c["_sk_id"]

        # Cutoff margin: difference between last candidate in and first candidate out
        party_seats = party_detail.get("total", 0)
        cutoff_margin = None
        if has_votes and party_seats >= 1 and len(candidates) > party_seats:
            last_in = candidates[party_seats - 1]["votes"]
            first_out = candidates[party_seats]["votes"]
            if last_in is not None and first_out is not None:
                cutoff_margin = last_in - first_out

        info = party_rows.get(party_id, {"id": party_id, "letter": None, "name": party_id})
        result.append({
            "id": party_id,
            "letter": info["letter"],
            "name": info["name"],
            "votes": national[party_id],
            "pct": round(national[party_id] / total_votes * 100, 1),
            "seats_total": party_seats,
            "kreds_seats": party_detail.get("kreds", 0),
            "tillaeg_seats": party_detail.get("tillaeg", 0),
            "seats_by_storkreds": seats_breakdown,
            "candidates": candidates,
            "has_votes": has_votes,
            "cutoff_margin": cutoff_margin,
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
        FROM results r
        JOIN afstemningsomraader ao ON ao.id = r.afstemningsomraade_id
        WHERE r.candidate_id = ?
          AND r.snapshot_at = ?
        ORDER BY COALESCE(r.votes, 0) DESC
        """,
        (candidate_id, latest),
    ).fetchall()

    by_district = [{"name": d["name"], "votes": d["votes"]} for d in districts]
    total_votes = sum(d["votes"] for d in by_district if d["votes"] is not None)

    return {
        "name": row["name"],
        "party_letter": row["party_letter"],
        "available": True,
        "total_votes": total_votes,
        "polling_districts_reported": len(by_district),
        "polling_districts_total": len(by_district),
        "by_district": by_district,
    }


def query_place_detail(conn, place_id: str) -> dict | None:
    ao = conn.execute(
        "SELECT ao.id, ao.name, ao.opstillingskreds_id, ok.name AS opstillingskreds "
        "FROM afstemningsomraader ao "
        "JOIN opstillingskredse ok ON ok.id = ao.opstillingskreds_id "
        "WHERE ao.id = ?",
        (place_id,),
    ).fetchone()
    if not ao:
        return None

    # Two most recent distinct snapshot_at values for this place
    snaps = conn.execute(
        "SELECT DISTINCT snapshot_at FROM results "
        "WHERE afstemningsomraade_id = ? AND candidate_id IS NULL "
        "ORDER BY snapshot_at DESC LIMIT 2",
        (place_id,),
    ).fetchall()
    if not snaps:
        # No AO-level results yet — show opstillingskreds-level party votes
        ok_snaps = conn.execute(
            "SELECT DISTINCT snapshot_at FROM party_votes "
            "WHERE opstillingskreds_id = ? ORDER BY snapshot_at DESC LIMIT 1",
            (ao["opstillingskreds_id"],),
        ).fetchall()
        ok_snap = ok_snaps[0]["snapshot_at"] if ok_snaps else None
        parties = []
        if ok_snap:
            pv_rows = conn.execute(
                "SELECT pv.party_id, pv.votes, p.letter, p.name "
                "FROM party_votes pv JOIN parties p ON p.id = pv.party_id "
                "WHERE pv.opstillingskreds_id = ? AND pv.snapshot_at = ? "
                "ORDER BY pv.votes DESC",
                (ao["opstillingskreds_id"], ok_snap),
            ).fetchall()
            parties = [
                {"party_id": r["party_id"], "letter": r["letter"], "name": r["name"],
                 "votes": r["votes"], "delta": None}
                for r in pv_rows
            ]
        return {
            "id": ao["id"],
            "name": ao["name"],
            "opstillingskreds": ao["opstillingskreds"],
            "count_type": "foreløbig",
            "occurred_at": ok_snap,
            "parties": parties,
            "candidates": [],
        }

    latest_snap = snaps[0]["snapshot_at"]
    prev_snap = snaps[1]["snapshot_at"] if len(snaps) > 1 else None

    def _party_votes_at(snap_at: str) -> dict:
        """Return {party_id: row} preferring 'final' over 'preliminary'."""
        rows = conn.execute(
            "WITH ranked AS ("
            "  SELECT party_id, votes, count_type, "
            "  ROW_NUMBER() OVER (PARTITION BY party_id ORDER BY count_type ASC) AS rn "
            "  FROM results "
            "  WHERE afstemningsomraade_id = ? AND snapshot_at = ? AND candidate_id IS NULL"
            ") SELECT party_id, votes, count_type FROM ranked WHERE rn = 1",
            (place_id, snap_at),
        ).fetchall()
        return {r["party_id"]: r for r in rows}

    latest_rows = _party_votes_at(latest_snap)
    prev_rows = _party_votes_at(prev_snap) if prev_snap else {}

    # Dominant count_type for header (prefer 'final')
    count_types = {r["count_type"] for r in latest_rows.values()}
    count_type_db = "final" if "final" in count_types else "preliminary"
    count_type_display = "fintælling" if count_type_db == "final" else "foreløbig"

    # Build party list with deltas
    party_meta = {
        r["id"]: r
        for r in conn.execute(
            "SELECT id, letter, name FROM parties WHERE id IN ("
            + ",".join("?" * len(latest_rows)) + ")",
            list(latest_rows.keys()),
        ).fetchall()
    } if latest_rows else {}

    parties = []
    for party_id, row in sorted(latest_rows.items(), key=lambda x: -x[1]["votes"]):
        meta = party_meta.get(party_id, {"letter": party_id, "name": party_id})
        prev = prev_rows.get(party_id)
        delta = (row["votes"] - prev["votes"]) if prev else None
        parties.append({
            "party_id": party_id,
            "letter": meta["letter"],
            "name": meta["name"],
            "votes": row["votes"],
            "delta": delta,
        })

    # Candidate votes (only present for 'final' count) — use latest snapshot that has candidates
    latest_cand_snap = conn.execute(
        "SELECT MAX(snapshot_at) FROM results "
        "WHERE afstemningsomraade_id = ? AND candidate_id IS NOT NULL",
        (place_id,),
    ).fetchone()[0]

    cand_rows = []
    if latest_cand_snap:
        cand_rows = conn.execute(
            "WITH ranked AS ("
            "  SELECT r.candidate_id, r.votes, c.name AS cand_name, p.letter AS party_letter, "
            "  ROW_NUMBER() OVER (PARTITION BY r.candidate_id ORDER BY r.count_type ASC) AS rn "
            "  FROM results r "
            "  JOIN candidates c ON c.id = r.candidate_id "
            "  JOIN parties p ON p.id = c.party_id "
            "  WHERE r.afstemningsomraade_id = ? AND r.snapshot_at = ? "
            "    AND r.candidate_id IS NOT NULL"
            ") SELECT candidate_id, votes, cand_name, party_letter FROM ranked WHERE rn = 1 "
            "ORDER BY votes DESC",
            (place_id, latest_cand_snap),
        ).fetchall()

    candidates = [
        {"name": r["cand_name"], "party_letter": r["party_letter"], "votes": r["votes"]}
        for r in cand_rows
    ]

    return {
        "name": ao["name"],
        "opstillingskreds": ao["opstillingskreds"],
        "count_type": count_type_display,
        "occurred_at": latest_snap,
        "parties": parties,
        "candidates": candidates,
    }


def query_feed_places(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT e.id AS event_id, e.subject, ao.name, e.occurred_at, e.description,
               sk.name AS storkreds
        FROM events e
        JOIN afstemningsomraader ao ON ao.id = e.subject
        JOIN opstillingskredse ok ON ok.id = ao.opstillingskreds_id
        JOIN storkredse sk ON sk.id = ok.storkreds_id
        WHERE e.event_type = 'district_reported'
        ORDER BY e.id DESC
        """,
        [],
    ).fetchall()
    return [
        {
            "event_id": r["event_id"],
            "place_id": r["subject"],
            "name": r["name"],
            "occurred_at": r["occurred_at"],
            "count_type": "fintælling" if "final" in r["description"] else "foreløbig",
            "storkreds": r["storkreds"],
        }
        for r in rows
    ]


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


def get_reporting_progress(conn) -> tuple[dict[str, float], float]:
    # Try party_votes first, fall back to results
    rows = conn.execute("""
        SELECT ok.storkreds_id, SUM(pv.votes) as reported
        FROM party_votes pv
        INNER JOIN (
            SELECT opstillingskreds_id, party_id, MAX(snapshot_at) as latest
            FROM party_votes
            GROUP BY opstillingskreds_id, party_id
        ) lat ON pv.opstillingskreds_id = lat.opstillingskreds_id
              AND pv.party_id = lat.party_id
              AND pv.snapshot_at = lat.latest
        JOIN opstillingskredse ok ON ok.id = pv.opstillingskreds_id
        GROUP BY ok.storkreds_id
    """).fetchall()

    if not rows or sum(r["reported"] or 0 for r in rows) == 0:
        rows = conn.execute("""
            SELECT ok.storkreds_id, SUM(r.votes) as reported
            FROM results r
            INNER JOIN (
                SELECT afstemningsomraade_id, party_id, MAX(snapshot_at) as latest
                FROM results
                WHERE candidate_id IS NULL
                GROUP BY afstemningsomraade_id, party_id
            ) lat ON r.afstemningsomraade_id = lat.afstemningsomraade_id
                  AND r.party_id = lat.party_id
                  AND r.snapshot_at = lat.latest
            JOIN afstemningsomraader ao ON ao.id = r.afstemningsomraade_id
            JOIN opstillingskredse ok ON ok.id = ao.opstillingskreds_id
            WHERE r.candidate_id IS NULL AND r.votes > 0
            GROUP BY ok.storkreds_id
        """).fetchall()

    # Get eligible voters from turnout table (2026 data doesn't have it in geography)
    eligible_by_sk = {}
    for r in conn.execute("""
        SELECT ok.storkreds_id, SUM(t.eligible_voters) as eligible
        FROM turnout t
        JOIN afstemningsomraader ao ON ao.id = t.afstemningsomraade_id
        JOIN opstillingskredse ok ON ok.id = ao.opstillingskreds_id
        GROUP BY ok.storkreds_id
    """).fetchall():
        eligible_by_sk[str(r["storkreds_id"])] = r["eligible"] or 0

    progress = {}
    total_reported = 0
    total_eligible = 0
    for r in rows:
        sk_id = str(r["storkreds_id"])
        reported = r["reported"] or 0
        eligible = eligible_by_sk.get(sk_id, 0)
        expected = eligible * TURNOUT_ESTIMATE if eligible > 0 else 0
        total_reported += reported
        total_eligible += eligible
        # If no eligible data, assume 100% reporting when votes exist
        if expected > 0:
            progress[sk_id] = min(1.0, reported / expected)
        else:
            progress[sk_id] = 1.0 if reported > 0 else 0.0

    total_expected = total_eligible * TURNOUT_ESTIMATE
    national_pct = min(1.0, total_reported / total_expected) if total_expected > 0 else (1.0 if total_reported > 0 else 0.0)

    return progress, national_pct
