# valg

Real-time web dashboard for Danish Folketing election results.

Tracks what valg.dk doesn't: candidate and party drilldowns, seat-flip margins, and constituency-level breakdowns — updating live as districts report.

**Live:** https://valgdashboard.osc-fr1.scalingo.io/

> See DISCLAIMER.md. This is not an official source. Always refer to valg.dk.

## What it does

- **National overview** — party vote totals, projected seats (D'Hondt kredsmandater + approximate Saint-Laguë tillægsmandater), reporting progress
- **Seat-flip margins** — how many votes each party needs to gain or lose a seat
- **Party drilldown** — vote breakdown per storkreds, seat allocation, momentum since last sync
- **Candidate tracking** — individual vote counts, rank within party (fintælling phase)
- **Constituency drilldown** — district-level results, flip feasibility for contested seats
- **Live event feed** — seat flips, momentum shifts, district completions as they happen
- **AI commentary** — optional model-agnostic analysis (any OpenAI-compatible endpoint)
- **Demo mode** — simulated election night with scenario picker, speed control (1x-60x), pause/resume

## Download (no Python required)

Go to [Releases](https://github.com/deterherligt/valg/releases) and download:
- **macOS:** `valg-macos.zip` — unzip, right-click → Open on first run (Gatekeeper)
- **Windows:** `valg-windows.exe` — click "More info → Run anyway" on first run (SmartScreen)

Double-click to start. Your browser opens at `http://localhost:5000`.

## Development setup

```bash
pip install -e ".[dev]"
cp .env.example .env
```

### Run the web dashboard

```bash
python -m valg.server          # http://localhost:5000
python -m valg.server --demo   # demo mode with simulated election data
```

### Run the CLI

```bash
python -m valg status
python -m valg flip
python -m valg party A
python -m valg candidate "Mette Frederiksen"
python -m valg kreds "Østerbro"
python -m valg feed
python -m valg commentary       # requires VALG_AI_API_KEY
```

### Sync data

```bash
# One-shot sync from SFTP
python -m valg sync --election-folder /Folketingsvalg-1-2024

# Continuous sync loop
python -m valg sync --election-folder /Folketingsvalg-1-2024 --interval 300
```

The dashboard also syncs automatically from the public [valg-data](https://github.com/deterherligt/valg-data) GitHub repo via HTTP polling.

## Architecture

```
data.valg.dk (SFTP) or valg-data GitHub repo (HTTP)
       |
       v
  [ Fetcher ]        mtime-diff sync, git commit in valg-data/
       |
       v
  [ Processor ]      plugin-based JSON parsing → SQLite
       |
       v
  [ valg.db ]        SQLite (WAL mode), snapshotted rows
       |
       v
  [ Calculator ]     D'Hondt + Saint-Laguë seat allocation, flip margins
       |
       v
  [ Server / CLI ]   Flask web dashboard or Rich CLI tables
```

Two repos:
- **valg/** — this code repo
- **valg-data/** — raw JSON election data, auto-committed after each sync cycle

## Demo mode

The web UI includes a demo control bar: pick a scenario, adjust speed, pause/resume, restart. Scenarios are defined in `valg/demo.py` as `Scenario` objects with `Step` lists.

### Adding a scenario

```python
SCENARIOS["Quick Demo"] = Scenario(
    name="Quick Demo",
    description="Setup + one preliminary wave only.",
    steps=[
        Step(name="Setup", wave=0, setup=True, process=False, commit=True, base_interval_s=0),
        Step(name="100% foreløbig", wave=3, base_interval_s=30.0),
    ],
)
```

Register it in `SCENARIOS` and it appears in the UI picker.

## Adding a new file format

Drop a file in `valg/plugins/`:

```python
TABLE = "results"
def MATCH(filename): return "my-pattern" in filename.lower()
def parse(data, snapshot_at): return [...]  # list of row dicts
```

No other changes needed. Plugins are auto-discovered at startup.

## Deployment

Deployed on Scalingo (FR region). Data syncs via GitHub HTTP polling — no SFTP access needed in production.

```
Procfile: web: python -m valg.server
```

Key env vars:
- `PORT` — set by Scalingo automatically
- `VALG_ADMIN_TOKEN` — controls demo API access (`POST /admin/demo`)
- `VALG_DATA_REPO` — path to data repo (default: `../valg-data`)

## Environment

Copy `.env.example` to `.env`. Key variables:

```
VALG_SFTP_HOST=data.valg.dk
VALG_SFTP_USER=Valg
VALG_SFTP_PASSWORD=Valg
VALG_DATA_REPO=../valg-data
VALG_AI_BASE_URL=...            # optional, any OpenAI-compatible endpoint
VALG_AI_API_KEY=...
VALG_AI_MODEL=claude-sonnet-4-6
VALG_ADMIN_TOKEN=...            # optional, for demo API
```

## Data source

Election data from data.valg.dk (Netcompany / Indenrigsministeriet). API docs in `valg/api-doc/`.

## License

Beerware — see LICENSE.
