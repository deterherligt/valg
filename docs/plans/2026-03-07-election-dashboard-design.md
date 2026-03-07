# Valg Election Dashboard — Design Document

**Date:** 2026-03-07
**Scope:** Folketingsvalg (Danish parliamentary elections)
**Status:** Approved

---

## Problem

valg.dk and other sites cover the macro picture (national totals, bloc majorities) adequately.
What is missing is:

1. Real-time tracking of a specific candidate or party's vote count as districts report
2. Seat-flip margins — how many votes a party needs to gain or lose a seat
3. Constituency-level drilldown showing which districts have reported and what votes remain

---

## Use Cases

## Counting Phases

Understanding which data is available at which time is critical to the tool's design.

| Phase | When | Data available | What we can compute |
|---|---|---|---|
| **Foreløbig optælling** | Election night | Party votes per polling district | Party totals, seat projections, seat-flip margins, storkreds breakdown |
| **Fintælling** | Next day(s) | Candidate votes per polling district | Everything above + candidate rankings, constituency flip feasibility, party list "who's in" |

**Important nuances:**
- Party votes from the foreløbig optælling are the primary input for seat projection — candidate votes do not add information about total party seats
- Some party votes are counted incorrectly on election night and corrected during fintælling — party totals may shift slightly
- Candidate votes sum to party votes within a district, but candidate-level data only arrives with fintælling

The tool must be useful during both phases. Use cases are tagged accordingly.

### Graceful degradation

The tool never crashes or blocks on missing data. When data is incomplete or unavailable:

- **Missing party votes**: display `unknown` rather than zero or an error
- **Missing candidate votes**: display `unknown`, do not gate the command entirely — show what is known and mark the rest as pending
- **Partial fintælling**: if only some districts have candidate-level data, show those and mark others as `pending`
- **Election night → fintælling transition**: as fintælling data arrives district by district, the tool blends preliminary party totals with emerging final candidate data — no manual intervention required
- **No results yet**: all commands run and display a clear "no data yet" state rather than an error

The principle: **always show what is known, clearly label what is not**.

---

### Election Night (foreløbig optælling — party votes only)

#### UC1: Party seats and flip margins
> "Which parties are gaining/losing seats as districts report in?"

- Input: none
- Output: live party vote totals, projected seats, votes needed to gain/lose a seat nationally, momentum (votes gained since last sync)

#### UC2: Storkreds breakdown
> "How is each storkreds contributing to the overall picture?"

- Input: none or storkreds name
- Output: party votes per storkreds, projected kredsmandater, districts reported vs total

#### UC3: Seat flip margins per party
> "How many votes does Socialdemokratiet need to gain or lose to change their seat count?"

- Input: party letter
- Output: `+N votes to gain seat`, `-M votes to lose seat`, current projected seats, vote momentum

### Fintælling (candidate votes available — typically next day)

#### UC4: Constituency flip feasibility
> "Can candidate X still overtake candidate Y in Østerbro, given uncounted districts?"

- Input: opstillingskreds name
- Output: ranked list of candidates by current votes (with names and party), gap between each challenger and the leader, max votes still possible from uncounted districts, feasibility flag per challenger

#### UC5: Party list rankings
> "Within Socialdemokratiet, who is currently getting elected, and what are the margins between candidates?"

- Input: party letter
- Output: ranked list of all party candidates by current votes, margin between each adjacent pair, how many seats the party is projected to win (shows who is "in", "on the bubble", "out")

#### UC6: Candidate tracking
> "How is Mette Frederiksen doing across all opstillingskredse in her storkreds?"

- Input: candidate name
- Output: current vote total, votes gained since last snapshot, rank within party

### General

#### UC7: Replay and verification
> "After election night, verify that the seat-flip signals were correct at each sync point."

- Input: a past commit in the data repo
- Output: re-run the processor and calculator against that snapshot, compare to final results

#### UC8: Share live data with others
> "Push the data repo so a colleague can follow the same live feed from another machine."

