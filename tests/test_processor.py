# tests/test_processor.py
import json
import pytest
from pathlib import Path
from valg.models import get_connection, init_db
from valg.processor import process_raw_file, process_directory
from valg.plugins import load_plugins

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture(autouse=True)
def plugins():
    load_plugins()

@pytest.fixture
def db():
    conn = get_connection(":memory:")
    init_db(conn)
    return conn

def test_process_storkreds_file_inserts_storkredse_rows(db, tmp_path):
    f = tmp_path / "Storkreds-test.json"
    f.write_text((FIXTURES / "geografi_region.json").read_text())
    process_raw_file(db, f)
    count = db.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0]
    assert count == 2

def test_process_valgresultater_inserts_results(db, tmp_path):
    f = tmp_path / "valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json"
    f.write_text((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    process_raw_file(db, f)
    count = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    assert count > 0

def test_process_unknown_file_does_not_crash(db, tmp_path):
    f = tmp_path / "ukjent-format.json"
    f.write_text('{"noget": "andet"}')
    process_raw_file(db, f)  # must not raise

def test_process_malformed_json_does_not_crash(db, tmp_path):
    f = tmp_path / "Region.json"
    f.write_text("NOT VALID JSON {{{")
    process_raw_file(db, f)  # must not raise

def test_process_file_records_snapshot_at(db, tmp_path):
    f = tmp_path / "valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json"
    f.write_text((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    process_raw_file(db, f, snapshot_at="2024-11-05T21:00:00")
    row = db.execute("SELECT snapshot_at FROM results LIMIT 1").fetchone()
    assert row["snapshot_at"] == "2024-11-05T21:00:00"

def test_process_directory_of_files(db, tmp_path):
    (tmp_path / "Storkreds-test.json").write_text(
        (FIXTURES / "geografi_region.json").read_text())
    (tmp_path / "valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json").write_text(
        (FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    process_directory(db, tmp_path)
    assert db.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] > 0

def test_process_unknown_file_logs_anomaly(db, tmp_path):
    f = tmp_path / "ukjent-format.json"
    f.write_text('{"noget": "andet"}')
    process_raw_file(db, f)
    count = db.execute("SELECT COUNT(*) FROM anomalies WHERE anomaly_type = 'unknown_file'").fetchone()[0]
    assert count == 1

def test_process_malformed_json_logs_anomaly(db, tmp_path):
    f = tmp_path / "Region.json"
    f.write_text("NOT VALID JSON")
    process_raw_file(db, f)
    count = db.execute("SELECT COUNT(*) FROM anomalies WHERE anomaly_type = 'parse_failure'").fetchone()[0]
    assert count == 1

def test_process_empty_file_skips_silently(db, tmp_path):
    f = tmp_path / "valgdeltagelse-Folketingsvalg-Skive-240320261710.json"
    f.write_text("")
    result = process_raw_file(db, f)
    assert result == 0
    count = db.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0]
    assert count == 0  # empty files are transient SFTP artifacts, not anomalies

def test_process_whitespace_only_file_skips_silently(db, tmp_path):
    f = tmp_path / "valgdeltagelse-Folketingsvalg-Skive-240320261710.json"
    f.write_text("  \n  ")
    result = process_raw_file(db, f)
    assert result == 0
    count = db.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0]
    assert count == 0

def test_process_directory_processes_all_json_files(db, tmp_path):
    (tmp_path / "Storkreds-test.json").write_text((FIXTURES / "geografi_region.json").read_text())
    (tmp_path / "partistemmefordeling-Kobenhavn-2024.json").write_text(
        (FIXTURES / "partistemmer_fv.json").read_text())
    # also insert a prerequisite opstillingskreds for party_votes FK
    db.execute("INSERT INTO elections (id, name) VALUES ('FV2024', 'Test')")
    db.execute("INSERT INTO storkredse (id, name, election_id) VALUES ('SK1', 'SK1', 'FV2024')")
    db.execute("INSERT INTO opstillingskredse (id, name, storkreds_id) VALUES ('OK1', 'OK1', 'SK1')")
    db.commit()
    process_directory(db, tmp_path)
    assert db.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0] >= 2  # from Storkreds-test.json

def test_process_idempotent_upsert_does_not_duplicate(db, tmp_path):
    f = tmp_path / "Storkreds-test.json"
    f.write_text((FIXTURES / "geografi_region.json").read_text())
    process_raw_file(db, f)
    process_raw_file(db, f)  # process same file twice
    count = db.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0]
    assert count == 2  # not 4


def test_process_results_file_emits_district_event(db, tmp_path):
    from valg.fake_fetcher import make_election, write_wave
    election = make_election()
    write_wave(tmp_path, election, wave=1)
    process_directory(db, tmp_path, snapshot_at="2024-11-05T21:00:00")
    count = db.execute("SELECT COUNT(*) FROM events WHERE event_type='district_reported'").fetchone()[0]
    assert count > 0


def test_preliminary_event_description(db, tmp_path):
    from valg.fake_fetcher import make_election, write_wave
    election = make_election()
    write_wave(tmp_path, election, wave=1)
    process_directory(db, tmp_path, snapshot_at="2024-11-05T21:00:00")
    row = db.execute("SELECT description FROM events WHERE event_type='district_reported' LIMIT 1").fetchone()
    assert "preliminary" in row["description"]


def test_final_event_description(db, tmp_path):
    from valg.fake_fetcher import make_election, write_wave
    election = make_election()
    write_wave(tmp_path, election, wave=4)
    process_directory(db, tmp_path, snapshot_at="2024-11-06T10:00:00")
    row = db.execute("SELECT description FROM events WHERE event_type='district_reported' LIMIT 1").fetchone()
    assert "final" in row["description"]


def test_turnout_file_emits_preliminary_event(db, tmp_path):
    # valgdeltagelse (turnout) files should emit district_reported events
    # even when there are no valgresultater — this covers preliminary-only waves
    f = tmp_path / "valgdeltagelse-AO1.json"
    f.write_text((FIXTURES / "valgdeltagelse_fv.json").read_text())
    db.execute("INSERT OR REPLACE INTO afstemningsomraader (id, name) VALUES ('AO1', 'Test AO')")
    db.commit()
    process_raw_file(db, f, snapshot_at="2024-11-05T20:00:00")
    row = db.execute("SELECT description FROM events WHERE event_type='district_reported'").fetchone()
    assert row is not None
    assert "preliminary" in row["description"]
