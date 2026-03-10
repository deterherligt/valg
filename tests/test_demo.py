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