- Input: push data repo to private remote
- Output: colleague pulls and queries locally, or a server processes and serves results

---

## Architecture

```
data.valg.dk (SFTP)
       |
       v
  [ Fetcher ]          polls every N minutes, downloads new/changed JSON files
       |                mirrors raw files to: valg-data/ (separate git repo)
       |                auto-commits after each sync cycle
       v
  [ Processor ]        parses JSON, normalizes into SQLite
       |                runs after each fetch cycle
       v
  [ valg.db ]          single SQLite file, queryable anytime
       |
       v
  [ Calculator ]       Saint-Lague seat allocation, "votes to flip" logic
       |                pure functions, no I/O
       v
  [ CLI ]              initial display layer; TUI or web added later
```

Key principles:
- Raw JSON files live in a **separate git repo** (`valg-data/`) — auto-committed each sync cycle, pushable to a private remote for sharing and replay
- The SFTP server replaces files in place with no versioning — the data repo is the only historical record
- Results rows carry `snapshot_at` timestamps — enables momentum tracking (votes gained per sync cycle)
- Calculator layer is pure logic with no I/O — independently testable
- Display layer is thin and swappable

---

## Data Sources

Primary: SFTP at `data.valg.dk`, port 22, username/password: `Valg`

Possible secondary: HTTP download at valg.dk/data-eksport (unconfirmed — verify before relying on it)

Files consumed (Folketingsvalg focus):

| Dataset | Folder | Frequency |
|---|---|---|
| Geography | Geografi/ | Daily until day 14 |
| Candidate data | Kandidatdata/ | During campaign period |
| Voter turnout | Valgdeltagelse/ | Throughout election day |
| Election results | Valgresultater/ | Election evening + fintælling |
| Party vote distribution | Partistemmefordeling/ | Election evening |

---

## Raw Data Persistence

The SFTP server replaces files in place — there is no server-side versioning. Whatever the sync
machine captures at a given moment is the only record of that state.

### Approach: git + GitHub private repo

Raw JSON files are stored in a **dedicated git repo** (`valg-data/`) separate from the code repo.
After each sync cycle the fetcher commits locally and pushes to a private GitHub remote.

```bash
cd valg-data/
git add -A
git commit -m "sync 2024-11-05 21:34 UTC — 47 files updated"
git push origin main
```

**Why git is the right choice here:**
- Data is small (~20MB total across both counting phases) — well within GitHub free tier limits
- ~72 commits on election night (5-min interval) is unremarkable for git
- JSON is text — diffs are human-readable and genuinely useful for debugging
- History, sharing, and replay come for free with no additional infrastructure

**Hosting model:**
- The `valg-data/` git repo lives primarily on the **always-on server** — this is the source of truth
- GitHub is the **remote** — used for backup and sharing, not the primary store
- Colleagues clone from GitHub to replay locally or follow along
- If GitHub is unavailable on election night, the local repo keeps working unaffected; the push queue is flushed automatically when connectivity is restored (git will push all pending commits on the next successful push)

**Why not alternatives:**
- *Timestamped local copies* — simple but no history UI, no diffing, harder to share
- *Object storage (S3/R2)* — no size pressure here, adds boto3 dependency and per-request complexity for no real gain at this scale
- *PostgreSQL JSONB* — heavy setup for what is essentially structured file storage

### Hosting model

Both repos are **public on GitHub**. The data is intentionally public (government open data with published credentials), and a public data repo means anyone can access snapshots without needing SFTP access or running the tool.

```
GitHub Actions (scheduled cron, every 5 min on election night)
       |
       v
  SFTP fetch → git commit → git push
       |
       v
valg-data/  (public GitHub repo)   ← anyone can clone and replay
valg/       (public GitHub repo)   ← anyone can run the CLI
```

The sync can run as a **GitHub Actions workflow** (free for public repos, unlimited minutes) instead of a VPS. This eliminates the need for always-on infrastructure for most users. The VPS deployment (see Server Deployment section) remains available for those who want tighter timing control or a local fallback.

