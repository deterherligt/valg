# KV2025 Demo Scenario Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a realistic demo scenario that replays kommunalvalg 2025 results as a size-sorted, two-phase election night in the demo mode browser UI.

**Architecture:** Extend `demo.py`'s `Step`/`Scenario`/`DemoRunner` to support custom write functions and factory-built steps. A one-time preparation script downloads KV2025 data from SFTP, transforms it to FV-format JSON, and writes pre-sorted wave bundles to `valg/scenarios/kv2025/`. A `KV2025Scenario` reads these bundles and copies them to `valg-data/demo/kv2025/` one wave at a time — each commit to `valg-data` looks like a real election night sync.

**Tech Stack:** Python 3.13, paramiko (SFTP), existing valg plugin/processor pipeline, pytest

**Branch:** Build on top of `feature/demo-mode`. Create a new branch `feature/kv2025-scenario` off it.

**Spec:** `docs/superpowers/specs/2026-03-15-kv2025-demo-scenario-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `valg/demo.py` | Modify | Add `write_fn` to `Step`, `steps_factory` to `Scenario`, update `_run` |
| `valg/scenarios/__init__.py` | Create | Package marker |
| `valg/scenarios/kv2025_transform.py` | Create | Pure KV→FV transformation functions |
| `valg/scenarios/prepare_kv2025.py` | Create | SFTP download + wave generation script |
| `valg/scenarios/kv2025.py` | Create | Scenario definition, reads pre-baked waves |
| `valg/scenarios/kv2025/wave_NN/` | Generated | Pre-baked FV-format wave bundles (via prepare script) |
| `tests/test_kv2025_transform.py` | Create | Unit tests for transformation functions |
| `tests/test_kv2025_scenario.py` | Create | Unit tests for scenario step generation |
| `tests/test_demo.py` | Modify | Add tests for `write_fn` and `steps_factory` |

---

## Chunk 1: Extend demo.py

### Task 1: Add `write_fn` to `Step` and update `_run`

**Files:**
- Modify: `valg/demo.py`
- Modify: `tests/test_demo.py`

- [ ] **Step 1: Write failing tests for `write_fn` field**

Add to `tests/test_demo.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_demo.py::test_step_write_fn_default_none tests/test_demo.py::test_step_write_fn_callable -v
```

Expected: `AttributeError: Step has no attribute 'write_fn'`

- [ ] **Step 3: Add `write_fn` to `Step` in `valg/demo.py`**

```python
from typing import Callable

@dataclass
class Step:
    name: str
    wave: int | None
    setup: bool = False
    process: bool = True
    commit: bool = True
    base_interval_s: float = 60.0
    write_fn: Callable[["Path"], list["Path"]] | None = None  # NEW
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_demo.py::test_step_write_fn_default_none tests/test_demo.py::test_step_write_fn_callable -v
```

- [ ] **Step 5: Write failing tests for `_run` using `write_fn`**

Add to `tests/test_demo.py`:

```python
import tempfile, json
from valg.models import get_connection, init_db


def test_runner_uses_write_fn(tmp_path):
    """When step.write_fn is set, DemoRunner calls it instead of write_wave."""
    db = tmp_path / "valg.db"
    data_repo = tmp_path / "data"
    data_repo.mkdir()
    # Init git repo so commit_data_repo works
    import subprocess
    subprocess.run(["git", "init"], cwd=data_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=data_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=data_repo, check=True, capture_output=True)

    written_paths = []
    marker = tmp_path / "write_fn_called"

    def my_writer(repo):
        marker.touch()
        written_paths.append(repo)
        return []

    from valg.demo import DemoRunner, Scenario, SCENARIOS, Step
    import copy

    # Patch SCENARIOS with a custom one-step scenario
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
        import time; time.sleep(0.5)
        assert marker.exists(), "write_fn was not called"
    finally:
        SCENARIOS.clear()
        SCENARIOS.update(original)
```

- [ ] **Step 6: Run test — expect FAIL**

```bash
pytest tests/test_demo.py::test_runner_uses_write_fn -v
```

Expected: `AssertionError: write_fn was not called` (runner calls `write_wave` not `write_fn`)

- [ ] **Step 7: Update `DemoRunner._run` to call `write_fn` when set**

In `valg/demo.py`, find the `_run` method. Replace the block:

```python
written = []
if step.wave is not None:
    written = write_wave(demo_dir, election, step.wave)
```

With:

```python
written = []
if step.write_fn is not None:
    written = step.write_fn(self._data_repo)
elif step.wave is not None:
    written = write_wave(demo_dir, election, step.wave)
```

- [ ] **Step 8: Run test — expect PASS**

```bash
pytest tests/test_demo.py::test_runner_uses_write_fn -v
```

- [ ] **Step 9: Run full test suite to check no regressions**

```bash
pytest tests/test_demo.py -v
```

Expected: all pass.

---

### Task 2: Add `steps_factory` to `Scenario` and update `start()`

**Files:**
- Modify: `valg/demo.py`
- Modify: `tests/test_demo.py`

- [ ] **Step 1: Write failing tests for `steps_factory`**

Add to `tests/test_demo.py`:

```python
def test_scenario_steps_factory_default_none():
    s = Scenario(name="x", description="y", steps=[])
    assert s.steps_factory is None


def test_scenario_steps_factory_called_at_start(tmp_path):
    db = tmp_path / "valg.db"
    data_repo = tmp_path / "data"
    data_repo.mkdir()
    import subprocess
    subprocess.run(["git", "init"], cwd=data_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=data_repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=data_repo, check=True, capture_output=True)

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
        import time; time.sleep(0.5)
        assert factory_args == [data_repo], f"factory not called with data_repo, got {factory_args}"
    finally:
        SCENARIOS.clear()
        SCENARIOS.update(original)
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_demo.py::test_scenario_steps_factory_default_none tests/test_demo.py::test_scenario_steps_factory_called_at_start -v
```

- [ ] **Step 3: Add `steps_factory` to `Scenario` in `valg/demo.py`**

```python
@dataclass
class Scenario:
    name: str
    description: str
    steps: list[Step]
    steps_factory: Callable[["Path"], list[Step]] | None = None  # NEW
```

- [ ] **Step 4: Update `DemoRunner.start()` to resolve steps from factory**

In `DemoRunner.start()`, after setting `self._data_repo`:

```python
def start(self, db_path: Path, data_repo: Path) -> None:
    with self._lock:
        if self.state == "running":
            return
        self.state = "running"
        self.step_index = -1
        self._db_path = Path(db_path)
        self._data_repo = Path(data_repo)
        scenario = get_scenario(self.scenario_name)
        # Resolve steps — use factory if provided
        if scenario.steps_factory is not None:
            self._resolved_steps = scenario.steps_factory(self._data_repo)
        else:
            self._resolved_steps = scenario.steps
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
    t = threading.Thread(target=self._run, daemon=True)
    t.start()
    self._thread = t
