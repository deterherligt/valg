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
    name="KV2025 — Kommunalvalg 18. november 2025",
    description="Rigtige stemmeresultater fra kommunalvalget 18. november 2025, afspillet som valgaften.",
    steps=[],
    steps_factory=lambda data_repo: make_steps(_WAVE_DIR, data_repo),
    output_dir=Path("demo") / "kv2025",
)
