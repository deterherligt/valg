# valg/server.py
"""
Web dashboard for valg election results.

Run:  python -m valg.server
"""
import csv
import io
import logging
import os
import sys
import threading
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

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
_live_data_available = False
_sync_lock = threading.Lock()


def _maybe_switch_to_live(db_path: Path, session_manager) -> None:
    """Switch all demo sessions to live data if real election night results exist.

    Called from _sync_loop on every iteration. No-op once _live_data_available is True.

    Detection: look for preliminary results with votes > 0 that were snapshotted
    on or after election day. Pre-election test data has pre-election-day snapshots.
    """
    global _live_data_available
    if session_manager is None or _live_data_available:
        return
    from valg.models import get_connection
    conn = get_connection(db_path)
    # Only trigger on results from election day (2026-03-24) onward
    has_real = conn.execute(
        "SELECT 1 FROM results "
        "WHERE count_type = 'preliminary' "
        "AND votes > 0 "
        "AND REPLACE(snapshot_at, 'T', ' ') >= '2026-03-24' "
        "LIMIT 1"
    ).fetchone() is not None
    conn.close()
    if has_real:
        log.info("Live election data detected — switching all sessions to live")
        session_manager.switch_all_to_live()
        _live_data_available = True


# ── App factory ───────────────────────────────────────────────────────────────

def create_app(
    db_path: Path = _DEFAULT_DB,
    data_dir: Path = _DEFAULT_DATA,
    demo_runner=None,
    data_repo: Path | None = None,
    session_manager=None,
) -> Flask:
    app = Flask(__name__)
    db_path = Path(db_path)

    def _get_conn():
        from valg.models import get_connection, init_db
        if session_manager is not None:
            sid = request.cookies.get("valg_session")
            session = session_manager.get(sid) if sid else None
            conn_path = db_path if (session is None or session.live) else session.db_path
        else:
            conn_path = db_path
        conn = get_connection(conn_path)
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
        from flask import make_response
        resp = make_response(render_template("index.html"))
        if session_manager is not None:
            sid = request.cookies.get("valg_session") or str(_uuid.uuid4())
            session_manager.get_or_create(sid)
            # Always set cookie — even if cap exceeded so visitor retains same ID
            resp.set_cookie("valg_session", sid, httponly=True, samesite="Lax")
        return resp

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

    @app.get("/api/party-detail")
    def api_party_detail():
        raw = request.args.get("party_ids", "")
        party_ids = [p.strip() for p in raw.split(",") if p.strip()]
        from valg.queries import query_api_party_detail
        return jsonify(query_api_party_detail(_get_conn(), party_ids))

    @app.get("/api/candidate/<candidate_id>")
    def api_candidate(candidate_id):
        from valg.queries import query_api_candidate
        data = query_api_candidate(_get_conn(), candidate_id)
        if data is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(data)

    @app.get("/api/feed/places")
    def api_feed_places():
        from valg.queries import query_feed_places
        return jsonify(query_feed_places(_get_conn()))

    @app.get("/api/place/<place_id>")
    def api_place(place_id):
        from valg.queries import query_place_detail
        data = query_place_detail(_get_conn(), place_id)
        if data is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(data)

    @app.get("/api/candidate-feed/<candidate_id>")
    def api_candidate_feed(candidate_id):
        limit = min(int(request.args.get("limit", 20)), 100)
        from valg.queries import query_api_candidate_feed
        return jsonify(query_api_candidate_feed(_get_conn(), candidate_id, limit))

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

    _demo_repo = data_repo

    if session_manager is not None:
        @app.get("/demo/state")
        def demo_state():
            sid = request.cookies.get("valg_session")
            session = session_manager.get(sid) if sid else None
            if session is None or session.live:
                return jsonify({
                    "enabled": False, "state": "unavailable",
                    "scenarios": [], "speed": 1,
                    "step_index": -1, "step_name": "", "steps_total": 0,
                })
            return jsonify(session.runner.get_state_dict())

        @app.post("/demo/control")
        def demo_control():
            sid = request.cookies.get("valg_session")
            session = session_manager.get(sid) if sid else None
            if session is None:
                return "No active session", 404
            data = request.get_json(force=True)
            action = data.get("action", "")
            try:
                if action == "start":
                    session.runner.start(db_path=session.db_path, data_repo=session.data_dir)
                elif action == "pause":
                    session.runner.pause()
                elif action == "resume":
                    session.runner.resume()
                elif action == "restart":
                    session.runner.restart(db_path=session.db_path, data_repo=session.data_dir)
                elif action == "set_speed":
                    session.runner.set_speed(float(data["speed"]))
                elif action == "set_scenario":
                    session.runner.set_scenario(data["scenario"])
                else:
                    return f"Unknown action: {action}", 400
            except (KeyError, ValueError, RuntimeError) as e:
                return str(e), 400
            return "ok", 200

    elif demo_runner is not None:
        @app.get("/demo/state")
        def demo_state():
            return jsonify(demo_runner.get_state_dict())

        @app.post("/demo/control")
        def demo_control():
            data = request.get_json(force=True)
            action = data.get("action", "")
            repo = _demo_repo or Path(os.environ.get("VALG_DATA_REPO", "../valg-data"))
            try:
                if action == "start":
                    demo_runner.start(db_path=db_path, data_repo=repo)
                elif action == "pause":
                    demo_runner.pause()
                elif action == "resume":
                    demo_runner.resume()
                elif action == "restart":
                    demo_runner.restart(db_path=db_path, data_repo=repo)
                elif action == "set_speed":
                    demo_runner.set_speed(float(data["speed"]))
                elif action == "set_scenario":
                    demo_runner.set_scenario(data["scenario"])
                else:
                    return f"Unknown action: {action}", 400
            except (KeyError, ValueError, RuntimeError) as e:
                return str(e), 400
            return "ok", 200

        # ── Admin API ────────────────────────────────────────────────────────────

        def _check_admin_auth():
            token = os.environ.get("VALG_ADMIN_TOKEN")
            if not token:
                return jsonify({"error": "admin not configured"}), 503
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[len("Bearer "):] != token:
                return jsonify({"error": "unauthorized"}), 401
            return None

        @app.post("/admin/demo")
        def admin_demo_start():
            err = _check_admin_auth()
            if err is not None:
                return err
            body = request.get_json(silent=True) or {}
            scenario = body.get("scenario", "")
            from valg.demo import SCENARIOS
            if scenario not in SCENARIOS:
                return jsonify({"error": f"unknown scenario: {scenario!r}"}), 400
            demo_runner.set_scenario(scenario)
            if "speed" in body:
                demo_runner.set_speed(float(body["speed"]))
            demo_runner.start(db_path=db_path, data_repo=data_repo or Path(os.environ.get("VALG_DATA_REPO", "../valg-data")))
            return jsonify({"status": "started", "scenario": scenario}), 200

        @app.post("/admin/demo/stop")
        def admin_demo_stop():
            err = _check_admin_auth()
            if err is not None:
                return err
            demo_runner.pause()
            return jsonify({"status": "stopped"}), 200

    else:
        @app.get("/demo/state")
        def demo_state_disabled():
            return "Demo mode not enabled", 404

        @app.post("/demo/control")
        def demo_control_disabled():
            return "Demo mode not enabled", 404

    return app