### Fallback behaviour

If the `git push` fails (network outage, GitHub unavailable), the fetcher:
1. Logs the failure but does not crash or retry indefinitely
2. Continues syncing from SFTP — local commits keep accumulating
3. On the next successful push, all pending commits are sent in one go

**GitHub going down on election night causes zero data loss** — the local repo holds everything. The only consequence is that colleagues cannot pull updates until connectivity is restored.

Estimated data repo size for one full election including fintælling (~80 sync cycles): **40-60MB**

---

## SQLite Schema

```sql
-- Core
elections (id, name, election_date, synced_at)

-- Geography
storkredse         (id, name, election_id)
opstillingskredse  (id, name, storkreds_id)
afstemningsomraader(id, name, opstillingskreds_id,
                    eligible_voters, municipality_name)

-- Candidates
parties    (id, letter, name, election_id)
candidates (id, name, party_id, opstillingskreds_id, ballot_position)

-- Results — all snapshotted with timestamp
results    (id, afstemningsomraade_id, party_id, candidate_id,
            votes, count_type, snapshot_at)
            -- count_type: 'preliminary' | 'final'

turnout    (id, afstemningsomraade_id, eligible_voters,
            votes_cast, snapshot_at)

party_votes(id, opstillingskreds_id, party_id,
            votes, snapshot_at)
            -- from partistemmefordeling, used for national seat calc

-- Indexes (critical for query performance with ~620K result rows)
CREATE INDEX idx_results_party_snapshot    ON results(party_id, snapshot_at);
CREATE INDEX idx_results_ao_snapshot       ON results(afstemningsomraade_id, snapshot_at);
CREATE INDEX idx_results_candidate_snap    ON results(candidate_id, snapshot_at);
CREATE INDEX idx_party_votes_party_snap    ON party_votes(party_id, snapshot_at);
CREATE INDEX idx_turnout_ao_snapshot       ON turnout(afstemningsomraade_id, snapshot_at);
```

`count_type` distinguishes preliminary counts (valgaftenen) from final (fintælling).
`eligible_voters` on `afstemningsomraader` is the basis for "votes still possible" projections.

---

## Seat Calculator

### National allocation

Danish Folketing seats split into two types:

**Kredsmandater (135 seats)** — straightforward. Each storkreds has a fixed number of seats.
Within each storkreds, seats are allocated to parties using D'Hondt based on votes in that storkreds.
Candidates receive kredsmandat seats based on their individual vote totals within their opstillingskreds.

**Tillægsmandater (40 seats)** — complex. Distributed nationally to correct for disproportionality
between vote share and kredsmandater won. Requires knowing all kredsmandater first, then computing
the gap between proportional entitlement and what was already won. This is deferred for v1.

**v1 approach:** Calculate kredsmandater per storkreds using D'Hondt (accurate), and
approximate tillægsmandater using national Saint-Laguë as a top-up (good enough for seat-flip
signalling). Full tillægsmandater calculation is a v2 improvement.

```
per storkreds: party_votes -> D'Hondt -> kredsmandater
national:      party_votes -> threshold filter -> Saint-Lague(175) - kredsmandater = approx_tillaeg
```

Threshold: party needs >= 2% nationally, OR 1 kredsmandat, OR enough signatures in 3 storkredse.

### "Votes to flip" — national level

```python
# Binary search: smallest delta that changes seat count
votes_to_gain_seat(party) -> int
votes_to_lose_seat(party) -> int
```

### "Votes to flip" — constituency level

```python
uncounted_districts = afstemningsomraader with no final result in opstillingskreds
max_remaining = sum(district.eligible_voters * historical_turnout_rate
                    for district in uncounted_districts)
gap = leading_candidate.votes - challenger.votes
feasible = gap < max_remaining
```

This surfaces: "Candidate X trails by 340 votes. 2 districts remain with ~800 eligible voters. Flip is feasible."

---

