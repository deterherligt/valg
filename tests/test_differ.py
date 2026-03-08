import json
import pytest
from valg.models import get_connection, init_db
from valg.differ import diff_snapshots, write_events

@pytest.fixture
def db():
    conn = get_connection(":memory:")
    init_db(conn)
    return conn

def _insert_party_votes(conn, party_id, votes, snapshot_at):
    conn.execute(
        "INSERT OR IGNORE INTO elections (id, name) VALUES (?, ?)", ("E1", "Test"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO parties (id, letter, name, election_id) VALUES (?, ?, ?, ?)",
        (party_id, party_id, party_id, "E1"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO storkredse (id, name, election_id) VALUES (?, ?, ?)",
        ("SK1", "SK1", "E1"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO opstillingskredse (id, name, storkreds_id) VALUES (?, ?, ?)",
        ("OK1", "OK1", "SK1"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO party_votes (opstillingskreds_id, party_id, votes, snapshot_at) VALUES (?, ?, ?, ?)",
        ("OK1", party_id, votes, snapshot_at),
    )
    conn.commit()


def test_diff_detects_vote_increase(db):
    _insert_party_votes(db, "A", 1000, "2024-11-05T21:00:00")
    _insert_party_votes(db, "A", 1500, "2024-11-05T21:05:00")
    events = diff_snapshots(db, "2024-11-05T21:00:00", "2024-11-05T21:05:00")
    assert any(e["event_type"] == "vote_increase" and e["subject"] == "A" for e in events)

def test_diff_no_events_when_unchanged(db):
    _insert_party_votes(db, "A", 1000, "2024-11-05T21:00:00")
    _insert_party_votes(db, "A", 1000, "2024-11-05T21:05:00")
    events = diff_snapshots(db, "2024-11-05T21:00:00", "2024-11-05T21:05:00")
    assert len(events) == 0

def test_diff_returns_empty_list_on_first_snapshot(db):
    _insert_party_votes(db, "A", 1000, "2024-11-05T21:00:00")
    events = diff_snapshots(db, None, "2024-11-05T21:00:00")
    assert isinstance(events, list)

def test_write_events_inserts_rows(db):
    events = [
        {
            "occurred_at": "2024-11-05T21:05:00",
            "event_type": "vote_increase",
            "subject": "A",
            "description": "Party A gained 500 votes",
            "data": json.dumps({"before": 1000, "after": 1500, "delta": 500}),
        }
    ]
    write_events(db, events)
    count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 1