```

- [ ] **Step 5: Update `_run` to use `self._resolved_steps`**

In `_run`, make three changes:

1. Remove `scenario = get_scenario(self.scenario_name)` and `election = make_election()` (no longer needed at the top of `_run` — steps are already resolved).

2. Replace the loop header:
```python
for i, step in enumerate(scenario.steps):
```
with:
```python
for i, step in enumerate(self._resolved_steps):
```

3. At the very end of `_run`, replace the trailing reference:
```python
self.step_index = len(scenario.steps) - 1
```
with:
```python
self.step_index = len(self._resolved_steps) - 1
```

Also update `get_state_dict` to use `self._resolved_steps` if set. Use `is not None` (not `or`) so an empty list doesn't fall through to `scenario.steps`:

```python
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
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
pytest tests/test_demo.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add valg/demo.py tests/test_demo.py
git commit -m "feat(demo): add write_fn to Step and steps_factory to Scenario"
```

---

## Chunk 2: KV2025 transformation module

### Task 3: Create `valg/scenarios/` package and transformation module

**Files:**
- Create: `valg/scenarios/__init__.py`
- Create: `valg/scenarios/kv2025_transform.py`
- Create: `tests/test_kv2025_transform.py`

The transformation module contains pure functions — no I/O, no SFTP, no file writes. All functions take parsed dicts and return dicts/lists ready to serialize.

- [ ] **Step 1: Create package marker**

Create `valg/scenarios/__init__.py` as an empty file.

- [ ] **Step 2: Write all failing tests for `kv2025_transform.py`**

Create `tests/test_kv2025_transform.py`:

```python
"""Tests for KV2025 → FV transformation functions."""
import pytest
from valg.scenarios.kv2025_transform import (
    FT_PARTY_LETTERS,
    filter_ft_lists,
    build_party_registry,
    transform_storkreds_json,
    transform_geography_files,
    assign_candidates_to_ok,
    transform_kandidatdata_json,
    transform_valgresultater_preliminary,
    transform_valgresultater_final,
    aggregate_partistemmer,
    bucket_aos,
)


# ── filter_ft_lists ─────────────────────────────────────────────────────────

def test_filter_ft_lists_keeps_ft_parties():
    lists = [
        {"Bogstavbetegnelse": "A", "Stemmer": 100, "Kandidater": []},
        {"Bogstavbetegnelse": "L", "Stemmer": 50, "Kandidater": []},  # local
        {"Bogstavbetegnelse": "V", "Stemmer": 200, "Kandidater": []},
    ]
    result = filter_ft_lists(lists)
    assert len(result) == 2
    assert {r["Bogstavbetegnelse"] for r in result} == {"A", "V"}


def test_filter_ft_lists_empty():
    assert filter_ft_lists([]) == []


def test_filter_ft_lists_all_local():
    lists = [{"Bogstavbetegnelse": "G", "Stemmer": 10, "Kandidater": []}]
    assert filter_ft_lists(lists) == []


# ── build_party_registry ─────────────────────────────────────────────────────

def test_build_party_registry_first_occurrence_wins():
    """First name seen for each letter is canonical."""
    results_by_kommune = [
        [  # Aabenraa
            {"Bogstavbetegnelse": "A", "Navn": "Socialdemokratiet", "KandidatlisteId": "x"},
            {"Bogstavbetegnelse": "L", "Navn": "Lokal Liste", "KandidatlisteId": "y"},
        ],
        [  # Aalborg — A appears again with different name
            {"Bogstavbetegnelse": "A", "Navn": "Socialdemokraterne", "KandidatlisteId": "z"},
            {"Bogstavbetegnelse": "V", "Navn": "Venstre", "KandidatlisteId": "w"},
        ],
    ]
    registry = build_party_registry(results_by_kommune)
    assert registry["A"] == "Socialdemokratiet"  # first occurrence wins
    assert registry["V"] == "Venstre"
    assert "L" not in registry  # local list filtered out


def test_build_party_registry_empty():
    assert build_party_registry([]) == {}


# ── transform_storkreds_json ─────────────────────────────────────────────────

def test_transform_storkreds_json():
    kommuner = [
        {"Kode": 101, "Navn": "København"},
        {"Kode": 851, "Navn": "Aalborg"},
    ]
    mandatfordeling = {101: 55, 851: 31}
    result = transform_storkreds_json(kommuner, mandatfordeling)
    assert len(result) == 2
    kbh = next(r for r in result if r["Kode"] == "101")
    assert kbh["Navn"] == "København"
    assert kbh["AntalKredsmandater"] == 55
    assert kbh["ValgId"] == "KV2025"


def test_transform_storkreds_json_missing_mandatfordeling():
    """Kommuner without mandatfordeling entry get a default of 0."""
    kommuner = [{"Kode": 999, "Navn": "Unknown"}]
    result = transform_storkreds_json(kommuner, {})
    assert result[0]["AntalKredsmandater"] == 0


# ── transform_geography_files ────────────────────────────────────────────────

def test_transform_geography_files_keys():
    kommuner = [{"Kode": 101, "Navn": "København", "Dagi_id": "111"}]
    opstillingskredse = [{"Kode": 10101, "Navn": "Bispebjerg", "KommuneKode": 101, "Dagi_id": "222"}]
    aos = [{"Dagi_id": "333", "Nummer": 1, "Navn": "Bispebjerg Skole",
            "OpstillingskredsKode": 10101, "StemmeberettigeteVaelgere": 2500}]
    result = transform_geography_files(kommuner, opstillingskredse, aos)
    assert "Opstillingskreds" in result
    assert "Afstemningsomraade" in result
    ok = result["Opstillingskreds"][0]
    assert ok["Kode"] == "10101"
    assert ok["Navn"] == "Bispebjerg"
    assert ok["StorkredskodeKode"] == "101"  # parent kommune as storkreds
    ao = result["Afstemningsomraade"][0]
    assert ao["Kode"] == "333"
    assert ao["OpstillingskredsKode"] == "10101"
    assert ao["AntalStemmeberettigede"] == 2500


# ── assign_candidates_to_ok ──────────────────────────────────────────────────

def test_assign_candidates_to_ok_uses_largest():
    """All candidates for a party in a kommune go to the largest opstillingskreds."""
    ok_by_voters = {
        "10101": 500,
        "10102": 2000,  # largest
        "10103": 800,
    }
    kommune_kode = 101
    ok_kode_to_storkreds = {"10101": "101", "10102": "101", "10103": "101"}
    kandidater = [
        {"Id": "c1", "Stemmeseddelnavn": "Anne Larsen, København", "Nummer": 1},
        {"Id": "c2", "Stemmeseddelnavn": "Bo Mikkelsen, København", "Nummer": 2},
    ]
    result = assign_candidates_to_ok(kandidater, "A", kommune_kode, ok_by_voters, ok_kode_to_storkreds)
    assert all(r["ok_id"] == "10102" for r in result)
    assert all(r["party_letter"] == "A" for r in result)
    assert result[0]["id"] == "c1"
    assert result[1]["ballot_position"] == 2


# ── transform_kandidatdata_json ───────────────────────────────────────────────

