# Standalone Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A double-click executable for macOS and Windows that pulls election data from the public `valg-data` GitHub repo and serves a local browser dashboard with buttons for all CLI commands and CSV export.

**Architecture:** `http_fetcher.py` syncs JSON files from GitHub via HTTPS (no SFTP, no credentials). `queries.py` provides structured data for CSV export. `server.py` is a Flask app with embedded HTML that runs locally, auto-polls every 60 seconds, and opens the browser on startup. PyInstaller bundles everything into a single executable per platform.

**Tech Stack:** Python 3.11+, Flask 3.x, urllib.request (stdlib), PyInstaller, GitHub Actions for cross-platform builds.

---

## Task 1: Add Flask dependency + http_fetcher.py

**Files:**
- Modify: `pyproject.toml`
- Create: `valg/http_fetcher.py`
- Create: `tests/test_http_fetcher.py`

### Step 1: Write failing tests

```python
# tests/test_http_fetcher.py
import json
import pytest
from unittest.mock import patch, MagicMock
from valg.http_fetcher import fetch_tree, download_file, sync_from_github


def _mock_response(data):
    cm = MagicMock()
    cm.__enter__ = lambda s: s
    cm.__exit__ = MagicMock(return_value=False)
    cm.read = MagicMock(
        return_value=json.dumps(data).encode() if isinstance(data, dict) else data
    )
    return cm


def test_fetch_tree_returns_only_json_blobs():
    tree = {
        "tree": [
            {"path": "Storkreds.json", "sha": "abc", "type": "blob"},
            {"path": "README.md", "sha": "def", "type": "blob"},
            {"path": "subdir/votes.json", "sha": "ghi", "type": "blob"},
            {"path": "subdir", "sha": "jkl", "type": "tree"},
        ]
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(tree)):
        result = fetch_tree()
    assert len(result) == 2
    assert all(f["path"].endswith(".json") for f in result)


def test_fetch_tree_excludes_non_json():
    tree = {"tree": [{"path": "README.md", "sha": "abc", "type": "blob"}]}
    with patch("urllib.request.urlopen", return_value=_mock_response(tree)):
        result = fetch_tree()
    assert result == []


def test_download_file_writes_content(tmp_path):
    with patch("urllib.request.urlopen", return_value=_mock_response(b'{"ok":true}')):
        download_file("Storkreds.json", tmp_path / "Storkreds.json")
    assert (tmp_path / "Storkreds.json").read_bytes() == b'{"ok":true}'


def test_download_file_creates_parent_dirs(tmp_path):
    with patch("urllib.request.urlopen", return_value=_mock_response(b'{}')):
        download_file("a/b/file.json", tmp_path / "a" / "b" / "file.json")
    assert (tmp_path / "a" / "b" / "file.json").exists()


def test_sync_downloads_new_files(tmp_path):
    tree = {"tree": [{"path": "Storkreds.json", "sha": "abc123", "type": "blob"}]}

    def fake_urlopen(url, timeout=10):
        if "api.github.com" in url:
            return _mock_response(tree)
        return _mock_response(b'[{"Kode":"SK1","Navn":"Test","AntalKredsmandater":10,"ValgId":"FV"}]')

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        count = sync_from_github(tmp_path)
    assert count == 1
    assert (tmp_path / "Storkreds.json").exists()


def test_sync_skips_unchanged_files(tmp_path):
    (tmp_path / ".sha_cache.json").write_text(json.dumps({"Storkreds.json": "abc123"}))
    tree = {"tree": [{"path": "Storkreds.json", "sha": "abc123", "type": "blob"}]}
    with patch("urllib.request.urlopen", return_value=_mock_response(tree)):
        count = sync_from_github(tmp_path)
    assert count == 0


def test_sync_downloads_when_sha_changed(tmp_path):
    (tmp_path / ".sha_cache.json").write_text(json.dumps({"Storkreds.json": "old_sha"}))
    tree = {"tree": [{"path": "Storkreds.json", "sha": "new_sha", "type": "blob"}]}

    def fake_urlopen(url, timeout=10):
        if "api.github.com" in url:
            return _mock_response(tree)
        return _mock_response(b'[]')

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        count = sync_from_github(tmp_path)
    assert count == 1
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/test_http_fetcher.py -v
```

Expected: `ImportError: cannot import name 'fetch_tree' from 'valg.http_fetcher'`

### Step 3: Add Flask to pyproject.toml

