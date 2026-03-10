# valg

Unofficial real-time tracker for Danish Folketing election results.

Fills the gap valg.dk misses: candidate/party drilldowns and seat-flip margins.

> See DISCLAIMER.md. This is not an official source. Always refer to valg.dk.

## Download (no Python required)

Go to [Releases](https://github.com/deterherligt/valg/releases) and download:
- **macOS:** `valg-macos.zip` — unzip, then right-click → Open on first run (Gatekeeper)
- **Windows:** `valg-windows.exe` — click "More info → Run anyway" on first run (SmartScreen)

Double-click to start. Your browser opens automatically at `http://localhost:5000`.
Data syncs from the public [valg-data](https://github.com/deterherligt/valg-data) repo every 60 seconds.

## Setup

    pip install -e ".[dev]"
    cp .env.example .env   # credentials are public defaults — override if needed

    # Initialise the data repo
    mkdir -p ../valg-data && cd ../valg-data && git init && cd -

## Election night

    # Option A: GitHub Actions (no server needed)
    # Fork this repo, set DATA_REPO and ELECTION_FOLDER variables — done.

    # Option B: run locally
    python -m valg sync --election-folder /Folketingsvalg-1-2024 --interval 300

    # Query results
    python -m valg status
    python -m valg flip
    python -m valg party A
    python -m valg feed

## Fintælling (next day)

    python -m valg kreds "Østerbro"
    python -m valg candidate "Mette Frederiksen"

## AI commentary (optional)

Set `VALG_AI_API_KEY` and `VALG_AI_BASE_URL` in `.env`. Any OpenAI-compatible endpoint works.

    python -m valg commentary

## Demo mode

Run a simulated election night without a live SFTP connection:

    python -m valg.server --demo

The browser UI gains a demo control strip: pick a scenario, hit Start, adjust speed (1×–60×), pause, or restart.

### Adding a new scenario

Scenarios live in `valg/demo.py` in the `SCENARIOS` dict. Each scenario is a `Scenario` with a list of `Step` objects.

**Step fields:**

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | `str` | required | Display label shown in the UI |
| `wave` | `int \| None` | required | Which synthetic data wave to write (see `fake_fetcher.write_wave`) |
| `setup` | `bool` | `False` | Call `setup_db` (load geography + candidates) — use for the first step only |
| `process` | `bool` | `True` | Run `process_raw_file` on the written files (populates SQLite) |
| `commit` | `bool` | `True` | Git-commit the wave files to the data repo |
| `base_interval_s` | `float` | `60.0` | Seconds to wait after this step (divided by current speed multiplier) |

**Wave numbering** (from `fake_fetcher.write_wave`):
- Wave 0 — geography + candidate files only (no vote data)
- Wave 1 — 25% foreløbig (preliminary) vote data
- Wave 2 — 50% foreløbig
- Wave 3 — 100% foreløbig
- Wave 4 — 50% fintælling (final count)
- Wave 5 — 100% fintælling

**Example — a quick two-wave demo:**

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

Register it in `SCENARIOS` and it appears immediately in the UI scenario picker.

## Adding a new file format

Drop a file in valg/plugins/:

    TABLE = "results"
    def MATCH(filename): return "my-pattern" in filename.lower()
    def parse(data, snapshot_at): return [...]  # list of row dicts

No other changes needed.

## Data source

Election data: data.valg.dk (Netcompany / Indenrigsministeriet).
Documented at: valg/api-doc/

## License

Beerware — see LICENSE.
