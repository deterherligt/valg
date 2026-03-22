"""
FV2022 demo scenario: replay Folketing election 2022 results as election night.

Pre-baked wave bundles live in valg/scenarios/fv2022/wave_NN/.
Each wave's files are copied into valg-data/demo/fv2022/ at runtime.

Geography and candidates are from FV2026 (latest available).
Vote results are real FV2022 data from the valg.dk public API.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from valg.demo import Scenario, Step

_WAVE_DIR = Path(__file__).parent / "fv2022"
_DEST_SUBPATH = Path("demo") / "fv2022"


def _copy_wave(wave_dir: Path, data_repo: Path) -> list[Path]:
    """Copy all non-meta files from wave_dir into data_repo/demo/fv2022/."""
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
    steps = []
    for wd in sorted(wave_dir.glob("wave_*")):
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


FV2022_SCENARIO = Scenario(
    name="FV2022 — Folketing 1. november 2022",
    description="Rigtige stemmeresultater fra Folketingsvalget 2022, afspillet som valgaften.",
    steps=[],
    steps_factory=lambda data_repo: make_steps(_WAVE_DIR, data_repo),
    output_dir=_DEST_SUBPATH,
)
