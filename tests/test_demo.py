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


def test_step_write_fn_default_none():
    s = Step(name="test", wave=1)
    assert s.write_fn is None


def test_step_write_fn_callable():
    called_with = []
    def my_writer(repo):
        called_with.append(repo)
        return []
    s = Step(name="test", wave=None, write_fn=my_writer)
    assert s.write_fn is not None
    result = s.write_fn(Path("/tmp"))
    assert called_with == [Path("/tmp")]
    assert result == []


def test_runner_uses_write_fn(tmp_path):
    """When step.write_fn is set, DemoRunner calls it instead of write_wave."""
    db = tmp_path / "valg.db"
    data_repo = tmp_path / "data"
    data_repo.mkdir()
    _init_git_repo(data_repo)

    written_paths = []
    marker = tmp_path / "write_fn_called"

    def my_writer(repo):
        marker.touch()
        written_paths.append(repo)
        return []

    from valg.demo import DemoRunner, Scenario, SCENARIOS, Step

    test_scenario = Scenario(
        name="Test",
        description="test",
        steps=[
            Step(name="custom step", wave=None, setup=False,
                 process=False, commit=True, base_interval_s=0.0,
                 write_fn=my_writer),
        ],
    )
    original = dict(SCENARIOS)
    SCENARIOS["Test"] = test_scenario
    try:
        r = DemoRunner()
        r.set_scenario("Test")
        r.set_speed(1000.0)
        r.start(db_path=db, data_repo=data_repo)
        r._thread.join(timeout=10.0)
        assert marker.exists(), "write_fn was not called"
    finally:
        SCENARIOS.clear()
        SCENARIOS.update(original)


def test_scenario_steps_factory_default_none():
    s = Scenario(name="x", description="y", steps=[])
    assert s.steps_factory is None


def test_scenario_steps_factory_called_at_start(tmp_path):
    db = tmp_path / "valg.db"
    data_repo = tmp_path / "data"
    data_repo.mkdir()
    _init_git_repo(data_repo)

    factory_args = []

    def my_factory(repo):
        factory_args.append(repo)
        return [Step(name="factory step", wave=None, process=False, commit=False, base_interval_s=0.0)]

    from valg.demo import DemoRunner, Scenario, SCENARIOS, Step
    test_scenario = Scenario(
        name="FactoryTest",
        description="test",
        steps=[],
        steps_factory=my_factory,
    )
    original = dict(SCENARIOS)
    SCENARIOS["FactoryTest"] = test_scenario
    try:
        r = DemoRunner()
        r.set_scenario("FactoryTest")
        r.set_speed(1000.0)
        r.start(db_path=db, data_repo=data_repo)
        r._thread.join(timeout=10.0)
        assert factory_args == [data_repo], f"factory not called with data_repo, got {factory_args}"
    finally:
        SCENARIOS.clear()
        SCENARIOS.update(original)


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


def test_kandidat_data_files_are_processed(tmp_path):
    """kandidat-data files written by a step's write_fn must be processed into candidates table."""
    import json
    from pathlib import Path
    from valg.demo import DemoRunner, Scenario, Step
    from valg.models import get_connection, init_db

    db_path = tmp_path / "test.db"
    data_repo = tmp_path / "data"
    data_repo.mkdir()

    kandidat_file = tmp_path / "kandidat-data-Folketingsvalg-test.json"
    kandidat_file.write_text(json.dumps({
        "Storkreds": "Test",
        "Storkredsnummer": "1",
        "IndenforParti": [
            {"PartiId": "some-uuid", "Partibogstav": "A", "Partinavn": "Socialdemokratiet", "PersonligeStemmer": True, "Kandidater": [
                {"Id": "cand-uuid-1", "Navn": "Test Kandidat", "Opstillingskredse": [
                    {"Opstillingskreds": "Test", "OpstillingskredsDagiId": "OK1", "OpstilletIKreds": True, "KandidatsPlacering": 1}
                ]}
            ]}
        ]
    }))

    def write_fn(data_repo):
        dest = data_repo / "kandidat-data-Folketingsvalg-test.json"
        import shutil
        shutil.copy2(kandidat_file, dest)
        return [dest]

    scenario = Scenario(
        name="test", description="test",
        steps=[Step(name="setup", wave=None, setup=True, process=True, commit=False,
                    base_interval_s=0, write_fn=write_fn)],
    )

    conn = get_connection(db_path)
    init_db(conn)
    conn.close()

    # Temporarily register test scenario
    from valg import demo as demo_module
    demo_module.SCENARIOS["test"] = scenario

    runner = DemoRunner()
    runner.set_scenario("test")

    runner.start(db_path=db_path, data_repo=data_repo)

    # Poll until runner is done or timeout
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if runner.step_index >= len(scenario.steps):
            break
        time.sleep(0.05)

    runner._stop_event.set()
    runner._thread.join(timeout=2.0)

    conn = get_connection(db_path)
    count = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    conn.close()

    demo_module.SCENARIOS.pop("test", None)
    assert count == 1, f"Expected 1 candidate in DB, got {count}"


def test_restart_cleans_scenario_output_dir(tmp_path):
    """restart() removes the scenario's output directory before re-running."""
    from valg.demo import DemoRunner, Scenario, Step
    from valg.models import get_connection, init_db
    import valg.demo as demo_module
    from pathlib import Path

    db_path = tmp_path / "test.db"
    data_repo = tmp_path / "data"
    data_repo.mkdir()

    # Pre-populate a scenario output dir
    stale_dir = data_repo / "demo" / "fv2022"
    stale_dir.mkdir(parents=True)
    (stale_dir / "stale.json").write_text("{}")

    def write_fn(dr):
        out = dr / "demo" / "fv2022"
        out.mkdir(parents=True, exist_ok=True)
        return []

    scenario = Scenario(
        name="fv2022_test", description="test",
        steps=[Step(name="step", wave=None, setup=False, process=False, commit=False,
                    base_interval_s=0, write_fn=write_fn)],
        output_dir=Path("demo") / "fv2022",
    )
    demo_module.SCENARIOS["fv2022_test"] = scenario

    conn = get_connection(db_path)
    init_db(conn)
    conn.close()

    runner = DemoRunner()
    runner.set_scenario("fv2022_test")
    runner.start(db_path=db_path, data_repo=data_repo)

    # Wait for first run to complete
    import time
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if runner.step_index >= len(scenario.steps):
            break
        time.sleep(0.05)

    # Re-create the stale dir to simulate leftover data before restart
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "stale.json").write_text("{}")

    runner.restart(db_path=db_path, data_repo=data_repo)

    # Wait for restart to clean and complete
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if runner.step_index >= len(scenario.steps):
            break
        time.sleep(0.05)

    runner._stop_event.set()
    runner._thread.join(timeout=2.0)

    # Stale file should have been removed during restart
    assert not (stale_dir / "stale.json").exists(), "stale.json should be cleaned by restart()"

    demo_module.SCENARIOS.pop("fv2022_test", None)
