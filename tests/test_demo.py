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