```toml
[project.optional-dependencies]
dev        = ["pytest>=8.0", "pytest-cov"]
ai         = ["openai>=1.0"]
standalone = ["flask>=3.0"]
```

Install:
```bash
.venv/bin/pip install -e ".[standalone]"
```

### Step 4: Implement valg/http_fetcher.py

```python
# valg/http_fetcher.py
"""
Fetches election JSON files from a public GitHub repo via HTTPS.
No SFTP, no git, no credentials required.
"""
import json
import logging
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

REPO = "deterherligt/valg-data"
BRANCH = "main"
_CACHE = ".sha_cache.json"


def fetch_tree(repo: str = REPO, branch: str = BRANCH) -> list[dict]:
    """Return list of {path, sha} for all .json blobs in the repo."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
    return [
        f for f in data.get("tree", [])
        if f.get("type") == "blob" and f["path"].endswith(".json")
    ]


def download_file(path: str, dest: Path, repo: str = REPO, branch: str = BRANCH) -> None:
    """Download a single file from GitHub raw."""
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=10) as resp:
        dest.write_bytes(resp.read())
    log.debug("Downloaded %s", path)


def sync_from_github(data_dir: Path, repo: str = REPO, branch: str = BRANCH) -> int:
    """
    Sync changed JSON files from repo to data_dir using SHA-based change detection.
    Returns number of files downloaded.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_path = data_dir / _CACHE
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    files = fetch_tree(repo, branch)
    downloaded = 0
    new_cache = dict(cache)

    for f in files:
        path, sha = f["path"], f["sha"]
        if cache.get(path) == sha:
            continue
        download_file(path, data_dir / path, repo, branch)
        new_cache[path] = sha
        downloaded += 1

    cache_path.write_text(json.dumps(new_cache))
    log.info("Synced %d files from %s", downloaded, repo)
    return downloaded
```

### Step 5: Run tests — confirm all pass

```bash
.venv/bin/pytest tests/test_http_fetcher.py -v
```

Expected: 7 PASSED

### Step 6: Full suite — no regressions

```bash
.venv/bin/pytest -q
```

### Step 7: Commit

```bash
git add pyproject.toml valg/http_fetcher.py tests/test_http_fetcher.py
git commit -m "feat: HTTP fetcher — sync valg-data from GitHub via HTTPS"
```

---

## Task 2: queries.py — structured data for CSV export

**Files:**
- Create: `valg/queries.py`
- Create: `tests/test_queries.py`

These functions return `list[dict]` (no Rich, no console) so the server can render both ASCII display and CSV download from the same data.

### Step 1: Write failing tests

```python
# tests/test_queries.py
import pytest
from valg.models import get_connection, init_db
from valg.queries import query_status, query_flip, query_party, query_kreds
from tests.synthetic.generator import generate_election, load_into_db


@pytest.fixture
def db_night():
    conn = get_connection(":memory:")
    init_db(conn)
    e = generate_election(seed=42)
    load_into_db(conn, e, phase="preliminary")
    return conn


@pytest.fixture
def db_final(db_night):
    e = generate_election(seed=42)
    load_into_db(db_night, e, phase="final")
    return db_night


def test_query_status_returns_list_of_dicts(db_night):
    rows = query_status(db_night)
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert all({"party", "votes", "pct", "seats"} <= r.keys() for r in rows)


def test_query_status_sorted_by_votes_descending(db_night):
    rows = query_status(db_night)
    votes = [r["votes"] for r in rows]
    assert votes == sorted(votes, reverse=True)


def test_query_status_empty_db_returns_empty_list():
    conn = get_connection(":memory:")
    init_db(conn)
    assert query_status(conn) == []


def test_query_flip_returns_top_10(db_night):
    rows = query_flip(db_night)
    assert len(rows) <= 10
    assert all({"party", "seats", "votes_to_gain", "votes_to_lose"} <= r.keys() for r in rows)


def test_query_party_returns_dict_for_known_party(db_night):
    rows = query_party(db_night, "A")
    assert len(rows) == 1
    assert rows[0]["party"] is not None
    assert "votes" in rows[0]
    assert "seats" in rows[0]


def test_query_party_returns_empty_for_unknown(db_night):
    assert query_party(db_night, "Z") == []


def test_query_kreds_returns_candidates_after_final(db_final):
    rows = query_kreds(db_final, "Opstillingskreds 1")
    assert len(rows) > 0
    assert all({"candidate", "party", "votes"} <= r.keys() for r in rows)


def test_query_kreds_returns_empty_for_unknown(db_final):
    assert query_kreds(db_final, "nonexistent") == []
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/test_queries.py -v
```