# ── Background sync ───────────────────────────────────────────────────────────

def _sync_loop(data_dir: Path, db_path: Path, interval: int = 60, session_manager=None, run_immediately: bool = False) -> None:
    global _last_sync, _just_synced
    import time
    if not run_immediately:
        time.sleep(interval)
    while True:
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
            _maybe_switch_to_live(db_path, session_manager)
        except Exception as e:
            log.warning("Sync failed: %s", e)
        time.sleep(interval)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(prog="valg-server")
    parser.add_argument("--demo", action="store_true", help="Enable demo mode")
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    import subprocess as _sp

    from valg.plugins import load_plugins
    load_plugins()

    db_path = args.db
    data_dir = _DEFAULT_DATA
    data_repo = Path(os.environ.get("VALG_DATA_REPO", "../valg-data"))

    data_repo.mkdir(parents=True, exist_ok=True)
    if not (data_repo / ".git").exists():
        _sp.run(["git", "init"], cwd=str(data_repo), check=True)
        _sp.run(["git", "config", "user.email", "valg@localhost"], cwd=str(data_repo), check=True)
        _sp.run(["git", "config", "user.name", "valg"], cwd=str(data_repo), check=True)

    from valg.models import get_connection, init_db

    # Initialize DB schema before starting (fast, no network)
    _init_conn = get_connection(db_path)
    init_db(_init_conn)
    _init_conn.close()

    from valg.sessions import SessionManager
    session_manager = SessionManager(base_dir=_APP_DIR / "sessions")

    # Initial sync + ongoing sync both happen in background — app boots immediately
    t = threading.Thread(target=_sync_loop, args=(data_dir, db_path), kwargs={"session_manager": session_manager, "run_immediately": True}, daemon=True)
    t.start()

    app = create_app(
        db_path=db_path,
        data_dir=data_dir,
        session_manager=session_manager,
        data_repo=data_repo,
    )
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", args.port)))


if __name__ == "__main__":
    main()