def test_transform_kandidatdata_json_structure():
    party_registry = {"A": "Socialdemokratiet", "V": "Venstre"}
    candidates = [
        {"id": "c1", "name": "Anne Larsen", "party_letter": "A",
         "ok_id": "10101", "ballot_position": 1},
        {"id": "c2", "name": "Bo Mikkelsen", "party_letter": "V",
         "ok_id": "10101", "ballot_position": 1},
    ]
    result = transform_kandidatdata_json(party_registry, candidates)
    assert result["Valg"]["Id"] == "KV2025"
    parties = result["Valg"]["IndenforParti"]
    a_entry = next(p for p in parties if p["Id"] == "A")
    assert len(a_entry["Kandidater"]) == 1
    assert a_entry["Kandidater"][0]["Id"] == "c1"
    assert a_entry["Kandidater"][0]["Stemmeseddelplacering"] == 1


# ── transform_valgresultater_preliminary ─────────────────────────────────────

def test_transform_valgresultater_preliminary():
    party_registry = {"A": "Socialdemokratiet", "V": "Venstre"}
    ao_result = {
        "AfstemningsomraadeDagiId": "333",
        "Kandidatlister": [
            {"Bogstavbetegnelse": "A", "Navn": "Socialdemokratiet",
             "KandidatlisteId": "x", "Stemmer": 150, "Listestemmer": 30,
             "Kandidater": [{"Id": "c1", "Stemmeseddelnavn": "Anne", "Stemmer": 120}]},
            {"Bogstavbetegnelse": "L", "Navn": "Lokal", "KandidatlisteId": "y",
             "Stemmer": 20, "Listestemmer": 20, "Kandidater": []},
        ],
    }
    result = transform_valgresultater_preliminary(ao_result, party_registry)
    vr = result["Valgresultater"]
    assert vr["AfstemningsomraadeId"] == "333"
    assert vr["Optaellingstype"] == "Foreløbig"
    assert len(vr["IndenforParti"]) == 1  # only A, L filtered out
    party = vr["IndenforParti"][0]
    assert party["PartiId"] == "A"
    assert party["Partistemmer"] == 150
    assert party["Kandidater"] == []  # no candidates in preliminary


def test_transform_valgresultater_preliminary_all_local():
    party_registry = {"V": "Venstre"}
    ao_result = {
        "AfstemningsomraadeDagiId": "333",
        "Kandidatlister": [
            {"Bogstavbetegnelse": "L", "Navn": "Lokal", "KandidatlisteId": "y",
             "Stemmer": 20, "Listestemmer": 20, "Kandidater": []},
        ],
    }
    result = transform_valgresultater_preliminary(ao_result, party_registry)
    assert result["Valgresultater"]["IndenforParti"] == []


# ── transform_valgresultater_final ───────────────────────────────────────────

def test_transform_valgresultater_final():
    party_registry = {"A": "Socialdemokratiet"}
    ao_result = {
        "AfstemningsomraadeDagiId": "333",
        "Kandidatlister": [
            {"Bogstavbetegnelse": "A", "Navn": "Socialdemokratiet",
             "KandidatlisteId": "x", "Stemmer": 150, "Listestemmer": 30,
             "Kandidater": [
                 {"Id": "c1", "Stemmeseddelnavn": "Anne", "Stemmer": 120},
                 {"Id": "c2", "Stemmeseddelnavn": "Bo", "Stemmer": 30},
             ]},
        ],
    }
    result = transform_valgresultater_final(ao_result, party_registry)
    vr = result["Valgresultater"]
    assert vr["Optaellingstype"] == "Fintaelling"
    party = vr["IndenforParti"][0]
    assert len(party["Kandidater"]) == 2
    assert party["Kandidater"][0] == {"KandidatId": "c1", "Stemmer": 120}


# ── aggregate_partistemmer ───────────────────────────────────────────────────

def test_aggregate_partistemmer():
    """Sums Stemmer per party per opstillingskreds across AOs."""
    party_registry = {"A": "Socialdemokratiet", "V": "Venstre"}
    # Two AOs in the same opstillingskreds
    ao_results = [
        {
            "AfstemningsomraadeDagiId": "ao1",
            "Kandidatlister": [
                {"Bogstavbetegnelse": "A", "KandidatlisteId": "x", "Stemmer": 100, "Listestemmer": 20, "Kandidater": []},
            ],
        },
        {
            "AfstemningsomraadeDagiId": "ao2",
            "Kandidatlister": [
                {"Bogstavbetegnelse": "A", "KandidatlisteId": "x", "Stemmer": 80, "Listestemmer": 10, "Kandidater": []},
                {"Bogstavbetegnelse": "V", "KandidatlisteId": "y", "Stemmer": 50, "Listestemmer": 50, "Kandidater": []},
            ],
        },
    ]
    ao_to_ok = {"ao1": "ok1", "ao2": "ok1"}
    result = aggregate_partistemmer(ao_results, party_registry, ao_to_ok)
    assert "ok1" in result
    ok1 = result["ok1"]
    assert ok1["Valg"]["OpstillingskredsId"] == "ok1"
    parties = {p["PartiId"]: p["Stemmer"] for p in ok1["Valg"]["Partier"]}
    assert parties["A"] == 180  # 100 + 80
    assert parties["V"] == 50


# ── bucket_aos ───────────────────────────────────────────────────────────────

def test_bucket_aos_sorted_ascending():
    """AOs are sorted by eligible_voters and split at thresholds."""
    aos = [
        {"id": "a", "eligible_voters": 3000},
        {"id": "b", "eligible_voters": 200},
        {"id": "c", "eligible_voters": 800},
        {"id": "d", "eligible_voters": 8000},
        {"id": "e", "eligible_voters": 1200},
    ]
    thresholds = [500, 1000, 5000]
    buckets = bucket_aos(aos, thresholds)
    # bucket 0: <500   → b(200)
    # bucket 1: 500-1000 → c(800)
    # bucket 2: 1000-5000 → e(1200), a(3000)
    # bucket 3: >5000  → d(8000)
    assert len(buckets) == 4
    assert [x["id"] for x in buckets[0]] == ["b"]
    assert [x["id"] for x in buckets[1]] == ["c"]
    assert [x["id"] for x in buckets[2]] == ["e", "a"]
    assert [x["id"] for x in buckets[3]] == ["d"]


def test_bucket_aos_empty_bucket_excluded():
    """Empty buckets (no AOs in range) are omitted."""
    aos = [
        {"id": "a", "eligible_voters": 200},
        {"id": "b", "eligible_voters": 8000},
    ]
    thresholds = [500, 1000, 5000]
    buckets = bucket_aos(aos, thresholds)
    # bucket 0: <500 → a
    # bucket 1: 500-1000 → empty (skip)
    # bucket 2: 1000-5000 → empty (skip)
    # bucket 3: >5000 → b
    assert len(buckets) == 2
    assert buckets[0][0]["id"] == "a"
    assert buckets[1][0]["id"] == "b"
```

- [ ] **Step 3: Run tests — expect all FAIL (module not found)**

```bash
pytest tests/test_kv2025_transform.py -v
```

Expected: `ModuleNotFoundError: No module named 'valg.scenarios.kv2025_transform'`

- [ ] **Step 4: Create `valg/scenarios/kv2025_transform.py` with all functions**

```python
"""
Pure transformation functions: KV2025 (kommunalvalg) → FV (folketingsvalg) format.

No I/O. All functions take parsed dicts and return serialisable dicts/lists.
Election ID used throughout: KV2025
"""
from __future__ import annotations