Expected: `ImportError: cannot import name 'query_status' from 'valg.queries'`

### Step 3: Implement valg/queries.py

```python
# valg/queries.py
"""
Pure query functions returning list[dict] for CSV export and web display.
No Rich, no console output.
"""
from valg.cli import _get_seat_data
from valg import calculator


def query_status(conn) -> list[dict]:
    total_ao = conn.execute("SELECT COUNT(*) FROM afstemningsomraader").fetchone()[0]
    prelim_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type='preliminary'"
    ).fetchone()[0]
    final_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type='final'"
    ).fetchone()[0]

    national, storkreds, kredsmandater = _get_seat_data(conn)
    if not national:
        return []

    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    total_votes = sum(national.values()) or 1

    return [
        {
            "party": party,
            "votes": votes,
            "pct": round(votes / total_votes * 100, 1),
            "seats": seats.get(party, 0),
            "districts_prelim": prelim_ao,
            "districts_final": final_ao,
            "districts_total": total_ao,
        }
        for party, votes in sorted(national.items(), key=lambda x: -x[1])
    ]


def query_flip(conn) -> list[dict]:
    national, storkreds, kredsmandater = _get_seat_data(conn)
    if not national:
        return []

    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    rows = []
    for party in national:
        if seats.get(party, 0) > 0:
            gain = calculator.votes_to_gain_seat(party, national, storkreds, kredsmandater)
            lose = calculator.votes_to_lose_seat(party, national, storkreds, kredsmandater)
            rows.append({
                "party": party,
                "seats": seats[party],
                "votes_to_gain": gain,
                "votes_to_lose": lose,
            })

    return sorted(rows, key=lambda r: min(r["votes_to_gain"], r["votes_to_lose"]))[:10]


def query_party(conn, letter: str) -> list[dict]:
    letter = letter.upper()
    row = conn.execute(
        "SELECT id, name FROM parties WHERE letter = ? OR id = ?", (letter, letter)
    ).fetchone()
    if not row:
        return []

    national, storkreds, kredsmandater = _get_seat_data(conn)
    votes = national.get(row["id"], 0)
    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    gain = calculator.votes_to_gain_seat(row["id"], national, storkreds, kredsmandater)
    lose = calculator.votes_to_lose_seat(row["id"], national, storkreds, kredsmandater)

    return [{
        "party": row["name"],
        "votes": votes,
        "seats": seats.get(row["id"], 0),
        "votes_to_gain": gain,
        "votes_to_lose": lose,
    }]


def query_kreds(conn, name: str) -> list[dict]:
    ok = conn.execute(
        "SELECT id, name FROM opstillingskredse WHERE name LIKE ?", (f"%{name}%",)
    ).fetchone()
    if not ok:
        return []

    rows = conn.execute(
        "SELECT c.name, c.party_id, SUM(r.votes) as total "
        "FROM results r JOIN candidates c ON c.id = r.candidate_id "
        "WHERE c.opstillingskreds_id = ? AND r.count_type = 'final' "
        "GROUP BY c.id ORDER BY total DESC LIMIT 20",
        (ok["id"],),
    ).fetchall()
    return [{"candidate": r["name"], "party": r["party_id"], "votes": r["total"]} for r in rows]
```

### Step 4: Run tests — confirm all pass

```bash
.venv/bin/pytest tests/test_queries.py -v
```

Expected: 8 PASSED

### Step 5: Full suite

```bash
.venv/bin/pytest -q
```

### Step 6: Commit

```bash
git add valg/queries.py tests/test_queries.py
git commit -m "feat: query functions returning structured data for CSV export"
```

---

## Task 3: server.py — Flask dashboard

**Files:**
- Create: `valg/server.py`
- Create: `tests/test_server.py`

### Step 1: Write failing tests

