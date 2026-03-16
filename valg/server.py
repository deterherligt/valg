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

        # Map JSON param names to argparse attribute names
        _rename = {
            "party": {"letter": "party_letter"},
            "candidate": {"name": "candidate_name"},
            "kreds": {"name": "kreds_name"},
        }
        mapped = {_rename.get(cmd, {}).get(k, k): v for k, v in params.items()}

        import valg.cli as cli_mod
        original = cli_mod.console
        cli_mod.console = rich_console
        try:
            conn = _get_conn()
            args = argparse.Namespace(**mapped)
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

    @app.get("/api/status")
    def api_status():
        global _just_synced
        with _sync_lock:
            just = _just_synced
            _just_synced = False
        from valg.queries import query_api_status
        meta = query_api_status(_get_conn())
        return jsonify({
            "last_sync": _last_sync,
            "just_synced": just,
            **meta,
        })

    @app.get("/api/parties")
    def api_parties():
        from valg.queries import query_api_parties
        return jsonify(query_api_parties(_get_conn()))

    @app.get("/api/candidates")
    def api_candidates():
        raw = request.args.get("party_ids", "")
        party_ids = [p.strip() for p in raw.split(",") if p.strip()]
        from valg.queries import query_api_candidates
        return jsonify(query_api_candidates(_get_conn(), party_ids))

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
        buf = io.StringIO()
        if not rows:
            return Response(
                "",
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=valg-{cmd}.csv"},
            )
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