## Testing Infrastructure

```
valg/
  data/
    raw/          # mirrored live SFTP files
    historical/   # archived past elections for parser validation
  tests/
    fixtures/     # hand-crafted JSON edge cases (missing fields, bad timestamps)
    synthetic/    # generator: streams fake results district-by-district on a timer
    test_parser.py
    test_processor.py
    test_calculator.py
```

### Historical data

The SFTP server retains past elections in an archive folder (per the API doc).
Use the 2022 Folketing election as the primary validation dataset:
- Validates parser against real JSON structure
- Catches any divergence from the documented schema
- Known ground truth for seat calculation verification

### Synthetic generator

Configurable simulation of election night:
- Loads real geography and candidate data
- Drips results in district by district on a configurable timer
- Supports injection of edge cases: missing fields, recount corrections, districts reporting out of order

### Parser resilience rules

These apply to all JSON ingestion:
- Unknown fields: log field name + ignore
- Missing optional fields: store as NULL, do not crash
- Malformed timestamps: log + skip the row
- Every raw file stored with `ingest_at` timestamp for post-hoc debugging

---

## CLI (initial display layer)

```bash
python -m valg sync                        # fetch latest from SFTP, run processor
python -m valg status                      # districts reported, national totals
python -m valg party A                     # Socialdemokratiet: votes, seats, momentum
python -m valg candidate "Mette Frederiksen"
python -m valg flip                        # top 10 closest seat flips nationally
python -m valg kreds "Østerbro"            # constituency drilldown
```

The CLI is the first display layer. TUI (htop-style live dashboard) or a local web app
are natural next steps once the data pipeline is validated.

---

## Performance Characteristics

### Data volumes

#### Election night (foreløbig optælling)

| Dataset | Files | Size per file | Total |
|---|---|---|---|
| Geography | ~6 | 10-500KB | ~1MB |
| Candidate data | 10 (one/storkreds) | 50-100KB | ~1MB |
| Voter turnout | ~1,386 | 1-2KB | ~3MB |
| Election results (party-level) | ~1,386 | 2-3KB | ~4MB |
| Party vote distribution | ~92 | 5-10KB | ~1MB |
| **Election night total** | | | **~10MB** |

Election result files on election night contain party votes and totals per polling district,
but no candidate-level breakdown.

#### Fintælling (next day)

| Dataset | Files | Size per file | Total |
|---|---|---|---|
| Election results (candidate-level) | ~1,386 | 5-10KB | ~10MB |
| **Additional vs election night** | | | **~10MB** |

Fintælling files replace the election night files in place on the SFTP server — the same
filenames, but now containing candidate-level vote breakdowns alongside party totals.
The data repo git history preserves both versions.

**Full election total across both phases: ~20MB**

### Sync frequency and download per cycle

| Period | Phase | Interval | Files changed | Download |
|---|---|---|---|---|
| Election day | Valgdeltagelse (turnout) | every 30 min | 200-400 | ~500KB |
| 20:00-21:00 | First results trickle in | every 10 min | 50-150 | ~300KB |
| 21:00-23:00 | Peak foreløbig reporting | every 5 min | 100-300 | ~800KB |
| 23:00-01:00 | Late stragglers | every 10 min | 20-80 | ~200KB |
| Next day | Fintælling (replaces files) | every 30 min | 50-200 | ~1-2MB |

mtime-based diffing means only changed files are downloaded each cycle.

### Processing time

**Election night (party-level files, smaller):**
- Per file (JSON parse + SQLite insert): <1ms
- Incremental sync (100 new files): <0.5 seconds
- Saint-Laguë + D'Hondt seat allocation (15 parties): <1ms
- "Votes to flip" binary search (per party): <1ms
- End-to-end sync cycle (fetch + process + recalculate): **5-10 seconds**

**Fintælling (candidate-level files, larger):**
- Per file: 2-5ms (more rows per file)
- Full reprocess of 1,386 fintælling files from scratch: 5-15 seconds
- Incremental sync (100 updated files): ~1 second
- Candidate ranking queries (per opstillingskreds): <5ms with indexes
- End-to-end sync cycle: **15-30 seconds**