```python
# tests/test_server.py
import json
import pytest
from unittest.mock import patch, MagicMock
from valg.server import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "test.db", data_dir=tmp_path / "data")
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"valg" in resp.data
    assert b"<pre" in resp.data


def test_sync_status_returns_json(client):
    resp = client.get("/sync-status")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert "last_sync" in data


def test_run_status_returns_text(client):
    resp = client.post("/run", json={"cmd": "status"})
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/plain")


def test_run_unknown_command_returns_400(client):
    resp = client.post("/run", json={"cmd": "nonexistent"})
    assert resp.status_code == 400


def test_csv_status_returns_csv(client):
    resp = client.get("/csv/status")
    assert resp.status_code == 200
    assert "text/csv" in resp.content_type


def test_csv_unsupported_command_returns_404(client):
    resp = client.get("/csv/feed")
    assert resp.status_code == 404


def test_run_party_with_letter(client):
    resp = client.post("/run", json={"cmd": "party", "letter": "A"})
    assert resp.status_code == 200


def test_run_candidate_with_name(client):
    resp = client.post("/run", json={"cmd": "candidate", "name": "Test"})
    assert resp.status_code == 200


def test_run_kreds_with_name(client):
    resp = client.post("/run", json={"cmd": "kreds", "name": "Test"})
    assert resp.status_code == 200
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/test_server.py -v
```

Expected: `ImportError: cannot import name 'create_app' from 'valg.server'`

### Step 3: Implement valg/server.py

