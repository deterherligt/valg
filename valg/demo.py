from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class Step:
    name: str
    wave: int | None
    setup: bool = False
    process: bool = True
    commit: bool = True
    base_interval_s: float = 60.0
    write_fn: Callable[[Path], list[Path]] | None = None


@dataclass
class Scenario:
    name: str
    description: str
    steps: list[Step]
    steps_factory: Callable[[Path], list[Step]] | None = None
    output_dir: Path | None = None   # relative path under data_repo to clean on restart


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

# Register KV2025 scenario if wave data is available
try:
    from valg.scenarios.kv2025 import KV2025_SCENARIO
    SCENARIOS["kv2025"] = KV2025_SCENARIO
except Exception:
    pass  # wave data not generated yet — scenario unavailable


def get_scenario(name: str) -> Scenario:
    return SCENARIOS[name]


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

    def start(self, db_path: Path, data_repo: Path) -> None:
        with self._lock:
            if self.state == "running":
                return
            self.state = "running"
            self.step_index = -1
            self._db_path = Path(db_path)
            self._data_repo = Path(data_repo)
            scenario = get_scenario(self.scenario_name)
            self._output_dir = scenario.output_dir  # may be None
            # Resolve steps — use factory if provided
            if scenario.steps_factory is not None:
                self._resolved_steps = scenario.steps_factory(self._data_repo)
            else:
                self._resolved_steps = scenario.steps
            self._stop_event = threading.Event()
            self._pause_event = threading.Event()
            self._pause_event.set()  # not paused initially
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        self._thread = t

    def pause(self) -> None:
        with self._lock:
            if self.state != "running":
                return
            self.state = "paused"
            self.paused = True
            self._pause_event.clear()

    def resume(self) -> None:
        with self._lock:
            if self.state != "paused":
                return
            self.state = "running"
            self.paused = False
            self._pause_event.set()

    def restart(self, db_path: Path, data_repo: Path) -> None:
        # Stop the running loop
        if hasattr(self, "_stop_event"):
            self._stop_event.set()
        if hasattr(self, "_pause_event"):
            self._pause_event.set()  # unblock if paused
        if hasattr(self, "_thread") and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        # Reset DB
        from valg.models import get_connection, reset_db
        conn = get_connection(Path(db_path))
        reset_db(conn)
        conn.execute("PRAGMA wal_checkpoint(RESTART)")
        conn.close()

        # Delete demo folder(s) and commit the deletion
        import shutil
        to_clean = [Path(data_repo) / "FV2024-demo"]
        if getattr(self, "_output_dir", None) is not None:
            to_clean.append(Path(data_repo) / self._output_dir)
        cleaned = False
        for d in to_clean:
            if d.exists():
                shutil.rmtree(d)
                cleaned = True
        if cleaned:
            from valg.fetcher import commit_data_repo
            commit_data_repo(Path(data_repo), message="demo: reset")

        with self._lock:
            self.state = "idle"
            self.step_index = -1
            self.paused = False

        self.start(db_path=db_path, data_repo=data_repo)

    def _run(self) -> None:
        from valg.fake_fetcher import make_election, setup_db, write_wave
        from valg.processor import process_raw_file
        from valg.plugins import load_plugins
        from valg.fetcher import commit_data_repo
        from valg.models import get_connection, init_db
        from datetime import datetime, timezone

        load_plugins()
        election = make_election()
        demo_dir = self._data_repo / "FV2024-demo"
        demo_dir.mkdir(parents=True, exist_ok=True)

        for i, step in enumerate(self._resolved_steps):
            if self._stop_event.is_set():
                break
            with self._lock:
                self.step_index = i
            log.info("Demo step %d: %s", i, step.name)

            written = []
            if step.write_fn is not None:
                written = step.write_fn(self._data_repo)
            elif step.wave is not None:
                written = write_wave(demo_dir, election, step.wave)

            if step.setup and step.write_fn is None:
                conn = get_connection(self._db_path)
                init_db(conn)
                setup_db(conn, election)

            if step.process and written:
                conn = get_connection(self._db_path)
                snapshot_at = datetime.now(timezone.utc).isoformat()
                for p in written:
                    process_raw_file(conn, p, snapshot_at=snapshot_at)

            if step.commit:
                commit_data_repo(self._data_repo, message=f"demo: {step.name}")

            with self._lock:
                interval = step.base_interval_s / self.speed
            elapsed = 0.0
            tick = 0.1
            while elapsed < interval:
                if self._stop_event.is_set():
                    break
                self._pause_event.wait()  # blocks when paused
                time.sleep(tick)
                elapsed += tick

        with self._lock:
            if not self._stop_event.is_set():
                self.state = "done"
                self.step_index = len(self._resolved_steps) - 1

    def get_state_dict(self) -> dict:
        with self._lock:
            scenario = get_scenario(self.scenario_name)
            resolved = getattr(self, "_resolved_steps", None)
            steps = resolved if resolved is not None else scenario.steps
            step_name = ""
            if 0 <= self.step_index < len(steps):
                step_name = steps[self.step_index].name
            return {
                "enabled": True,
                "state": self.state,
                "scenario": self.scenario_name,
                "step_index": self.step_index,
                "step_name": step_name,
                "steps_total": len(steps),
                "speed": self.speed,
                "scenarios": list(SCENARIOS.keys()),
            }