FT_PARTY_LETTERS: frozenset[str] = frozenset(
    {"A", "B", "C", "D", "F", "I", "M", "O", "V", "Ø", "Å"}
)

_ELECTION_ID = "KV2025"


def filter_ft_lists(kandidatlister: list[dict]) -> list[dict]:
    """Keep only lists whose Bogstavbetegnelse is a national FT party letter."""
    return [k for k in kandidatlister if k.get("Bogstavbetegnelse") in FT_PARTY_LETTERS]


def build_party_registry(results_by_kommune: list[list[dict]]) -> dict[str, str]:
    """
    Return {letter: name} for all FT parties found across all kommuner.
    First occurrence of each letter wins.

    Each element in results_by_kommune is the list of Kandidatlister for one kommune
    (from valgresultater or kandidat-data files).
    """
    registry: dict[str, str] = {}
    for lists in results_by_kommune:
        for kl in lists:
            letter = kl.get("Bogstavbetegnelse", "")
            if letter in FT_PARTY_LETTERS and letter not in registry:
                registry[letter] = kl.get("Navn", letter)
    return registry


def transform_storkreds_json(
    kommuner: list[dict],
    mandatfordeling: dict[int, int],
) -> list[dict]:
    """
    Return a list of FV-format storkreds dicts (content of Storkreds.json).

    kommuner: list of Kommune dicts from SFTP geografi/Kommune-*.json
    mandatfordeling: {kommune_kode: byraadssize}
    """
    return [
        {
            "Kode": str(k["Kode"]),
            "Navn": k["Navn"],
            "AntalKredsmandater": mandatfordeling.get(k["Kode"], 0),
            "ValgId": _ELECTION_ID,
        }
        for k in kommuner
    ]


def transform_geography_files(
    kommuner: list[dict],
    opstillingskredse: list[dict],
    afstemningsomraader: list[dict],
) -> dict[str, list[dict]]:
    """
    Return FV-format geography dicts for Opstillingskreds and Afstemningsomraade files.

    Returns:
        {
            "Opstillingskreds": [...],
            "Afstemningsomraade": [...],
        }
    """
    ok_list = [
        {
            "Kode": str(ok["Kode"]),
            "Navn": ok["Navn"],
            "StorkredskodeKode": str(ok["KommuneKode"]),
            "ValgId": _ELECTION_ID,
        }
        for ok in opstillingskredse
    ]
    ao_list = [
        {
            "Kode": ao["Dagi_id"],
            "Navn": ao["Navn"],
            "OpstillingskredsKode": str(ao["OpstillingskredsKode"]),
            "AntalStemmeberettigede": ao.get("StemmeberettigeteVaelgere", 0),
            "ValgId": _ELECTION_ID,
        }
        for ao in afstemningsomraader
    ]
    return {"Opstillingskreds": ok_list, "Afstemningsomraade": ao_list}


def assign_candidates_to_ok(
    kandidater: list[dict],
    party_letter: str,
    kommune_kode: int,
    ok_by_voters: dict[str, int],
    ok_kode_to_storkreds: dict[str, str],
) -> list[dict]:
    """
    Assign all candidates for a party list in a kommune to the largest opstillingskreds
    (by eligible voters) in that kommune.

    Returns list of candidate dicts with fields: id, name, party_letter, ok_id,
    ballot_position.
    """
    # Find the largest OK in this kommune
    kommune_oks = [k for k in ok_by_voters if ok_kode_to_storkreds.get(k) == str(kommune_kode)]
    if not kommune_oks:
        return []
    target_ok = max(kommune_oks, key=lambda k: ok_by_voters[k])
    return [
        {
            "id": c["Id"],
            "name": c.get("Stemmeseddelnavn", c.get("Navn", "")),
            "party_letter": party_letter,
            "ok_id": target_ok,
            "ballot_position": c.get("Nummer", i + 1),
        }
        for i, c in enumerate(kandidater)
    ]


def transform_kandidatdata_json(
    party_registry: dict[str, str],
    candidates: list[dict],
) -> dict:
    """
    Return FV-format kandidat-data dict (content of kandidat-data-Folketingsvalg-KV2025.json).

    candidates: list of dicts with keys: id, name, party_letter, ok_id, ballot_position
    """
    by_party: dict[str, list] = {}
    for c in candidates:
        letter = c.get("party_letter", "")
        if letter in party_registry:
            by_party.setdefault(letter, []).append(c)
    return {
        "Valg": {
            "Id": _ELECTION_ID,
            "IndenforParti": [
                {
                    "Id": letter,
                    "Kandidater": [
                        {
                            "Id": c["id"],
                            "Navn": c["name"],
                            "Stemmeseddelplacering": c.get("ballot_position", 1),
                        }
                        for c in cands
                    ],
                }
                for letter, cands in by_party.items()
            ],
            "UdenforParti": {"Kandidater": []},
        }
    }


def transform_valgresultater_preliminary(
    ao_result: dict,
    party_registry: dict[str, str],
) -> dict:
    """
    Return FV-format preliminary valgresultater dict (Foreløbig, no candidate votes).

    ao_result: one entry from valgresultater SFTP file (has AfstemningsomraadeDagiId,
               Kandidatlister)
    """
    ft_lists = filter_ft_lists(ao_result.get("Kandidatlister", []))
    return {
        "Valgresultater": {
            "AfstemningsomraadeId": ao_result["AfstemningsomraadeDagiId"],
            "Optaellingstype": "Foreløbig",
            "IndenforParti": [
                {
                    "PartiId": kl["Bogstavbetegnelse"],
                    "Partistemmer": kl.get("Stemmer", 0),
                    "Kandidater": [],
                }
                for kl in ft_lists
            ],
            "KandidaterUdenforParti": [],
        }
    }


def transform_valgresultater_final(
    ao_result: dict,
    party_registry: dict[str, str],
) -> dict:
    """
    Return FV-format final valgresultater dict (Fintaelling, with candidate votes).
    """
    ft_lists = filter_ft_lists(ao_result.get("Kandidatlister", []))
    return {
        "Valgresultater": {
            "AfstemningsomraadeId": ao_result["AfstemningsomraadeDagiId"],
            "Optaellingstype": "Fintaelling",
            "IndenforParti": [
                {
                    "PartiId": kl["Bogstavbetegnelse"],
                    "Partistemmer": kl.get("Stemmer", 0),
                    "Kandidater": [
                        {"KandidatId": c["Id"], "Stemmer": c.get("Stemmer", 0)}
                        for c in kl.get("Kandidater", [])
                    ],
                }
                for kl in ft_lists
            ],
            "KandidaterUdenforParti": [],
        }
    }