```python
# valg/server.py
"""
Standalone web dashboard for valg election results.

Run:  python -m valg.server
Opens browser at http://localhost:5000 automatically.
"""
import csv
import io
import logging
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, request

log = logging.getLogger(__name__)

# ── Path resolution (handles PyInstaller frozen mode) ────────────────────────

if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).parent
else:
    _APP_DIR = Path(__file__).parent.parent

_DEFAULT_DB = _APP_DIR / "valg.db"
_DEFAULT_DATA = _APP_DIR / "data"

# ── Sync state ────────────────────────────────────────────────────────────────

_last_sync = "never"
_just_synced = False
_sync_lock = threading.Lock()

# ── Embedded HTML ─────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<title>valg</title>
<style>
  body { font-family: monospace; margin: 0; background: #0d1117; color: #c9d1d9; }
  header { padding: 12px 20px; background: #161b22; border-bottom: 1px solid #30363d;
           display: flex; align-items: center; gap: 20px; }
  header h1 { margin: 0; font-size: 1.2em; color: #58a6ff; }
  #sync-info { font-size: 0.85em; color: #8b949e; }
  #controls { padding: 12px 20px; background: #161b22; border-bottom: 1px solid #30363d;
              display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
  button { background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
           padding: 6px 14px; cursor: pointer; font-family: monospace; font-size: 0.9em; }
  button:hover { background: #30363d; }
  button.active { background: #1f6feb; border-color: #1f6feb; color: #fff; }
  input[type=text] { background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
                     padding: 5px 10px; font-family: monospace; font-size: 0.9em; width: 120px; }
  #output-bar { padding: 8px 20px; background: #161b22; border-bottom: 1px solid #30363d;
                display: flex; align-items: center; gap: 10px; min-height: 36px; }
  #csv-btn { display: none; background: #238636; border-color: #2ea043; color: #fff; }
  #csv-btn:hover { background: #2ea043; }
  #output { margin: 0; padding: 20px; white-space: pre; overflow: auto;
            font-size: 0.9em; line-height: 1.5; min-height: 400px; }
</style>
</head>
<body>
<header>
  <h1>valg</h1>
  <span id="sync-info">Syncing every 60s &bull; Last sync: <span id="last-sync">–</span></span>
</header>
<div id="controls">
  <button onclick="run('status')" data-cmd="status">Status</button>
  <button onclick="run('flip')" data-cmd="flip">Flip</button>
  <span>
    <input type="text" id="party-input" placeholder="Party letter" maxlength="1">
    <button onclick="run('party')" data-cmd="party">Party</button>
  </span>
  <span>
    <input type="text" id="candidate-input" placeholder="Name">
    <button onclick="run('candidate')" data-cmd="candidate">Candidate</button>
  </span>
  <span>
    <input type="text" id="kreds-input" placeholder="Kreds name">
    <button onclick="run('kreds')" data-cmd="kreds">Kreds</button>
  </span>
  <button onclick="run('feed')" data-cmd="feed">Feed</button>
  <button onclick="run('commentary')" data-cmd="commentary">Commentary</button>
</div>
<div id="output-bar">
  <button id="csv-btn" onclick="downloadCsv()">Download CSV</button>
</div>
<pre id="output">Click a button to load data.</pre>
<script>
const CSV_COMMANDS = ['status', 'flip', 'party', 'kreds'];
let _current = null;

async function run(cmd) {
  const params = {cmd};
  if (cmd === 'party') params.letter = document.getElementById('party-input').value || 'A';
  if (cmd === 'candidate') params.name = document.getElementById('candidate-input').value;
  if (cmd === 'kreds') params.name = document.getElementById('kreds-input').value;

  document.querySelectorAll('button[data-cmd]').forEach(b => b.classList.remove('active'));
  document.querySelector(`button[data-cmd="${cmd}"]`).classList.add('active');
  document.getElementById('output').textContent = 'Loading...';
  document.getElementById('csv-btn').style.display = 'none';

  const resp = await fetch('/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(params),
  });
  document.getElementById('output').textContent = await resp.text();

  if (CSV_COMMANDS.includes(cmd)) {
    document.getElementById('csv-btn').style.display = 'inline';
  }
  _current = params;
}

function downloadCsv() {
  if (!_current) return;
  const params = new URLSearchParams(_current);
  window.location = '/csv/' + _current.cmd + '?' + params.toString();
}

async function pollSync() {
  try {
    const resp = await fetch('/sync-status');
    const data = await resp.json();
    document.getElementById('last-sync').textContent = data.last_sync;
    if (data.just_synced && _current) run(_current.cmd);
  } catch(e) {}
}

setInterval(pollSync, 10000);
pollSync();
</script>
</body>
</html>"""

# ── App factory ───────────────────────────────────────────────────────────────

def create_app(db_path: Path = _DEFAULT_DB, data_dir: Path = _DEFAULT_DATA) -> Flask:
    app = Flask(__name__)
    db_path = Path(db_path)
    data_dir = Path(data_dir)

    def _get_conn():
        from valg.models import get_connection, init_db
        conn = get_connection(db_path)
        init_db(conn)
        return conn

    def _capture(cmd: str, params: dict) -> str:
        """Run a CLI command, capture Rich output as plain text."""
        from io import StringIO
        from rich.console import Console as RichConsole
        import argparse

        buf = StringIO()
        rich_console = RichConsole(file=buf, width=100, no_color=True)

        # Temporarily patch the module-level console in cli
        import valg.cli as cli_mod
        original = cli_mod.console
        cli_mod.console = rich_console
        try:
            conn = _get_conn()
            args = argparse.Namespace(**params)
            dispatch = {
                "status": cli_mod.cmd_status,
                "flip": cli_mod.cmd_flip,
                "party": cli_mod.cmd_party,
                "candidate": cli_mod.cmd_candidate,
                "kreds": cli_mod.cmd_kreds,
                "feed": cli_mod.cmd_feed,
                "commentary": cli_mod.cmd_commentary,
            }
            handler = dispatch.get(cmd)
            if handler:
                handler(conn, args)
        finally:
            cli_mod.console = original

        return buf.getvalue()

    @app.get("/")
    def index():
        return _HTML, 200, {"Content-Type": "text/html; charset=utf-8"}

    @app.get("/sync-status")
    def sync_status():
        global _just_synced
        with _sync_lock:
            just = _just_synced
            _just_synced = False
        return jsonify({"last_sync": _last_sync, "just_synced": just})

    @app.post("/run")
    def run_command():
        data = request.get_json(force=True)
        cmd = data.get("cmd", "")
        valid = {"status", "flip", "party", "candidate", "kreds", "feed", "commentary"}
        if cmd not in valid:
            return "Unknown command", 400
        output = _capture(cmd, {k: v for k, v in data.items() if k != "cmd"})
        return output, 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.get("/csv/<cmd>")
    def csv_download(cmd):
        from valg.queries import query_status, query_flip, query_party, query_kreds
        handlers = {
            "status": lambda: query_status(_get_conn()),
            "flip": lambda: query_flip(_get_conn()),
            "party": lambda: query_party(_get_conn(), request.args.get("letter", "A")),
            "kreds": lambda: query_kreds(_get_conn(), request.args.get("name", "")),
        }
        if cmd not in handlers:
            return "CSV not available for this command", 404

        rows = handlers[cmd]()
        if not rows:
            return "No data", 200, {"Content-Type": "text/plain"}

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=valg-{cmd}.csv"},
        )

    return app


# ── Background sync ───────────────────────────────────────────────────────────

def _sync_loop(data_dir: Path, db_path: Path, interval: int = 60) -> None:
    global _last_sync, _just_synced
    import time
    while True:
        time.sleep(interval)
        try:
            from valg.http_fetcher import sync_from_github
            from valg.processor import process_directory
            from valg.plugins import load_plugins
            from valg.models import get_connection, init_db

            load_plugins()
            count = sync_from_github(data_dir)
            if count > 0:
                conn = get_connection(db_path)
                init_db(conn)
                process_directory(conn, data_dir)
            with _sync_lock:
                _last_sync = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
                _just_synced = count > 0
        except Exception as e:
            log.warning("Sync failed: %s", e)


# ── Entry point ───────────────────────────────────────────────────────────────

def main(port: int = 5000) -> None:
    from valg.plugins import load_plugins
    load_plugins()

    db_path = _DEFAULT_DB
    data_dir = _DEFAULT_DATA

    t = threading.Thread(target=_sync_loop, args=(data_dir, db_path), daemon=True)
    t.start()

    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app = create_app(db_path=db_path, data_dir=data_dir)
    app.run(host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
```

