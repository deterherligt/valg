# tests/test_demo.py
from valg.demo import Step, Scenario, SCENARIOS, get_scenario


def test_step_defaults():
    s = Step(name="test", wave=1)
    assert s.process is True
    assert s.commit is True
    assert s.setup is False
    assert s.base_interval_s == 60.0


def test_election_night_scenario():
    s = get_scenario("Election Night")
    assert s.name == "Election Night"
    assert len(s.steps) == 6
    assert s.steps[0].setup is True
    assert s.steps[0].wave == 0
    assert s.steps[0].process is False
    assert s.steps[3].wave == 3


def test_get_scenario_unknown():
    import pytest
    with pytest.raises(KeyError):
        get_scenario("Does Not Exist")


def test_scenarios_dict_keys():
    assert "Election Night" in SCENARIOS


from valg.demo import DemoRunner


def test_runner_initial_state():
    r = DemoRunner()
    assert r.state == "idle"
    assert r.speed == 1.0
    assert r.step_index == -1
    assert r.paused is False
    assert r.scenario_name == "Election Night"


def test_runner_set_speed():
    r = DemoRunner()
    r.set_speed(5.0)
    assert r.speed == 5.0


def test_runner_set_scenario():
    r = DemoRunner()
    r.set_scenario("Election Night")
    assert r.scenario_name == "Election Night"


def test_runner_set_scenario_unknown():
    import pytest
    r = DemoRunner()
    with pytest.raises(KeyError):
        r.set_scenario("Nope")


def test_runner_set_scenario_rejects_when_running():
    r = DemoRunner()
    r.state = "running"
    import pytest
    with pytest.raises(RuntimeError):
        r.set_scenario("Election Night")


def test_runner_get_state_dict():
    r = DemoRunner()
    d = r.get_state_dict()
    assert d["enabled"] is True
    assert d["state"] == "idle"
    assert d["step_index"] == -1
    assert d["speed"] == 1.0
    assert "Election Night" in d["scenarios"]


import subprocess
import time
from pathlib import Path


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, capture_output=True)
    (path / "README.md").write_text("demo")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True)


def test_runner_runs_election_night(tmp_path):
    """Full Election Night scenario at 100× speed (~0.6s per wave)."""
    from valg.models import get_connection, init_db

    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    _init_git_repo(data_repo)

    db_path = tmp_path / "valg.db"
    conn = get_connection(db_path)
    init_db(conn)

    runner = DemoRunner()
    runner.set_speed(100.0)  # 60s / 100 = 0.6s per wave
    runner.start(db_path=db_path, data_repo=data_repo)

    deadline = time.time() + 20
    while runner.state != "done" and time.time() < deadline:
        time.sleep(0.2)

    assert runner.state == "done", f"Runner timed out in state: {runner.state}"
    assert runner.step_index == 5

    conn2 = get_connection(db_path)
    party_votes = conn2.execute("SELECT COUNT(*) FROM party_votes").fetchone()[0]
    assert party_votes > 0, "No party_votes — preliminary phase didn't process"

    final_results = conn2.execute(
        "SELECT COUNT(*) FROM results WHERE count_type='final'"
    ).fetchone()[0]
    assert final_results > 0, "No final results — fintælling phase didn't process"


def test_runner_restart_clears_data(tmp_path):
    """Restart resets DB and demo folder, then re-runs from step 0."""
    from valg.models import get_connection, init_db

    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    _init_git_repo(data_repo)

    db_path = tmp_path / "valg.db"
    conn = get_connection(db_path)
    init_db(conn)

    runner = DemoRunner()
    runner.set_speed(100.0)
    runner.start(db_path=db_path, data_repo=data_repo)

    # Let it process at least one data wave
    deadline = time.time() + 8
    while runner.step_index < 2 and time.time() < deadline:
        time.sleep(0.2)

    runner.restart(db_path=db_path, data_repo=data_repo)

    # reset_db is synchronous inside restart(), so DB is empty right after it returns
    conn2 = get_connection(db_path)
    count = conn2.execute("SELECT COUNT(*) FROM party_votes").fetchone()[0]
    assert count == 0, f"Expected empty party_votes after restart, got {count}"

    # After restart the runner should be running again
    deadline2 = time.time() + 5
    while runner.step_index < 0 and time.time() < deadline2:
        time.sleep(0.1)

    assert runner.state in ("running", "done")
