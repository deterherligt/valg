#!/usr/bin/env python3
"""
Firedrill: simulates a complete election night using synthetic data.

Usage:
    python scripts/firedrill.py                  # runs all 6 waves
    python scripts/firedrill.py --wave 0 1 2     # specific waves only
    python scripts/firedrill.py --pause          # pause between waves
    python scripts/firedrill.py --db /tmp/my.db  # custom DB path
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
DB_DEFAULT = Path(tempfile.gettempdir()) / "valg-firedrill.db"
DATA_DIR = Path(tempfile.gettempdir()) / "valg-firedrill-data"

WAVE_LABELS = {
    0: "Wave 0 — Setup (geography, parties, candidates)",
    1: "Wave 1 — 25% districts reporting (preliminary)",
    2: "Wave 2 — 50% districts reporting (preliminary)",
    3: "Wave 3 — 100% districts reporting (preliminary)",
    4: "Wave 4 — 50% districts fintælling",
    5: "Wave 5 — 100% districts fintælling",
}

COMMANDS_AFTER_WAVE = {
    0: [],
    1: ["status", "flip"],
    2: ["status", "flip"],
    3: ["status", "flip", "party A"],
    4: ["status", "candidate Kandidat"],
    5: ["status", "flip", "feed"],
}


def run(cmd: list[str], db: Path) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "valg", "--db", str(db)] + cmd,
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return result.stdout + result.stderr


def run_wave(wave: int, db: Path) -> None:
    print(f"\n{'='*60}")
    print(f"  {WAVE_LABELS[wave]}")
    print(f"{'='*60}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "valg", "--db", str(db),
         "sync", "--fake", "--wave", str(wave),
         "--data-dir", str(DATA_DIR)],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.returncode != 0:
        print(f"ERROR in sync: {result.stderr}")
        return
    print(result.stdout.strip())

    for cmd_str in COMMANDS_AFTER_WAVE.get(wave, []):
        print(f"\n--- valg {cmd_str} ---")
        print(run(cmd_str.split(), db))


def main():
    p = argparse.ArgumentParser(description="valg firedrill")
    p.add_argument("--wave", type=int, nargs="+", default=list(range(6)),
                   help="Which waves to run (default: 0-5)")
    p.add_argument("--pause", action="store_true",
                   help="Pause between waves for manual inspection")
    p.add_argument("--db", type=Path, default=DB_DEFAULT,
                   help=f"DB path (default: {DB_DEFAULT})")
    p.add_argument("--fresh", action="store_true",
                   help="Delete DB before starting")
    args = p.parse_args()

    if args.fresh and args.db.exists():
        args.db.unlink()
        print(f"Deleted {args.db}")

    print(f"Firedrill DB: {args.db}")
    print(f"Data dir:     {DATA_DIR}")

    for wave in sorted(args.wave):
        run_wave(wave, args.db)
        if args.pause and wave < max(args.wave):
            input("\nPress Enter for next wave...")

    print(f"\n{'='*60}")
    print("  Firedrill complete.")
    print(f"  DB: {args.db}")
    print(f"  Run: python -m valg --db {args.db} status")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