### SQLite DB size

**Election night rows:**
~1,386 districts × ~15 parties × ~30 sync snapshots = ~620K party result rows

**Fintælling rows:**
~1,386 districts × ~900 candidates × ~15 fintælling snapshots = ~18M candidate result rows

With indexes, candidate queries remain fast (<50ms). Total DB size with both phases: **200-500MB**.
If storage is a concern, old preliminary snapshots can be pruned once fintælling is complete.

### Fetcher loop

The fetcher runs continuously with a configurable sleep interval:

```bash
# Election night — sync every 5 minutes
python -m valg sync --interval 300 --election-folder /Folketingsvalg-1-2024

# Fintælling — less urgent, every 30 minutes
python -m valg sync --interval 1800 --election-folder /Folketingsvalg-1-2024
```

---

## Project Structure

Two repos:

```
valg/                          # code repo (public GitHub)
  .github/workflows/
    sync.yml           # GitHub Actions cron sync
  docs/plans/
  tests/
    fixtures/          # hand-crafted JSON edge cases
    synthetic/         # election night simulator
    e2e/               # end-to-end tests per use case
  valg/
    __init__.py
    fetcher.py         # SFTP sync + data repo git commit
    processor.py       # JSON -> SQLite dispatch
    models.py          # SQLite schema + queries + indexes
    calculator.py      # D'Hondt, Saint-Lague, flip logic
    cli.py             # argparse entry point
    plugins/           # hot-pluggable file parsers
  deploy/
    valg-sync.service  # systemd unit
    install.sh
  LICENSE
  DISCLAIMER.md
  .env.example
  valg.db              # generated, gitignored
  README.md

valg-data/                     # data repo (separate git repo)
  <election-folder>/
    Geografi/
    Kandidatdata/
    Valgresultater/
    Valgdeltagelse/
    Partistemmefordeling/
```

`valg-data/` is initialised as a git repo, auto-committed after each sync, and optionally
pushed to a private remote. It is referenced by the fetcher via a config path, not a submodule.

---

## GitHub Actions Sync

For public repos, GitHub Actions provides free unlimited compute minutes. The sync workflow runs on a cron schedule and requires no infrastructure beyond the two repos.

```yaml
# .github/workflows/sync.yml (in the valg/ code repo)
on:
  schedule:
    - cron: "*/5 * * * *"   # every 5 minutes
  workflow_dispatch:          # manual trigger for testing
```

The workflow:
1. Checks out `valg-data/` into the runner
2. Runs `python -m valg sync --election-folder <path> --data-repo ./valg-data`
3. Commits and pushes any new files to `valg-data/`

**Limitations:**
- GitHub cron minimum interval is 5 minutes
- Under load, GitHub may delay scheduled runs by several minutes — acceptable for this use case
- The election folder path must be updated per election (stored as a repo variable)

**Credentials:** SFTP credentials are stored as GitHub Actions secrets (even though they are publicly documented, this is cleaner than hardcoding them in the workflow file).

## Server Deployment

The tool is designed to run on a small always-on server (e.g. a VPS, Raspberry Pi, or spare
Mac) during election periods. The local machine is not required to stay on.

### Deployment model

```
[ VPS / server ]
  valg sync --interval 300   # runs as a systemd service or screen session
  valg-data/                 # data repo, pushed to private remote after each commit
  valg.db                    # SQLite DB, queried via CLI

[ Your laptop / colleague ]
  git pull valg-data          # optional: pull raw data for local replay
  python -m valg status       # query against local or remote DB
```

### Minimal server requirements

- Python 3.11+, git, paramiko, gitpython, rich
- ~500MB disk (data repo + SQLite over full election)
- Network access to data.valg.dk:22
- No public-facing ports required (CLI only)

### Running as a service (systemd example)