def aggregate_partistemmer(
    ao_results: list[dict],
    party_registry: dict[str, str],
    ao_to_ok: dict[str, str],
) -> dict[str, dict]:
    """
    Aggregate party votes per opstillingskreds from ALL ao_results seen so far
    (cumulative, not just the current wave's batch).

    Callers must pass the full accumulated list of AO results up to the current
    wave — not just the current wave's new AOs. This mirrors how real
    partistemmefordeling files are overwritten each sync with the running total.

    Returns {ok_id: partistemmefordeling_data} — one entry per opstillingskreds
    that has at least one reported AO in ao_results.
    """
    totals: dict[str, dict[str, int]] = {}  # ok_id -> {letter: votes}
    for ao in ao_results:
        ao_id = ao["AfstemningsomraadeDagiId"]
        ok_id = ao_to_ok.get(ao_id)
        if ok_id is None:
            continue
        for kl in filter_ft_lists(ao.get("Kandidatlister", [])):
            letter = kl["Bogstavbetegnelse"]
            totals.setdefault(ok_id, {}).setdefault(letter, 0)
            totals[ok_id][letter] += kl.get("Stemmer", 0)

    result = {}
    for ok_id, party_totals in totals.items():
        result[ok_id] = {
            "Valg": {
                "OpstillingskredsId": ok_id,
                "Partier": [
                    {"PartiId": letter, "Stemmer": votes}
                    for letter, votes in party_totals.items()
                ],
            }
        }
    return result


def bucket_aos(
    aos: list[dict],
    thresholds: list[int],
) -> list[list[dict]]:
    """
    Sort AOs by eligible_voters ascending, split into buckets at voter-count thresholds.
    Empty buckets are omitted.

    thresholds: e.g. [500, 1000, 1500, ...] defines N+1 buckets.
    """
    sorted_aos = sorted(aos, key=lambda a: a.get("eligible_voters", 0))
    buckets: list[list[dict]] = []
    prev = 0
    for threshold in thresholds:
        bucket = [a for a in sorted_aos
                  if prev <= a.get("eligible_voters", 0) < threshold]
        if bucket:
            buckets.append(bucket)
        prev = threshold
    # Final bucket: >= last threshold
    final = [a for a in sorted_aos if a.get("eligible_voters", 0) >= prev]
    if final:
        buckets.append(final)
    return buckets
```

- [ ] **Step 5: Run tests — expect all PASS**

```bash
pytest tests/test_kv2025_transform.py -v
```

Expected: all 14 tests pass.

- [ ] **Step 6: Commit**

```bash
git add valg/scenarios/__init__.py valg/scenarios/kv2025_transform.py tests/test_kv2025_transform.py
git commit -m "feat(kv2025): add KV→FV transformation module with tests"
```

---

## Chunk 3: Preparation script

### Task 4: Write `prepare_kv2025.py`

**Files:**
- Create: `valg/scenarios/prepare_kv2025.py`

This is a one-time script run manually. It:
1. Downloads all KV2025 data from SFTP to a local cache dir
2. Parses all files
3. Builds FV-format JSON for each wave
4. Writes wave bundles to `valg/scenarios/kv2025/wave_NN/`

No unit tests (SFTP I/O). Manual verification after running.

- [ ] **Step 1: Create `valg/scenarios/prepare_kv2025.py`**

```python
"""
One-time preparation script: download KV2025 data from SFTP and generate
pre-sorted wave bundles in valg/scenarios/kv2025/.

Run from the valg/ repo root:
    python -m valg.scenarios.prepare_kv2025

Requires VALG_SFTP_* env vars (same credentials as production sync).
Output: valg/scenarios/kv2025/wave_00/ through wave_NN/ with FV-format JSON files.

Re-running is safe — output directory is cleared first.
"""
from __future__ import annotations

import io
import json
import logging
import shutil
from pathlib import Path

from valg.fetcher import get_sftp_client
from valg.scenarios.kv2025_transform import (
    FT_PARTY_LETTERS,
    aggregate_partistemmer,
    build_party_registry,
    bucket_aos,
    transform_geography_files,
    transform_kandidatdata_json,
    transform_storkreds_json,
    transform_valgresultater_final,
    transform_valgresultater_preliminary,
    assign_candidates_to_ok,
)

log = logging.getLogger(__name__)

SFTP_FOLDER = "data/kommunalvalg-134-18-11-2025"
OUTPUT_DIR = Path(__file__).parent / "kv2025"
ELECTION_ID = "KV2025"

# Voter-count thresholds for preliminary wave buckets (11 buckets)
PRELIMINARY_THRESHOLDS = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 5000, 7000]

# base_interval_s per preliminary bucket (index 0..10)
PRELIMINARY_INTERVALS = [90, 75, 60, 55, 50, 45, 40, 40, 45, 55, 70, 90]

# Fintælling groups: each is a list of preliminary bucket indices to merge
FINAL_GROUPS = [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10]]
FINAL_INTERVALS = [75, 60, 55, 55, 65, 90]


def _read_json(sftp, path: str) -> dict | list:
    buf = io.BytesIO()
    sftp.getfo(path, buf)
    return json.loads(buf.getvalue())


def _list_json(sftp, folder: str) -> list[str]:
    return [
        f"{folder}/{f}"
        for f in sftp.listdir(folder)
        if f.endswith(".json") and not f.endswith(".hash")
    ]


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _write_meta(wave_dir: Path, label: str, interval_s: float, phase: str) -> None:
    _write(wave_dir / "_meta.json", {
        "label": label,
        "interval_s": interval_s,
        "phase": phase,
    })


