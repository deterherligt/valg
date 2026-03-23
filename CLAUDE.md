# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_calculator.py

# Run a single test
pytest tests/test_calculator.py::test_dhondt_proportional_three_to_one

# Run CLI
python -m valg [--db PATH] <command>
valg [--db PATH] <command>   # if installed

# One-shot sync
python -m valg sync --election-folder /Folketingsvalg-1-2024

# Continuous sync loop (5-min interval)
python -m valg sync --election-folder /Folketingsvalg-1-2024 --interval 300
```

## Architecture

Two repos:
- `valg/` — this code repo
- `valg-data/` — sibling data repo at `../valg-data` (default). Raw JSON files, auto-committed after each sync. Referenced via `VALG_DATA_REPO` env var.

Data pipeline:

```
SFTP (data.valg.dk:22)
  → fetcher.py        mtime-diff download, git commit/push in valg-data/
  → processor.py      JSON → SQLite dispatch via plugin registry
  → valg.db           SQLite, WAL mode, snapshotted rows with snapshot_at timestamps
  → calculator.py     Pure functions: D'Hondt kredsmandater, Hare §77, Sainte-Laguë §78, Danish method §79
  → cli.py            Rich tables, argparse dispatch
```

### Key modules

- `valg/fetcher.py` — SFTP connect (`get_sftp_client`), mtime-based sync (`sync_election_folder`), git commit/push helpers
- `valg/processor.py` — `process_raw_file` / `process_directory`: find plugin → parse → `_insert_rows` with upsert logic. Anomalies logged to `anomalies` table, never raised.
- `valg/calculator.py` — pure functions, no I/O. `dhondt`, `hare_largest_remainder`, `allocate_kredsmandater_detail`, `allocate_tillaeg_to_landsdele`, `allocate_tillaeg_to_storkredse`, `allocate_seats_detail`, `project_storkreds_votes`, `votes_to_gain_seat`, `votes_to_lose_seat`, `constituency_flip_feasibility`, `seat_momentum`
- `valg/models.py` — schema + indexes, `get_connection`, `init_db`. `DB_PATH` defaults to repo root `valg.db`
- `valg/cli.py` — `build_parser` + dispatch dict. `cmd_sync` runs one cycle (no loop); loop is in `fetcher.run_sync_loop`
- `valg/ai.py` — model-agnostic AI commentary; disabled gracefully if `VALG_AI_API_KEY` unset
- `valg/plugins/` — hot-pluggable file parsers, auto-discovered at startup via `importlib`

### Plugin interface

Each file in `valg/plugins/` must export:
- `MATCH(filename: str) -> bool` — returns True if this plugin handles the file
- `parse(data: dict | list, snapshot_at: str) -> list[dict]` — returns normalized rows
- `TABLE: str` — target SQLite table name

Unknown files are logged to `anomalies` and skipped — no crash.

### SQLite schema notes

- Reference tables (`storkredse`, `opstillingskredse`, `afstemningsomraader`, `parties`, `candidates`) use `INSERT OR REPLACE` (upsert by natural key)
- Snapshot tables (`results`, `turnout`, `party_votes`) use `INSERT OR IGNORE` (immutable snapshots keyed by entity + `snapshot_at`)
- `count_type`: `'preliminary'` (election night) or `'final'` (fintælling)
- `party_votes` table (from `Partistemmefordeling/`) is the primary input for national seat calculations; `results` candidate rows only arrive with fintælling

### Seat calculation

- **Kredsmandater (135):** D'Hondt per storkreds (§76). Accurate.
- **National allocation (175):** Hare quota + largest remainder (§77) with overhang handling.
- **Tillægsmandater to landsdele (40):** Sainte-Laguë with exclusions (§78).
- **Tillægsmandater to storkredse:** Danish method 1-4-7-10 with exclusions (§79).
- **Projection:** Per-storkreds vote scaling based on reporting progress.
- Threshold: ≥2% nationally OR ≥1 kredsmandat

## Environment

Copy `.env.example` to `.env`. Key vars:

```
VALG_SFTP_HOST=data.valg.dk     # public SFTP, credentials are publicly documented
VALG_SFTP_USER=Valg
VALG_SFTP_PASSWORD=Valg
VALG_DATA_REPO=../valg-data
VALG_AI_BASE_URL=...            # optional, any OpenAI-compatible endpoint
VALG_AI_API_KEY=...
VALG_AI_MODEL=claude-sonnet-4-6
```

## Design doc

Full architecture, use cases, SQLite schema, performance targets, GitHub Actions setup, and v1/v2 scope are in `docs/plans/2026-03-07-election-dashboard-design.md`. Read it before making architectural decisions.
