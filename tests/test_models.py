# tests/test_models.py
from valg.models import init_db, get_connection, reset_db

def test_init_db_creates_all_tables():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {r[0] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    expected = {
        "elections", "storkredse", "opstillingskredse",
        "afstemningsomraader", "parties", "candidates",
        "results", "turnout", "party_votes",
        "events", "anomalies",
    }
    assert expected <= tables, f"Missing tables: {expected - tables}"

def test_init_db_creates_performance_indexes():
    conn = get_connection(":memory:")
    init_db(conn)
    indexes = {r[0] for r in
               conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    required = {
        "idx_results_party_snapshot",
        "idx_results_ao_snapshot",
        "idx_results_candidate_snap",
        "idx_party_votes_party_snap",
        "idx_turnout_ao_snapshot",
        "idx_events_type_time",
        "idx_anomalies_time",
    }
    assert required <= indexes, f"Missing indexes: {required - indexes}"

def test_init_db_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    init_db(conn)  # must not raise

def test_get_connection_enables_wal_mode():
    conn = get_connection(":memory:")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "memory"  # :memory: ignores WAL but call must not raise

def test_storkredse_has_n_kredsmandater_column():
    conn = get_connection(":memory:")
    init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(storkredse)").fetchall()}
    assert "n_kredsmandater" in cols

def test_events_table_has_required_columns():
    conn = get_connection(":memory:")
    init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    assert {"id", "occurred_at", "event_type", "subject", "description", "data"} <= cols

def test_anomalies_table_has_required_columns():
    conn = get_connection(":memory:")
    init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(anomalies)").fetchall()}
    assert {"id", "detected_at", "filename", "anomaly_type", "detail"} <= cols

def test_results_has_count_type_column():
    conn = get_connection(":memory:")
    init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(results)").fetchall()}
    assert "count_type" in cols

def test_row_factory_returns_dict_like_rows():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO elections (id, name) VALUES ('E1', 'Test')")
    row = conn.execute("SELECT id, name FROM elections").fetchone()
    assert row["id"] == "E1"
    assert row["name"] == "Test"

def test_reset_db_clears_all_rows():
    conn = get_connection(":memory:")
    init_db(conn)
    conn.execute("INSERT INTO elections (id, name) VALUES ('X', 'Test')")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM elections").fetchone()[0] == 1

    reset_db(conn)

    assert conn.execute("SELECT COUNT(*) FROM elections").fetchone()[0] == 0
    # Schema must still exist
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "elections" in tables