def run(sftp) -> None:
    base = SFTP_FOLDER

    # ── 1. Download raw data ───────────────────────────────────────────────

    log.info("Downloading geografi...")
    geo_files = sftp.listdir(f"{base}/geografi")
    kommune_file = next(f for f in geo_files if f.startswith("Kommune-") and not f.endswith(".hash"))
    ok_file = next(f for f in geo_files if f.startswith("Opstillingskreds-") and not f.endswith(".hash"))
    ao_file = next(f for f in geo_files if f.startswith("Afstemningsomraade-") and not f.endswith(".hash"))

    kommuner: list[dict] = _read_json(sftp, f"{base}/geografi/{kommune_file}")
    opstillingskredse: list[dict] = _read_json(sftp, f"{base}/geografi/{ok_file}")
    afstemningsomraader: list[dict] = _read_json(sftp, f"{base}/geografi/{ao_file}")

    log.info("  %d kommuner, %d opstillingskredse, %d afstemningsomraader",
             len(kommuner), len(opstillingskredse), len(afstemningsomraader))

    log.info("Downloading mandatfordeling...")
    mf_files = [f for f in sftp.listdir(f"{base}/mandatfordeling")
                if f.endswith(".json") and not f.endswith(".hash")]
    mandatfordeling: dict[int, int] = {}
    for fname in mf_files:
        data = _read_json(sftp, f"{base}/mandatfordeling/{fname}")
        if isinstance(data, dict) and "KommuneKode" in data:
            mandatfordeling[data["KommuneKode"]] = data.get("AntalMandater", 0)
    log.info("  %d kommuner with mandatfordeling", len(mandatfordeling))

    log.info("Downloading kandidat-data...")
    kd_files = [f for f in sftp.listdir(f"{base}/kandidat-data")
                if f.endswith(".json") and not f.endswith(".hash")]
    kd_by_kommune: dict[str, dict] = {}
    for fname in kd_files:
        data = _read_json(sftp, f"{base}/kandidat-data/{fname}")
        if isinstance(data, dict):
            kd_by_kommune[data.get("Kommune", fname)] = data
    log.info("  %d kommuner with kandidat-data", len(kd_by_kommune))

    log.info("Downloading valgresultater...")
    vr_files = [f for f in sftp.listdir(f"{base}/valgresultater")
                if f.endswith(".json") and not f.endswith(".hash")]
    # Each file is one AO's results — keyed by AfstemningsomraadeDagiId
    ao_results: dict[str, dict] = {}
    for fname in vr_files:
        data = _read_json(sftp, f"{base}/valgresultater/{fname}")
        if isinstance(data, dict) and "AfstemningsomraadeDagiId" in data:
            ao_results[data["AfstemningsomraadeDagiId"]] = data
    log.info("  %d AO results downloaded", len(ao_results))

    log.info("Downloading valgdeltagelse...")
    vd_files = [f for f in sftp.listdir(f"{base}/valgdeltagelse")
                if f.endswith(".json") and not f.endswith(".hash")]
    ao_turnout: dict[str, dict] = {}
    for fname in vd_files:
        data = _read_json(sftp, f"{base}/valgdeltagelse/{fname}")
        if isinstance(data, dict) and "AfstemningsområdeDagiId" in data:
            ao_turnout[data["AfstemningsområdeDagiId"]] = data
    log.info("  %d AO turnout files downloaded", len(ao_turnout))

    # ── 2. Build lookup tables ─────────────────────────────────────────────

    # AO Dagi_id → eligible_voters
    ao_voters: dict[str, int] = {
        ao["Dagi_id"]: ao.get("StemmeberettigeteVaelgere", 0)
        for ao in afstemningsomraader
    }

    # AO Dagi_id → opstillingskreds Kode (str)
    ao_to_ok: dict[str, str] = {
        ao["Dagi_id"]: str(ao["OpstillingskredsKode"])
        for ao in afstemningsomraader
    }

    # OK Kode (str) → storkreds (kommune) Kode (str)
    ok_to_storkreds: dict[str, str] = {
        str(ok["Kode"]): str(ok["KommuneKode"])
        for ok in opstillingskredse
    }

    # OK Kode (str) → total eligible voters in that OK
    ok_voters: dict[str, int] = {}
    for ao in afstemningsomraader:
        ok_id = str(ao["OpstillingskredsKode"])
        ok_voters[ok_id] = ok_voters.get(ok_id, 0) + ao.get("StemmeberettigeteVaelgere", 0)

    # ── 3. Build party registry ────────────────────────────────────────────

    all_result_lists = [
        r.get("Kandidatlister", [])
        for r in ao_results.values()
    ]
    party_registry = build_party_registry(all_result_lists)
    log.info("Party registry: %s", sorted(party_registry.keys()))

    # ── 4. Build candidate list ────────────────────────────────────────────

    all_candidates: list[dict] = []
    for kommune_name, kd in kd_by_kommune.items():
        kommune_kode = next(
            (k["Kode"] for k in kommuner if k["Navn"] == kommune_name), None
        )
        if kommune_kode is None:
            continue
        for valgforbund_or_list in kd.get("Kandidatlister", []):
            letter = valgforbund_or_list.get("Bogstavbetegnelse", "")
            if letter not in FT_PARTY_LETTERS:
                continue
            kandidater = valgforbund_or_list.get("Kandidater", [])
            assigned = assign_candidates_to_ok(
                kandidater, letter, kommune_kode, ok_voters, ok_to_storkreds
            )
            all_candidates.extend(assigned)
    log.info("  %d candidates assigned", len(all_candidates))

    # ── 5. Sort and bucket AOs ─────────────────────────────────────────────

    aos_with_voters = [
        {"id": ao["Dagi_id"], "eligible_voters": ao.get("StemmeberettigeteVaelgere", 0)}
        for ao in afstemningsomraader
        if ao["Dagi_id"] in ao_results  # only AOs with result data
    ]
    prelim_buckets = bucket_aos(aos_with_voters, PRELIMINARY_THRESHOLDS)
    log.info("Preliminary buckets: %s", [len(b) for b in prelim_buckets])

    # Fintælling buckets: merge preliminary buckets per FINAL_GROUPS
    final_buckets = []
    for group in FINAL_GROUPS:
        merged = []
        for idx in group:
            if idx < len(prelim_buckets):
                merged.extend(prelim_buckets[idx])
        if merged:
            final_buckets.append(merged)

    # ── 6. Clear output dir ────────────────────────────────────────────────

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    # ── 7. Wave 00: setup (Storkreds.json + geografi + kandidat-data) ──────

    wave00 = OUTPUT_DIR / "wave_00"
    _write_meta(wave00, "Setup — geografi & kandidater", 0.0, "setup")

    storkreds_data = transform_storkreds_json(kommuner, mandatfordeling)
    _write(wave00 / "Storkreds.json", storkreds_data)

    geo = transform_geography_files(kommuner, opstillingskredse, afstemningsomraader)
    _write(wave00 / "geografi" / "Opstillingskreds-KV2025.json", geo["Opstillingskreds"])
    _write(wave00 / "geografi" / "Afstemningsomraade-KV2025.json", geo["Afstemningsomraade"])

    kd_json = transform_kandidatdata_json(party_registry, all_candidates)
    _write(wave00 / "kandidat-data" / "kandidat-data-Folketingsvalg-KV2025.json", kd_json)

    log.info("Wrote wave_00 (setup)")

    # ── 8. Preliminary waves ───────────────────────────────────────────────

    # Track all AO results seen so far for running partistemmer totals
    seen_ao_results: list[dict] = []

    for bucket_idx, bucket in enumerate(prelim_buckets):
        wave_num = bucket_idx + 1
        wave_dir = OUTPUT_DIR / f"wave_{wave_num:02d}"
        interval = PRELIMINARY_INTERVALS[min(bucket_idx, len(PRELIMINARY_INTERVALS) - 1)]
        n_voters = int(sum(a["eligible_voters"] for a in bucket))
        label = f"Foreløbig — batch {wave_num} ({len(bucket)} stemmeafgivelsesområder)"
        _write_meta(wave_dir, label, float(interval), "preliminary")

        batch_ao_results = []
        for ao in bucket:
            ao_id = ao["id"]
            if ao_id not in ao_results:
                continue
            result = ao_results[ao_id]
            prelim = transform_valgresultater_preliminary(result, party_registry)
            _write(wave_dir / "valgresultater" / f"valgresultater-Folketingsvalg-{ao_id}.json", prelim)

            if ao_id in ao_turnout:
                _write(wave_dir / "valgdeltagelse" / f"valgdeltagelse-{ao_id}.json", ao_turnout[ao_id])

            batch_ao_results.append(result)

        seen_ao_results.extend(batch_ao_results)

        # Write running partistemmer totals for all AOs seen so far
        partistemmer = aggregate_partistemmer(seen_ao_results, party_registry, ao_to_ok)
        for ok_id, data in partistemmer.items():
            _write(wave_dir / "partistemmefordeling" / f"partistemmefordeling-{ok_id}.json", data)

        log.info("Wrote wave_%02d: %d AOs, %d OK partistemmer", wave_num, len(bucket), len(partistemmer))

    # ── 9. Fintælling waves ────────────────────────────────────────────────

    prelim_wave_count = len(prelim_buckets)
    for grp_idx, group_bucket in enumerate(final_buckets):
        wave_num = prelim_wave_count + 1 + grp_idx
        wave_dir = OUTPUT_DIR / f"wave_{wave_num:02d}"
        interval = FINAL_INTERVALS[min(grp_idx, len(FINAL_INTERVALS) - 1)]
        label = f"Fintælling — batch {grp_idx + 1} ({len(group_bucket)} stemmeafgivelsesområder)"
        _write_meta(wave_dir, label, float(interval), "final")

        for ao in group_bucket:
            ao_id = ao["id"]
            if ao_id not in ao_results:
                continue
            result = ao_results[ao_id]
            final = transform_valgresultater_final(result, party_registry)
            _write(wave_dir / "valgresultater" / f"valgresultater-Folketingsvalg-{ao_id}.json", final)

        log.info("Wrote wave_%02d (fintælling batch %d): %d AOs", wave_num, grp_idx + 1, len(group_bucket))

    log.info("Done. Wrote %d waves to %s", prelim_wave_count + len(final_buckets) + 1, OUTPUT_DIR)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("Connecting to SFTP...")
    ssh, sftp = get_sftp_client()
    try:
        run(sftp)
    finally:
        sftp.close()
        ssh.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Check mandatfordeling file format to verify `KommuneKode` and `AntalMandater` fields**

