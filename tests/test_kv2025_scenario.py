"""Tests for KV2025 scenario step generation."""
import json
import pytest
from pathlib import Path


def test_make_steps_reads_meta(tmp_path):
    """make_steps returns one Step per wave_NN directory, in order."""
    from valg.demo import Step

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
    written = steps[0].write_fn(data_repo)

    dest = data_repo / "demo" / "kv2025" / "valgresultater" / "valgresultater-Folketingsvalg-123.json"
    assert dest.exists()
    assert len(written) == 1
    assert written[0] == dest


def test_kv2025_scenario_registered():
    """KV2025 scenario appears in SCENARIOS dict."""
    from valg.demo import SCENARIOS
    assert "kv2025" in SCENARIOS


def test_kv2025_scenario_has_steps_factory():
    """KV2025 scenario uses steps_factory, not static steps."""
    from valg.demo import SCENARIOS
    scenario = SCENARIOS["kv2025"]
    assert scenario.steps_factory is not None
