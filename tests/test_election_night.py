import git
import json
from pathlib import Path
from valg.validator import run_validation, check_anomaly_rate
from valg.models import get_connection, init_db
from valg.processor import process_directory
from valg.plugins import load_plugins


def test_election_night_pipeline_happy_path(tmp_path):
    """Full pipeline: fetch → validate → process → check-anomalies."""
    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    repo = git.Repo.init(data_repo)

    # Simulate fetched files — use valid data matching plugin expectations
    # Storkreds file is a list (geografi plugin expects list)
    (data_repo / "Storkreds-test.json").write_text(json.dumps([
        {"Nummer": 1, "Navn": "Hovedstaden"}
    ]))
    # partistemmefordeling expects flat dict with OpstillingskredsDagiId + IndenforParti
    (data_repo / "partistemmefordeling-ok1.json").write_text(json.dumps({
        "Valgart": "FV", "Valgdag": "2026-03-24", "Storkreds": "Test",
        "OpstillingskredsDagiId": "ok1", "IndenforParti": [
            {"Bogstavbetegnelse": "A", "Stemmer": 1234}
        ]
    }))
    repo.index.add(["Storkreds-test.json", "partistemmefordeling-ok1.json"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))

    # Validate
    verdict = run_validation(data_repo, allowed_emails=["mads@example.com"])
    assert verdict["status"] == "pass"
    assert verdict["unauthorized_commits"] == []
    assert verdict["unknown_files"] == []

    # Process
    conn = get_connection(str(tmp_path / "test.db"))
    init_db(conn)
    load_plugins()
    rows = process_directory(conn, data_repo)
    assert rows > 0

    # Check anomalies
    result = check_anomaly_rate(conn, total_files=2, threshold=0.2)
    assert result["passed"] is True


def test_election_night_pipeline_detects_unauthorized_commit(tmp_path):
    """Pipeline detects commit from unauthorized author."""
    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    repo = git.Repo.init(data_repo)

    (data_repo / "Region.json").write_text('[{"Kode": "1", "Navn": "Test"}]')
    repo.index.add(["Region.json"])
    repo.index.commit("legit", author=git.Actor("Mads", "mads@example.com"))

    (data_repo / "hacked.json").write_text('{"votes": 999999}')
    repo.index.add(["hacked.json"])
    repo.index.commit("tamper", author=git.Actor("Evil", "evil@bad.com"))

    verdict = run_validation(data_repo, allowed_emails=["mads@example.com"])
    assert len(verdict["unauthorized_commits"]) == 1
    assert verdict["unauthorized_commits"][0]["email"] == "evil@bad.com"


def test_election_night_pipeline_flags_unknown_format(tmp_path):
    """Pipeline flags unknown file format for repair agent."""
    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    repo = git.Repo.init(data_repo)

    (data_repo / "BrandNewFormat.json").write_text('{"new": "data"}')
    repo.index.add(["BrandNewFormat.json"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))

    verdict = run_validation(data_repo, allowed_emails=["mads@example.com"])
    assert verdict["status"] == "repair_needed"
    assert "BrandNewFormat.json" in verdict["unknown_files"]
