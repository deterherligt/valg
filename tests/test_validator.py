import argparse
import json
import git
from valg.validator import check_authors, check_inventory, check_schema, run_validation, check_anomaly_rate
from valg.models import get_connection, init_db


def test_check_authors_passes_for_allowed_email(tmp_path):
    """All commits from allowed author → no unauthorized commits."""
    repo = git.Repo.init(tmp_path)
    (tmp_path / "file.txt").write_text("data")
    repo.index.add(["file.txt"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))
    result = check_authors(tmp_path, allowed_emails=["mads@example.com"])
    assert result == []


def test_check_authors_flags_unauthorized_email(tmp_path):
    """Commit from unknown author → returned in unauthorized list."""
    repo = git.Repo.init(tmp_path)
    (tmp_path / "file.txt").write_text("data")
    repo.index.add(["file.txt"])
    repo.index.commit("hack", author=git.Actor("Evil", "evil@bad.com"))
    result = check_authors(tmp_path, allowed_emails=["mads@example.com"])
    assert len(result) == 1
    assert result[0]["email"] == "evil@bad.com"


def test_check_inventory_all_matched(tmp_path):
    """All files match a plugin → no unknown files."""
    (tmp_path / "Storkreds-test.json").write_text("{}")
    (tmp_path / "partistemmefordeling-ok1.json").write_text("{}")
    result = check_inventory(tmp_path)
    assert result["unknown_files"] == []


def test_check_inventory_flags_unknown_files(tmp_path):
    """Files that no plugin matches → listed as unknown."""
    (tmp_path / "Storkreds-test.json").write_text("{}")
    (tmp_path / "BrandNewFormat.json").write_text("{}")
    result = check_inventory(tmp_path)
    assert "BrandNewFormat.json" in result["unknown_files"]
    assert "Storkreds-test.json" not in result["unknown_files"]


def test_check_schema_passes_valid_partistemmer(tmp_path):
    """Valid partistemmefordeling file passes schema check."""
    data = {"Valgart": "FV", "Valgdag": "2026-03-24", "Storkreds": "Test", "Partier": []}
    (tmp_path / "partistemmefordeling-ok1.json").write_text(json.dumps(data))
    violations = check_schema(tmp_path)
    assert violations == []


def test_check_schema_flags_missing_key(tmp_path):
    """File missing expected key → violation reported."""
    data = {"WrongKey": {}}
    (tmp_path / "partistemmefordeling-ok1.json").write_text(json.dumps(data))
    violations = check_schema(tmp_path)
    assert len(violations) == 1
    assert "Valgart" in violations[0]["issue"]


def test_run_validation_returns_verdict(tmp_path):
    """run_validation returns structured verdict."""
    repo = git.Repo.init(tmp_path)
    (tmp_path / "Region.json").write_text('[{"Kode": "1", "Navn": "Test"}]')
    repo.index.add(["Region.json"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))

    verdict = run_validation(tmp_path, allowed_emails=["mads@example.com"])
    assert verdict["status"] in ("pass", "repair_needed")
    assert isinstance(verdict["unauthorized_commits"], list)
    assert isinstance(verdict["unknown_files"], list)
    assert isinstance(verdict["schema_violations"], list)


def test_check_anomaly_rate_passes_under_threshold(tmp_path):
    """Anomaly rate below threshold → passes."""
    conn = get_connection(str(tmp_path / "test.db"))
    init_db(conn)
    conn.execute("INSERT INTO anomalies (detected_at, filename, anomaly_type, detail) VALUES (datetime('now'), 'f.json', 'unknown_field', 'x')")
    conn.commit()
    result = check_anomaly_rate(conn, total_files=10, threshold=0.2)
    assert result["passed"] is True


def test_check_anomaly_rate_fails_above_threshold(tmp_path):
    """Anomaly rate above threshold → fails."""
    conn = get_connection(str(tmp_path / "test.db"))
    init_db(conn)
    for i in range(5):
        conn.execute("INSERT INTO anomalies (detected_at, filename, anomaly_type, detail) VALUES (datetime('now'), ?, 'parse_failure', 'x')", (f"f{i}.json",))
    conn.commit()
    result = check_anomaly_rate(conn, total_files=10, threshold=0.2)
    assert result["passed"] is False


def test_cmd_validate_writes_github_output(tmp_path, monkeypatch):
    """In CI, validate writes unknown_files to $GITHUB_OUTPUT."""
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    data_repo = tmp_path / "data"
    data_repo.mkdir()
    repo = git.Repo.init(data_repo)
    (data_repo / "Unknown.json").write_text("{}")
    repo.index.add(["Unknown.json"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))

    from valg.cli import cmd_validate
    args = argparse.Namespace(
        data_repo=str(data_repo),
        allowed_emails="mads@example.com",
        db=str(tmp_path / "test.db"),
    )
    cmd_validate(None, args)
    content = output_file.read_text()
    assert "unknown_files=" in content
