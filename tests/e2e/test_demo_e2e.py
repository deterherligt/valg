"""E2E: full Election Night scenario at 100× speed.

Verifies that the complete pipeline (fake files → git commit → SQLite) works
end-to-end and that the DB contains party vote data and final candidate results
after all waves complete.
"""
import subprocess
import time
from pathlib import Path

import pytest

from valg.demo import DemoRunner
from valg.models import get_connection, init_db


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "ci@test"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "CI"], cwd=path, capture_output=True)
    (path / "README.md").write_text("demo data repo")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True)


def test_election_night_e2e(tmp_path):
    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    _init_git_repo(data_repo)

    db_path = tmp_path / "valg.db"
    conn = get_connection(db_path)
    init_db(conn)

    runner = DemoRunner()
    runner.set_speed(100.0)
    runner.start(db_path=db_path, data_repo=data_repo)

    deadline = time.time() + 25
    while runner.state != "done" and time.time() < deadline:
        time.sleep(0.3)

    assert runner.state == "done", f"Did not finish in time (state={runner.state})"
    assert runner.step_index == 5

    conn2 = get_connection(db_path)
    party_votes = conn2.execute("SELECT COUNT(*) FROM party_votes").fetchone()[0]
    assert party_votes > 0, "No party_votes — preliminary phase didn't process"

    final_results = conn2.execute(
        "SELECT COUNT(*) FROM results WHERE count_type='final'"
    ).fetchone()[0]
    assert final_results > 0, "No final results — fintælling phase didn't process"

    git_log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=data_repo, capture_output=True, text=True,
    ).stdout
    assert "demo:" in git_log, "No demo commits found in data repo git log"
