import json
import pytest
from pathlib import Path
from valg.fake_fetcher import make_election, setup_db, write_wave
from valg.models import get_connection, init_db
from valg.plugins import load_plugins, find_plugin


@pytest.fixture
def election():
    return make_election()


@pytest.fixture
def db():
    conn = get_connection(":memory:")
    init_db(conn)
    load_plugins()
    return conn


def test_make_election_has_required_keys(election):
    for key in ("storkredse", "opstillingskredse", "afstemningsomraader", "parties", "candidates"):
        assert key in election


def test_setup_db_populates_geography(election, db):
    setup_db(db, election)
    count = db.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0]
    assert count == len(election["storkredse"])


def test_setup_db_populates_parties(election, db):
    setup_db(db, election)
    count = db.execute("SELECT COUNT(*) FROM parties").fetchone()[0]
    assert count == len(election["parties"])


def test_write_wave0_produces_storkreds_json(election, tmp_path):
    write_wave(tmp_path, election, wave=0)
    files = list(tmp_path.glob("Storkreds-*.json"))
    assert len(files) == 1


def test_write_wave0_storkreds_parseable_by_plugin(election, tmp_path):
    write_wave(tmp_path, election, wave=0)
    load_plugins()
    storkreds_file = list(tmp_path.glob("Storkreds-*.json"))[0]
    data = json.loads(storkreds_file.read_text())
    plugin = find_plugin(storkreds_file.name)
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert len(rows) == len(election["storkredse"])


def test_write_wave1_produces_partistemmer_files(election, tmp_path):
    write_wave(tmp_path, election, wave=1)
    files = list(tmp_path.glob("partistemmefordeling-*.json"))
    assert len(files) > 0


def test_write_wave1_partistemmer_parseable_by_plugin(election, tmp_path):
    write_wave(tmp_path, election, wave=1)
    load_plugins()
    plugin = find_plugin("partistemmefordeling-OK1.json")
    for f in tmp_path.glob("partistemmefordeling-*.json"):
        data = json.loads(f.read_text())
        rows = plugin.parse(data, "2024-11-05T21:00:00")
        assert len(rows) > 0


def test_write_wave1_valgresultater_parseable_by_plugin(election, tmp_path):
    write_wave(tmp_path, election, wave=1)
    load_plugins()
    plugin = find_plugin("valgresultater-Folketingsvalg-AO1.json")
    for f in tmp_path.glob("valgresultater-Folketingsvalg-*.json"):
        data = json.loads(f.read_text())
        rows = plugin.parse(data, "2024-11-05T21:00:00")
        assert all(r["count_type"] == "preliminary" for r in rows)


def test_write_wave4_produces_final_results(election, tmp_path):
    write_wave(tmp_path, election, wave=4)
    load_plugins()
    plugin = find_plugin("valgresultater-Folketingsvalg-AO1.json")
    for f in tmp_path.glob("valgresultater-Folketingsvalg-*.json"):
        data = json.loads(f.read_text())
        rows = plugin.parse(data, "2024-11-06T10:00:00")
        assert all(r["count_type"] == "final" for r in rows)
        candidate_rows = [r for r in rows if r["candidate_id"] is not None]
        assert len(candidate_rows) > 0


def test_wave3_covers_all_districts(election, tmp_path):
    write_wave(tmp_path, election, wave=3)
    n_ao = len(election["afstemningsomraader"])
    files = list(tmp_path.glob("valgresultater-Folketingsvalg-*.json"))
    assert len(files) == n_ao
