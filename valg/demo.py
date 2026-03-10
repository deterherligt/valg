from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Step:
    name: str
    wave: int | None
    setup: bool = False
    process: bool = True
    commit: bool = True
    base_interval_s: float = 60.0


@dataclass
class Scenario:
    name: str
    description: str
    steps: list[Step]


SCENARIOS: dict[str, Scenario] = {
    "Election Night": Scenario(
        name="Election Night",
        description=(
            "Simulates a full Folketing election night: "
            "setup → 25/50/100% foreløbig → 50/100% fintælling."
        ),
        steps=[
            Step(name="Setup — geography & candidates", wave=0, setup=True, process=False, commit=True, base_interval_s=0),
            Step(name="25% foreløbig",   wave=1, base_interval_s=60.0),
            Step(name="50% foreløbig",   wave=2, base_interval_s=60.0),
            Step(name="100% foreløbig",  wave=3, base_interval_s=60.0),
            Step(name="50% fintælling",  wave=4, base_interval_s=60.0),
            Step(name="100% fintælling", wave=5, base_interval_s=60.0),
        ],
    ),
}


def get_scenario(name: str) -> Scenario:
    return SCENARIOS[name]


import logging
import threading

log = logging.getLogger(__name__)


class DemoRunner:
    def __init__(self) -> None:
        self.state: str = "idle"   # idle | running | paused | done
        self.speed: float = 1.0
        self.step_index: int = -1  # -1 = not started
        self.paused: bool = False
        self.scenario_name: str = "Election Night"
        self._lock = threading.Lock()

    def set_speed(self, multiplier: float) -> None:
        with self._lock:
            self.speed = multiplier

    def set_scenario(self, name: str) -> None:
        with self._lock:
            if self.state == "running":
                raise RuntimeError("Cannot change scenario while running")
            get_scenario(name)  # raises KeyError if unknown
            self.scenario_name = name

    def get_state_dict(self) -> dict:
        with self._lock:
            scenario = get_scenario(self.scenario_name)
            step_name = ""
            if 0 <= self.step_index < len(scenario.steps):
                step_name = scenario.steps[self.step_index].name
            return {
                "enabled": True,
                "state": self.state,
                "scenario": self.scenario_name,
                "step_index": self.step_index,
                "step_name": step_name,
                "steps_total": len(scenario.steps),
                "speed": self.speed,
                "scenarios": list(SCENARIOS.keys()),
            }
