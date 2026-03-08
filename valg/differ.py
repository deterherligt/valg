import json
import logging
from typing import Optional

log = logging.getLogger(__name__)


def diff_snapshots(conn, prev_snapshot: Optional[str], curr_snapshot: str) -> list[dict]:
    """Compare party votes between two snapshots and return detected events."""
    if prev_snapshot is None:
        return []

    events = []

    prev = {r["party_id"]: r["votes"] for r in conn.execute(
        "SELECT party_id, SUM(votes) as votes FROM party_votes "
        "WHERE snapshot_at = ? GROUP BY party_id",
        (prev_snapshot,),
    ).fetchall()}

    curr = {r["party_id"]: r["votes"] for r in conn.execute(
        "SELECT party_id, SUM(votes) as votes FROM party_votes "
        "WHERE snapshot_at = ? GROUP BY party_id",
        (curr_snapshot,),
    ).fetchall()}

    for party_id, curr_votes in curr.items():
        prev_votes = prev.get(party_id, 0)
        delta = curr_votes - prev_votes
        if delta > 0:
            events.append({
                "occurred_at": curr_snapshot,
                "event_type": "vote_increase",
                "subject": party_id,
                "description": f"Party {party_id} gained {delta:,} votes",
                "data": json.dumps({"before": prev_votes, "after": curr_votes, "delta": delta}),
            })

    return events


def write_events(conn, events: list[dict]) -> None:
    for e in events:
        conn.execute(
            "INSERT INTO events (occurred_at, event_type, subject, description, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (e["occurred_at"], e["event_type"], e["subject"], e["description"], e["data"]),
        )
    if events:
        conn.commit()
        log.info("Wrote %d events", len(events))
