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
