# valg/models.py
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "valg.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS elections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    election_date TEXT,
    synced_at TEXT
);
CREATE TABLE IF NOT EXISTS valglandsdele (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS regioner (
    id TEXT PRIMARY KEY,
    code INTEGER,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kommuner (
    id TEXT PRIMARY KEY,
    code INTEGER,
    name TEXT NOT NULL,
    region_id TEXT REFERENCES regioner(id)
);
CREATE TABLE IF NOT EXISTS storkredse (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    election_id TEXT REFERENCES elections(id),
    n_kredsmandater INTEGER
);
CREATE TABLE IF NOT EXISTS opstillingskredse (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    storkreds_id TEXT REFERENCES storkredse(id),
    nummer INTEGER
);
CREATE TABLE IF NOT EXISTS afstemningsomraader (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    opstillingskreds_id TEXT REFERENCES opstillingskredse(id),
    municipality_name TEXT,
    eligible_voters INTEGER
);
CREATE TABLE IF NOT EXISTS parties (
    id TEXT PRIMARY KEY,
    letter TEXT,
    name TEXT NOT NULL,
    election_id TEXT REFERENCES elections(id)
);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    party_id TEXT REFERENCES parties(id),
    opstillingskreds_id TEXT REFERENCES opstillingskredse(id),
    ballot_position INTEGER
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    afstemningsomraade_id TEXT REFERENCES afstemningsomraader(id),
    party_id TEXT REFERENCES parties(id),
    candidate_id TEXT REFERENCES candidates(id),
    votes INTEGER,
    count_type TEXT,
    snapshot_at TEXT
);
CREATE TABLE IF NOT EXISTS turnout (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    afstemningsomraade_id TEXT REFERENCES afstemningsomraader(id),
    eligible_voters INTEGER,
    votes_cast INTEGER,
    snapshot_at TEXT
);
CREATE TABLE IF NOT EXISTS party_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opstillingskreds_id TEXT REFERENCES opstillingskredse(id),
    party_id TEXT REFERENCES parties(id),
    votes INTEGER,
    snapshot_at TEXT,
    UNIQUE(opstillingskreds_id, party_id, snapshot_at)
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    subject     TEXT,
    description TEXT,
    data        TEXT
);
CREATE TABLE IF NOT EXISTS anomalies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at  TEXT NOT NULL,
    filename     TEXT,
    anomaly_type TEXT NOT NULL,
    detail       TEXT
);

CREATE INDEX IF NOT EXISTS idx_results_party_snapshot    ON results(party_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_results_ao_snapshot       ON results(afstemningsomraade_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_results_candidate_snap    ON results(candidate_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_party_votes_party_snap    ON party_votes(party_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_turnout_ao_snapshot       ON turnout(afstemningsomraade_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_events_type_time          ON events(event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_type_id            ON events(event_type, id);
CREATE INDEX IF NOT EXISTS idx_anomalies_time            ON anomalies(detected_at);
"""


def get_connection(path=None) -> sqlite3.Connection:
    db_path = str(path) if path is not None else str(DB_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


_TRUNCATE_ORDER = [
    "anomalies", "events", "turnout", "results", "party_votes",
    "candidates", "parties", "afstemningsomraader", "opstillingskredse",
    "storkredse", "kommuner", "regioner", "valglandsdele", "elections",
]


def reset_db(conn: sqlite3.Connection) -> None:
    """Delete all rows from all tables. Schema and indexes are preserved."""
    conn.execute("PRAGMA foreign_keys=OFF")
    for table in _TRUNCATE_ORDER:
        conn.execute(f"DELETE FROM {table}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