```bash
.venv/bin/python -c "
from valg.fetcher import get_sftp_client
import json, io
ssh, sftp = get_sftp_client()
buf = io.BytesIO()
sftp.getfo('./data/kommunalvalg-134-18-11-2025/mandatfordeling/mandatfordeling-Kommunalvalg-Aabenraa-191120251754.json', buf)
print(json.dumps(json.loads(buf.getvalue()), indent=2, ensure_ascii=False)[:800])
sftp.close(); ssh.close()
"
```

Inspect output and adjust field names in `prepare_kv2025.py` if they differ from `KommuneKode`/`AntalMandater`.

- [ ] **Step 3: Check full Opstillingskreds geografi file for field names**

```bash
.venv/bin/python -c "
from valg.fetcher import get_sftp_client
import json, io
ssh, sftp = get_sftp_client()
buf = io.BytesIO()
sftp.getfo('./data/kommunalvalg-134-18-11-2025/geografi/Opstillingskreds-111120250750.json', buf)
data = json.loads(buf.getvalue())
print(json.dumps(data[0], indent=2, ensure_ascii=False))
sftp.close(); ssh.close()
"
```

Adjust `ok["KommuneKode"]` in `transform_geography_files` and lookups in `prepare_kv2025.py` if needed.

- [ ] **Step 4: Check Afstemningsomraade geografi file for field names**

```bash
.venv/bin/python -c "
from valg.fetcher import get_sftp_client
import json, io
ssh, sftp = get_sftp_client()
buf = io.BytesIO()
sftp.getfo('./data/kommunalvalg-134-18-11-2025/geografi/Afstemningsomraade-111120250750.json', buf)
data = json.loads(buf.getvalue())
print(json.dumps(data[0], indent=2, ensure_ascii=False))
sftp.close(); ssh.close()
"
```

Adjust field names (`OpstillingskredsKode`, `StemmeberettigeteVaelgere`, `Dagi_id`) in `kv2025_transform.py` if needed, then re-run tests.

- [ ] **Step 5: Check kandidat-data file for Kandidatlister structure and kommune name format**

```bash
.venv/bin/python -c "
from valg.fetcher import get_sftp_client
import json, io
ssh, sftp = get_sftp_client()
buf = io.BytesIO()
sftp.getfo('./data/kommunalvalg-134-18-11-2025/kandidat-data/kandidat-data-Kommunalvalg-Aabenraa-061020251110.json', buf)
data = json.loads(buf.getvalue())
# Print top-level keys and first kandidatliste if present
print('Top-level keys:', list(data.keys()))
print('Kommune value:', data.get('Kommune'))  # check this matches geografi Navn
if 'Kandidatlister' in data:
    print(json.dumps(data['Kandidatlister'][0], indent=2, ensure_ascii=False)[:600])
sftp.close(); ssh.close()
"
```

Verify that `data['Kommune']` (e.g. `"Aabenraa"`) matches the corresponding `Navn` in the geografi `Kommune-*.json` file. If the formats differ (e.g. `"Aabenraa Kommune"` vs `"Aabenraa"`), adjust the lookup in `prepare_kv2025.py` at the line `k["Navn"] == kommune_name`. Adjust `kd.get('Kandidatlister', [])` and candidate field names if needed. Re-run `pytest tests/test_kv2025_transform.py` after any field-name changes to confirm tests still pass.

- [ ] **Step 5b: Check valgdeltagelse file for AO ID field name**

```bash
.venv/bin/python -c "
from valg.fetcher import get_sftp_client
import json, io
ssh, sftp = get_sftp_client()
buf = io.BytesIO()
sftp.getfo('./data/kommunalvalg-134-18-11-2025/valgdeltagelse/valgdeltagelse-Kommunalvalg-Aabenraa_Kommune-Aabenraa_Midt-181120251917.json', buf)
data = json.loads(buf.getvalue())
print('Top-level keys:', list(data.keys()))
print('AO ID key present:', 'AfstemningsområdeDagiId' in data, 'AfstemningsomraadeDagiId' in data)
sftp.close(); ssh.close()
"
```

Verify the exact key used for the AO ID. The script uses `"AfstemningsområdeDagiId"` (with ø). If the actual field name differs, update the `ao_turnout` keying in `prepare_kv2025.py` and re-run `pytest tests/test_kv2025_transform.py`.

- [ ] **Step 6: Run the preparation script**

```bash
cd /Users/madsschmidt/Documents/valg
.venv/bin/python -m valg.scenarios.prepare_kv2025
```

Expected: INFO log lines showing download progress, then wave creation. Final line: `Done. Wrote N waves to .../valg/scenarios/kv2025`

- [ ] **Step 7: Verify output structure**

```bash
ls valg/scenarios/kv2025/ | head -25
ls valg/scenarios/kv2025/wave_00/
ls valg/scenarios/kv2025/wave_01/valgresultater/ | wc -l
cat valg/scenarios/kv2025/wave_01/_meta.json
```

Expected:
- wave_00 through wave_NN directories present
- wave_00 has `Storkreds.json`, `geografi/`, `kandidat-data/`
- wave_01 has `valgresultater/` with small-AO result files
- `_meta.json` has label, interval_s, phase fields

- [ ] **Step 8: Run all existing tests to check nothing is broken**

```bash
pytest tests/ -v --ignore=tests/e2e
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add valg/scenarios/prepare_kv2025.py valg/scenarios/kv2025/
git commit -m "feat(kv2025): add preparation script and pre-baked wave bundles"
```

---

## Chunk 4: KV2025 scenario + registration

### Task 5: Write `kv2025.py` scenario and register it