```ini
# /etc/systemd/system/valg-sync.service
[Unit]
Description=Valg SFTP sync
After=network.target

[Service]
ExecStart=/usr/bin/python3 -m valg sync \
  --election-folder /Folketingsvalg-1-2024 \
  --interval 300
WorkingDirectory=/opt/valg
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Remote access to query results: SSH into the server and run CLI commands, or expose
`valg.db` via scp/rsync if a web frontend is added later.

---

## Hot-Pluggable Parsing

The JSON schema from valg.dk has evolved across versions (v1.0 → v1.8) and will
diverge from the spec on election night. The processor uses a **plugin registry**
so new file handlers can be added without modifying the core processor.

### Plugin interface

Each plugin is a Python file in `valg/plugins/` that exports:
- `MATCH: callable(filename: str) -> bool` — returns True if this plugin handles the file
- `parse(data: dict | list, snapshot_at: str) -> list[dict]` — returns normalized rows
- `TABLE: str` — target SQLite table name

```
valg/plugins/
  __init__.py          # registry loader
  valgresultater_fv.py # handles valgresultater-Folketingsvalg-*.json
  kandidatdata_fv.py   # handles kandidat-data-Folketingsvalg-*.json
  geografi.py          # handles Region.json, Storkreds.json, etc.
  partistemmer.py      # handles partistemmefordeling-*.json
  valgdeltagelse.py    # handles valgdeltagelse-*.json
```

Adding a new parser for an unexpected file format = drop a new `.py` into `valg/plugins/`,
no other files touched. Plugins are auto-discovered at startup via `importlib`.

### Registry loading

```python
# valg/plugins/__init__.py
import importlib
import pkgutil
from pathlib import Path

_plugins = []

def load_plugins():
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        mod = importlib.import_module(f"valg.plugins.{name}")
        if hasattr(mod, "MATCH") and hasattr(mod, "parse"):
            _plugins.append(mod)

def find_plugin(filename: str):
    for plugin in _plugins:
        if plugin.MATCH(filename):
            return plugin
    return None
