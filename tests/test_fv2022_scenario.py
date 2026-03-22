"""Tests for FV2022 scenario module."""
import json
import pytest
from pathlib import Path


def test_make_steps_reads_meta(tmp_path):
    """make_steps returns one Step per wave_NN dir, with correct fields."""
    for i, (label, interval, phase) in enumerate([
        ("20:00 — Opstilling & geografi", 0.0, "setup"),
        ("21:03 — Bornholm, Laesoe, Aeroe", 45.0, "preliminary"),
        ("00:22 — Fintaelling batch 6", 60.0, "final"),
    ]):
        wd = tmp_path / f"wave_{i:02d}"
        wd.mkdir()
        (wd / "_meta.json").write_text(
            json.dumps({"label": label, "time": label[:5], "interval_s": interval, "phase": phase})
        )

    from valg.scenarios.fv2022 import make_steps
    steps = make_steps(tmp_path, data_repo=Path("/irrelevant"))

    assert len(steps) == 3
    assert steps[0].name == "20:00 — Opstilling & geografi"
    assert steps[0].setup is True
    assert steps[0].base_interval_s == 0.0
    assert steps[0].write_fn is not None
    assert steps[1].setup is False
    assert steps[1].base_interval_s == 45.0
    assert steps[2].base_interval_s == 60.0


def test_make_steps_write_fn_copies_files(tmp_path):
    """write_fn copies files into data_repo/demo/fv2022/ preserving subdir structure."""
    wave_dir = tmp_path / "waves" / "wave_01"
    pf_dir = wave_dir / "partistemmefordeling"
    pf_dir.mkdir(parents=True)
    (wave_dir / "_meta.json").write_text(
        json.dumps({"label": "21:03 — test", "time": "21:03", "interval_s": 45.0, "phase": "preliminary"})
    )
    (pf_dir / "partistemmefordeling-123.json").write_text('{"Valg": {}}')

    data_repo = tmp_path / "data_repo"
    data_repo.mkdir()

    from valg.scenarios.fv2022 import make_steps
    steps = make_steps(tmp_path / "waves", data_repo=data_repo)
    written = steps[0].write_fn(data_repo)

    dest = data_repo / "demo" / "fv2022" / "partistemmefordeling" / "partistemmefordeling-123.json"
    assert dest.exists()
    assert len(written) == 1
    assert written[0] == dest


def test_make_steps_skips_meta_json(tmp_path):
    """_meta.json is not included in written files."""
    wave_dir = tmp_path / "wave_01"
    wave_dir.mkdir()
    (wave_dir / "_meta.json").write_text(
        json.dumps({"label": "test", "time": "21:00", "interval_s": 30.0, "phase": "preliminary"})
    )
    (wave_dir / "Parti-FV2022.json").write_text("[]")

    data_repo = tmp_path / "data"
    data_repo.mkdir()

    from valg.scenarios.fv2022 import make_steps
    steps = make_steps(tmp_path, data_repo=data_repo)
    written = steps[0].write_fn(data_repo)

    names = [p.name for p in written]
    assert "_meta.json" not in names
    assert "Parti-FV2022.json" in names


def test_fv2022_scenario_registered():
    """FV2022 scenario appears in SCENARIOS dict when wave data exists."""
    wave_dir = Path(__file__).parent.parent / "valg" / "scenarios" / "fv2022"
    if not wave_dir.exists():
        pytest.skip("fv2022 wave data not built yet")
    from valg.demo import SCENARIOS
    assert "fv2022" in SCENARIOS


def test_fv2022_scenario_has_output_dir():
    """FV2022 scenario declares output_dir for restart cleanup."""
    wave_dir = Path(__file__).parent.parent / "valg" / "scenarios" / "fv2022"
    if not wave_dir.exists():
        pytest.skip("fv2022 wave data not built yet")
    from valg.demo import SCENARIOS
    scenario = SCENARIOS["fv2022"]
    assert scenario.output_dir == Path("demo") / "fv2022"