**Prerequisite:** Chunk 3 (Task 4) must be completed first — `valg/scenarios/kv2025/` must exist with at least `wave_00/` present. The registration in `demo.py` uses `try/except` so the import won't crash if wave data is missing, but `test_kv2025_scenario_registered` and `test_kv2025_scenario_has_steps_factory` will fail until the wave data exists.

**Files:**
- Create: `valg/scenarios/kv2025.py`
- Modify: `valg/demo.py`
- Create: `tests/test_kv2025_scenario.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_kv2025_scenario.py`:

```python
"""Tests for KV2025 scenario step generation."""
import json
import pytest
from pathlib import Path


def test_make_steps_reads_meta(tmp_path):
    """make_steps returns one Step per wave_NN directory, in order."""
    from valg.demo import Step

    # Create fake wave dirs with _meta.json
    for i, (label, interval, phase) in enumerate([
        ("Setup", 0.0, "setup"),
        ("Prelim batch 1", 90.0, "preliminary"),
        ("Fintælling batch 1", 75.0, "final"),
    ]):
        wave_dir = tmp_path / f"wave_{i:02d}"
        wave_dir.mkdir()
        (wave_dir / "_meta.json").write_text(
            json.dumps({"label": label, "interval_s": interval, "phase": phase})
        )

    from valg.scenarios.kv2025 import make_steps
    steps = make_steps(tmp_path, data_repo=Path("/irrelevant"))

    assert len(steps) == 3
    assert steps[0].name == "Setup"
    assert steps[0].base_interval_s == 0.0
    assert steps[0].setup is True
    assert steps[0].write_fn is not None
    assert steps[1].name == "Prelim batch 1"
    assert steps[1].base_interval_s == 90.0
    assert steps[1].setup is False
    assert steps[2].base_interval_s == 75.0


def test_make_steps_write_fn_copies_files(tmp_path):
    """write_fn copies wave files into valg-data/demo/kv2025/ with correct structure."""
    wave_dir = tmp_path / "waves" / "wave_01"
    vr_dir = wave_dir / "valgresultater"
    vr_dir.mkdir(parents=True)
    (wave_dir / "_meta.json").write_text(
        json.dumps({"label": "Test wave", "interval_s": 60.0, "phase": "preliminary"})
    )
    (vr_dir / "valgresultater-Folketingsvalg-123.json").write_text('{"test": true}')

    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()

    from valg.scenarios.kv2025 import make_steps
    steps = make_steps(tmp_path / "waves", data_repo=data_repo)
    # Call the write_fn for wave_01
    written = steps[0].write_fn(data_repo)

    dest = data_repo / "demo" / "kv2025" / "valgresultater" / "valgresultater-Folketingsvalg-123.json"
    assert dest.exists()
    assert len(written) == 1
    assert written[0] == dest


def test_kv2025_scenario_registered():
    """KV2025 scenario appears in SCENARIOS dict."""
    from valg.demo import SCENARIOS
    assert "KV2025" in SCENARIOS


def test_kv2025_scenario_has_steps_factory():
    """KV2025 scenario uses steps_factory, not static steps."""
    from valg.demo import SCENARIOS
    scenario = SCENARIOS["KV2025"]
    assert scenario.steps_factory is not None
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
pytest tests/test_kv2025_scenario.py -v
```

Expected: `ModuleNotFoundError: No module named 'valg.scenarios.kv2025'`

- [ ] **Step 3: Create `valg/scenarios/kv2025.py`**

```python
"""
KV2025 demo scenario: replay kommunalvalg 2025 results as a FV-style election night.

Pre-baked wave bundles live in valg/scenarios/kv2025/wave_NN/.
Each wave's files are copied into valg-data/demo/kv2025/ at runtime.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from valg.demo import Scenario, Step

_WAVE_DIR = Path(__file__).parent / "kv2025"
_DEST_SUBPATH = Path("demo") / "kv2025"


def _copy_wave(wave_dir: Path, data_repo: Path) -> list[Path]:
    """Copy all non-meta files from wave_dir into data_repo/demo/kv2025/."""
    dest_base = data_repo / _DEST_SUBPATH
    written: list[Path] = []
    for src in wave_dir.rglob("*"):
        if src.is_dir() or src.name == "_meta.json":
            continue
        relative = src.relative_to(wave_dir)
        dest = dest_base / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(dest)
    return written


def make_steps(wave_dir: Path, data_repo: Path) -> list[Step]:
    """Build Step list from pre-baked wave directories."""
    wave_dirs = sorted(wave_dir.glob("wave_*"))
    steps = []
    for wd in wave_dirs:
        meta_path = wd / "_meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        steps.append(Step(
            name=meta["label"],
            wave=None,
            setup=meta.get("phase") == "setup",
            process=True,
            commit=True,
            base_interval_s=float(meta["interval_s"]),
            write_fn=lambda d, src=wd: _copy_wave(src, d),
        ))
    return steps


KV2025_SCENARIO = Scenario(
    name="KV2025",
    description="Rigtige stemmeresultater fra kommunalvalget 18. november 2025, afspillet som valgaften.",
    steps=[],
    steps_factory=lambda data_repo: make_steps(_WAVE_DIR, data_repo),
)
```

- [ ] **Step 4: Register scenario in `valg/demo.py`**

At the top of `valg/demo.py` after the `SCENARIOS` dict definition, add:

```python
# Register additional scenarios
try:
    from valg.scenarios.kv2025 import KV2025_SCENARIO
    SCENARIOS["KV2025"] = KV2025_SCENARIO
except Exception:
    pass  # wave data not generated yet — scenario unavailable
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
pytest tests/test_kv2025_scenario.py -v
```

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v --ignore=tests/e2e
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add valg/scenarios/kv2025.py valg/demo.py tests/test_kv2025_scenario.py
git commit -m "feat(kv2025): add KV2025 scenario and register in demo mode"
```

---

### Task 6: End-to-end smoke test

**Files:**
- No new files — manual verification

- [ ] **Step 1: Start demo server on feature/demo-mode with KV2025 scenario**

```bash
.venv/bin/python -m valg.server --demo --db /tmp/valg-kv2025-test.db
```

(Assumes `server.py` on `feature/demo-mode` supports `--demo`. If `__main__.py` is the entry point, use that instead.)

- [ ] **Step 2: Open browser, select KV2025 scenario**

Navigate to `http://localhost:5000`. In the demo control strip:
- Scenario picker should show "KV2025 — Kommunalvalg 18. november 2025"
- Select it, click Start

- [ ] **Step 3: Verify wave 00 runs correctly**

In the browser, click Status after wave_00 completes. Expected: geography loaded, no results yet.

- [ ] **Step 4: Set speed to 60× and run to completion**

Click `60×`, then Start. Let it run to done. Expected:
- Status shows seat projections with real KV2025 party distribution
- Flip shows seat-flip candidates based on real vote margins
- No errors in server logs

- [ ] **Step 5: Final commit**

```bash
git add valg/scenarios/kv2025.py valg/scenarios/prepare_kv2025.py valg/demo.py tests/
git commit -m "feat(kv2025): verified end-to-end KV2025 demo scenario"
```