### Step 4: Run tests — confirm all pass

```bash
.venv/bin/pytest tests/test_server.py -v
```

Expected: 9 PASSED

### Step 5: Manual smoke test

```bash
python -m valg.server
```

Expected: browser opens at `http://localhost:5000`, page loads, clicking "Status" shows output.

### Step 6: Full suite

```bash
.venv/bin/pytest -q
```

### Step 7: Commit

```bash
git add valg/server.py tests/test_server.py
git commit -m "feat: Flask dashboard server with embedded HTML, CSV export, auto-sync"
```

---

## Task 4: PyInstaller build + GitHub Actions release workflow

**Files:**
- Create: `valg.spec` (PyInstaller spec)
- Create: `.github/workflows/release.yml`

No tests for the build workflow itself — verification is manual (download and run the artifact).

### Step 1: Create valg.spec

```python
# valg.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['valg/server.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'valg.plugins.geografi',
        'valg.plugins.kandidatdata_fv',
        'valg.plugins.partistemmer',
        'valg.plugins.valgdeltagelse',
        'valg.plugins.valgresultater_fv',
        'valg.queries',
        'valg.http_fetcher',
        'valg.differ',
        'valg.ai',
        'valg.calculator',
        'valg.processor',
        'valg.models',
        'valg.cli',
        'valg.fetcher',
        'flask',
        'werkzeug',
        'rich',
        'dotenv',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['paramiko', 'git'],  # not needed for standalone mode
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='valg',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # set False on Windows for no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

### Step 2: Create .github/workflows/release.yml

```yaml
# .github/workflows/release.yml
name: Build & Release

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:

jobs:
  build:
    strategy:
      matrix:
        include:
          - os: macos-latest
            artifact: valg-macos
          - os: windows-latest
            artifact: valg-windows.exe

    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -e ".[standalone]" pyinstaller

      - name: Build executable (macOS)
        if: runner.os == 'macOS'
        run: pyinstaller valg.spec --distpath dist/

      - name: Build executable (Windows)
        if: runner.os == 'Windows'
        run: pyinstaller valg.spec --distpath dist/

      - name: Rename artifact (macOS)
        if: runner.os == 'macOS'
        run: mv dist/valg dist/valg-macos

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: ${{ matrix.artifact }}
          path: dist/${{ matrix.artifact }}

  release:
    needs: build
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/')

    steps:
      - uses: actions/download-artifact@v4
        with:
          path: artifacts/

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            artifacts/valg-macos/valg-macos
            artifacts/valg-windows.exe/valg-windows.exe
          generate_release_notes: true
```

### Step 3: Test the build locally (macOS)

```bash
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller valg.spec --distpath dist/
./dist/valg
```

Expected: browser opens at `localhost:5000`.

### Step 4: Commit

```bash
git add valg.spec .github/workflows/release.yml
git commit -m "feat: PyInstaller spec and GitHub Actions release workflow"
```

---

## Task 5: Update README + push

**Files:**
- Modify: `README.md`

### Step 1: Add download section to README

Add a "Download" section above "Setup":

```markdown
## Download (no Python required)

Go to [Releases](https://github.com/deterherligt/valg/releases) and download:
- **macOS:** `valg-macos` — right-click → Open on first run (Gatekeeper)
- **Windows:** `valg-windows.exe` — click "More info → Run anyway" on first run (SmartScreen)

Double-click to start. Your browser opens automatically at `http://localhost:5000`.
Data syncs from the public [valg-data](https://github.com/deterherligt/valg-data) repo every 60 seconds.
```

### Step 2: Commit and push everything

```bash
git add README.md
git commit -m "docs: add download section for standalone executable"
git push
```

### Step 3: Trigger a manual build to verify the workflow

```bash
gh workflow run release.yml --repo deterherligt/valg
gh run watch --repo deterherligt/valg
```

Expected: both macOS and Windows artifacts build successfully. Download and smoke-test each.