```

The processor calls `find_plugin(path.name)` and dispatches accordingly.
Unknown files are logged and skipped — no crash, no manual intervention needed.

---

## Distribution & Licensing

### Code license — Beerware

The code is released under the Beerware License (Revision 42). This is a recognised
permissive license more liberal than MIT: retain the notice, do whatever you want with
the code, buy the author a beer if you find it useful.

It is not OSI-approved, which is irrelevant for a civic tool of this nature.

### Data license

Election data originates from the Danish government's public SFTP server (`data.valg.dk`),
operated by Netcompany on behalf of Indenrigsministeriet. The server is explicitly documented
for public access with published credentials.

Danish public sector data is generally covered by the **Danish Open Government License (DOGL)**
or the EU Public Sector Information directive, both of which permit free redistribution with
attribution. No explicit Terms of Service are published for the SFTP access; redistribution
is considered low-risk given the intentionally public nature of the endpoint.

The data repo (`valg-data/`) carries its own `README.md` stating the data source and
that it is an unofficial snapshot archive, not the authoritative record.

### SFTP credentials

The username and password (`Valg`) are publicly documented in the official API guide.
They are not secrets. However, hardcoding credentials in public source code is bad practice.
They are exposed via environment variables with documented defaults:

```bash
VALG_SFTP_HOST=data.valg.dk   # default
VALG_SFTP_PORT=22             # default
VALG_SFTP_USER=Valg           # default
VALG_SFTP_PASSWORD=Valg       # default — override if credentials change
```

### Required disclaimers

Three disclaimers are required, included in `DISCLAIMER.md` and surfaced in the README:

**1. Not official results**
This tool is an unofficial viewer of Danish election data. Official results are published
at valg.dk. During the foreløbig optælling (election night), results are preliminary and
subject to correction. Always consult the official source for authoritative figures.

**2. Seat projections are approximate**
Projected seat totals are calculated using a simplified model. Kredsmandater are allocated
using D'Hondt per storkreds. Tillægsmandater are approximated via national Saint-Laguë and
may differ from the official final allocation. This tool is for informational and analytical
purposes only and should not be cited as an official source.

**3. Data source attribution**
Election data is sourced from the Danish election authority's public SFTP server
(data.valg.dk), operated by Netcompany on behalf of Indenrigsministeriet. This tool
is not affiliated with or endorsed by Indenrigsministeriet or Netcompany.

---

## Development Workflow

### GitHub Flow (code repo only)

Feature branches off `main` for all changes. Merge freely — no formal review required for solo work. `valg-data/` is exempt: the sync loop auto-commits directly to `main` by design (it is a data log, not a code repo).

Contribution scaffolding is included from the start:
- `CONTRIBUTING.md` — branch naming, commit conventions, how to open a PR
- `.github/pull_request_template.md` — checklist for contributors

This means the repos are ready for open contributions when published without any workflow changes needed.

---

## Documentation

Plans and design documents are working artefacts — they stay out of the repos. Outcomes are distilled into READMEs written for a cold reader.

### `valg/` README

Audience: developers and technically curious users discovering the repo.

Covers: what the tool does and why, install instructions, CLI command reference, how the sync loop works, how to contribute.

### `valg-data/` README

Audience: anyone consuming the data directly — journalists, researchers, other developers.

Covers: what the data is, where it comes from (data.valg.dk, Indenrigsministeriet), how snapshots are structured, data license and attribution, how to replay a past election.

---

## Live Update News Roller

After each sync cycle, the fetcher diffs the new snapshot against the previous one and writes detected events to an `events` table in SQLite.

### Events table

```sql
events (
  id          INTEGER PRIMARY KEY,
  occurred_at TEXT,       -- snapshot timestamp when event was detected
  event_type  TEXT,       -- 'seat_flip', 'momentum_shift', 'district_complete', 'correction', etc.
  subject     TEXT,       -- party letter, candidate name, or district name
  description TEXT,       -- human-readable summary
  data        TEXT        -- JSON blob of raw values (before/after, delta, etc.)
)
```

### Feed command

```bash
python -m valg feed                  # all events since last run
python -m valg feed --since 21:00    # events after a given time
python -m valg feed --type seat_flip # filter by event type
```

Events are written by the sync loop, not the calculator — diff-based detection means any change is caught automatically, including corrections and reversals.

The `events` table is the canonical source for the web feed and future TUI. No architectural change needed to add new consumers.

---

## AI Commentary

A model-agnostic AI layer that interprets results and generates human-readable commentary. The system passes structured data in, gets text back — the underlying model is swappable via config.

### Configuration

```bash
VALG_AI_BASE_URL=https://api.anthropic.com/v1   # or any OpenAI-compatible endpoint
VALG_AI_API_KEY=sk-...
VALG_AI_MODEL=claude-sonnet-4-6                 # or gpt-4o, llama3, etc.
```

Users without an AI subscription can omit these — the commentary feature degrades gracefully (disabled, not crashed).

### Trigger modes

**On-demand:**
```bash
python -m valg commentary            # full analysis of current state
python -m valg commentary --party A  # focused on a specific party
```

**Event-driven:** When the event roller detects a significant event (seat flip, large momentum shift), the sync loop automatically generates a short commentary snippet and appends it to the event record. Surfaced in the feed and web UI alongside the raw event.

### v1 scope

Commentary is the v1 output — structured prompts with current results data, returning a short analytical take. The events table and data model are rich enough for statistical modelling (e.g. seat flip probability from remaining votes and historical turnout rates) to be layered on as a v2 improvement.

---

## Self-Correcting Data Loop

The parser resilience rules (log and skip on anomalies) handle isolated bad records. The self-correcting loop handles **schema drift** — when a significant portion of files from a folder fail to parse, indicating the format has changed.

### Normal operation

All parse anomalies are logged silently to an `anomalies` table:

```sql
anomalies (
  id           INTEGER PRIMARY KEY,
  detected_at  TEXT,
  filename     TEXT,
  anomaly_type TEXT,   -- 'unknown_field', 'missing_key', 'parse_failure', etc.
  detail       TEXT
)
```

### Threshold escalation

If anomalies exceed a configurable threshold (default: >20% of files from a given folder fail parsing in one sync cycle):

1. The AI layer analyses the failing raw files and the existing plugin code
2. It generates a candidate plugin patch
3. **You are notified** (via the alert system) with the patch and the anomaly summary
4. The patch is applied only when you confirm — controlled by a config flag:

```bash
VALG_AI_AUTOPATCH=false   # default: require confirmation
VALG_AI_AUTOPATCH=true    # apply patches automatically (election night fast-path)
```

The raw files are always preserved in `valg-data/` — even if the patch is wrong, no data is lost and a corrected plugin can be applied retroactively.

### Fire drills

Before each election, run the sync loop against the 2022 historical archive with artificial schema mutations injected to verify the escalation path works end-to-end and calibrate the threshold.

---

## Public Web App

A static site hosted on GitHub Pages. All calculations run client-side in the browser. No backend required.

### Architecture

```
valg-data/ (public GitHub repo)
       |
       v
  GitHub Pages (valg/ repo, /docs or gh-pages branch)
  [ Svelte app ]
       |-- fetches latest JSON from valg-data/ raw URLs
       |-- fetches git commit list for history scrubber
       |-- runs seat calculations in-browser (WASM or JS port of calculator)
       |-- persists alert config to localStorage
```

### Tech stack

- **Framework:** Svelte — reactive, compiles to small vanilla JS bundles, minimal boilerplate
- **Charts:** TBD (Chart.js or Observable Plot)
- **Data fetching:** Raw JSON from `valg-data/` GitHub raw URLs, cached in `localStorage`
- **Hosting:** GitHub Pages (free, zero infrastructure)

### History scrubber

The app fetches the commit list from `valg-data/` via the GitHub API and renders a timeline scrubber. Selecting a past commit fetches the JSON files at that point in history, re-runs the client-side calculations, and re-renders the dashboard. Useful for testing, post-election analysis, and the replay use case (UC7).

### Performance

Data volumes are small (~10-20MB total). Fetching only changed files per snapshot and caching in `localStorage` keeps the page snappy. Seat calculations are fast enough to run in-browser synchronously — no worker threads required for v1.

---

## Alert System

User-defined conditions that trigger Web Push notifications in the browser. When the web app detects a matching event in the latest data fetch, it fires a notification even if the tab is backgrounded (requires notification permission).

### Condition types

- New vote count for a specific candidate or party (above a threshold delta)
- Seat flip between two parties
- Candidate moving into or out of an elected position within their party
- District reporting complete (for a watched opstillingskreds)

### Configuration

Conditions are defined in the web UI and persisted to `localStorage`. The same config format can be hand-edited or exported/imported as JSON for power users.

```json
{
  "alerts": [
    { "type": "candidate_votes", "candidate": "Mette Frederiksen", "min_delta": 100 },
    { "type": "seat_flip", "party_a": "A", "party_b": "V" },
    { "type": "candidate_elected", "party": "A" }
  ]
}
```

The UI settings panel reads from and writes to this structure in `localStorage`. No server-side persistence — alerts are per-browser by design.

### Delivery

Web Push (browser notifications) for v1. Background delivery via Ntfy or similar is a future option if you want alerts when the browser is not open.

---

## Out of Scope (v1)

- Tillægsmandater exact calculation (requires full kredsmandater pass first, deferred to v2)
- Kommunalvalg / Regionsrådsvalg
- Europa-Parlamentsvalg
- Folkeafstemning
- TUI (CLI + web first)
- Multi-election comparison / historical trends
- AI auto-patch without confirmation (config flag exists, default off — revisit after fire drills)
- Background push notifications / Ntfy (Web Push first)
