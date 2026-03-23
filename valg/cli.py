# valg/cli.py
"""
CLI entry point for the valg election dashboard.

Usage:
    python -m valg [--db PATH] <command> [args]

Commands:
    sync       Fetch from SFTP and process data
    status     Show districts reported and national totals
    party      Party drilldown (votes, seats, momentum)
    candidate  Candidate tracking
    flip       Top 10 closest seat flips nationally
    kreds      Constituency drilldown
    feed       Live event feed
    commentary AI commentary on current state
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

from valg.queries import get_seat_data as _get_seat_data

console = Console()

# ── DB helper ────────────────────────────────────────────────────────────────

def _get_conn(db_path: Path):
    from valg.models import get_connection, init_db
    conn = get_connection(db_path)
    init_db(conn)
    return conn


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_status(conn, args):
    from valg.plugins import load_plugins
    load_plugins()

    total_ao = conn.execute("SELECT COUNT(*) FROM afstemningsomraader").fetchone()[0]
    prelim_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type='preliminary'"
    ).fetchone()[0]
    final_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results WHERE count_type='final'"
    ).fetchone()[0]

    if total_ao == 0:
        console.print("[dim]No data yet.[/dim]")
        return

    console.print(f"Districts: [bold]{prelim_ao}/{total_ao}[/bold] foreløbig, "
                  f"[bold]{final_ao}/{total_ao}[/bold] fintælling")

    national, storkreds, kredsmandater = _get_seat_data(conn)
    if not national:
        console.print("[dim]No vote data yet.[/dim]")
        return

    from valg import calculator
    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)

    t = Table(title="National results")
    t.add_column("Party")
    t.add_column("Votes", justify="right")
    t.add_column("Seats", justify="right")
    total_votes = sum(national.values()) or 1
    for party, votes in sorted(national.items(), key=lambda x: -x[1]):
        pct = votes / total_votes * 100
        t.add_row(party, f"{votes:,} ({pct:.1f}%)", str(seats.get(party, 0)))
    console.print(t)


def cmd_flip(conn, args):
    from valg import calculator

    national, storkreds, kredsmandater = _get_seat_data(conn)
    if not national:
        console.print("[dim]No data.[/dim]")
        return

    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    results = []
    for party in national:
        if seats.get(party, 0) > 0:
            gain = calculator.votes_to_gain_seat(party, national, storkreds, kredsmandater)
            lose = calculator.votes_to_lose_seat(party, national, storkreds, kredsmandater)
            results.append((min(gain, lose), party, gain, lose, seats[party]))

    results.sort()
    t = Table(title="Seat flip margins (top 10 closest)")
    t.add_column("Party")
    t.add_column("Seats", justify="right")
    t.add_column("+1 seat (votes)", justify="right")
    t.add_column("-1 seat (votes)", justify="right")
    for _, party, gain, lose, seat_count in results[:10]:
        t.add_row(party, str(seat_count), f"+{gain:,}", f"-{lose:,}")
    console.print(t)


def cmd_party(conn, args):
    from valg import calculator

    letter = args.party_letter.upper()
    row = conn.execute(
        "SELECT id, name FROM parties WHERE letter = ? OR id = ?", (letter, letter)
    ).fetchone()
    if not row:
        console.print(f"[yellow]No party found: {letter}[/yellow]")
        return

    national, storkreds, kredsmandater = _get_seat_data(conn)
    votes = national.get(row["id"], 0)
    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    console.print(f"[bold]{row['name']}[/bold] ({letter})")
    console.print(f"  Votes: {votes:,}")
    console.print(f"  Projected seats: {seats.get(row['id'], 0)}")
    gain = calculator.votes_to_gain_seat(row["id"], national, storkreds, kredsmandater)
    lose = calculator.votes_to_lose_seat(row["id"], national, storkreds, kredsmandater)
    console.print(f"  To gain seat: +{gain:,}")
    console.print(f"  To lose seat: -{lose:,}")


def cmd_candidate(conn, args):
    name = args.candidate_name
    rows = conn.execute(
        "SELECT c.id, c.name, c.party_id FROM candidates c "
        "WHERE c.name LIKE ?", (f"%{name}%",)
    ).fetchall()
    if not rows:
        console.print(f"[dim]No candidate found: {name}[/dim]")
        return
    for row in rows:
        total = conn.execute(
            "SELECT SUM(votes) as v FROM results WHERE candidate_id = ? AND count_type='final'",
            (row["id"],)
        ).fetchone()["v"] or 0
        prelim = conn.execute(
            "SELECT SUM(votes) as v FROM results WHERE candidate_id = ? AND count_type='preliminary'",
            (row["id"],)
        ).fetchone()["v"] or 0
        console.print(f"[bold]{row['name']}[/bold] (Party {row['party_id']})")
        console.print(f"  Fintælling votes: {total:,}")
        if prelim:
            console.print(f"  Foreløbig votes: {prelim:,}")


def cmd_kreds(conn, args):
    name = args.kreds_name
    ok = conn.execute(
        "SELECT id, name FROM opstillingskredse WHERE name LIKE ?", (f"%{name}%",)
    ).fetchone()
    if not ok:
        console.print(f"[dim]No opstillingskreds found: {name}[/dim]")
        return

    rows = conn.execute(
        "SELECT c.name, c.party_id, SUM(r.votes) as total "
        "FROM results r "
        "JOIN candidates c ON c.id = r.candidate_id "
        "WHERE c.opstillingskreds_id = ? AND r.count_type = 'final' "
        "GROUP BY c.id ORDER BY total DESC LIMIT 20",
        (ok["id"],),
    ).fetchall()
    if not rows:
        console.print(f"[dim]No final results for {ok['name']} yet.[/dim]")
        return
    t = Table(title=f"{ok['name']} — candidate rankings")
    t.add_column("Candidate")
    t.add_column("Party")
    t.add_column("Votes", justify="right")
    for r in rows:
        t.add_row(r["name"], r["party_id"], f"{r['total']:,}")
    console.print(t)


def cmd_feed(conn, args):
    conditions = []
    params: list = []
    if hasattr(args, "since") and args.since:
        conditions.append("occurred_at >= ?")
        params.append(args.since)
    if hasattr(args, "type") and args.type:
        conditions.append("event_type = ?")
        params.append(args.type)
    query = "SELECT occurred_at, event_type, subject, description FROM events"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY occurred_at DESC LIMIT ?"
    params.append(getattr(args, "limit", 50) or 50)
    rows = conn.execute(query, params).fetchall()
    if not rows:
        console.print("[dim]No events yet.[/dim]")
        return
    for r in rows:
        console.print(f"[dim]{r['occurred_at']}[/dim] [{r['event_type']}] {r['subject']}: {r['description']}")


def cmd_commentary(conn, args):
    from valg.ai import get_commentary, is_ai_configured
    if not is_ai_configured():
        console.print("[yellow]AI not configured. Set VALG_AI_API_KEY in .env[/yellow]")
        return

    national, storkreds, kredsmandater = _get_seat_data(conn)
    from valg import calculator
    seats = calculator.allocate_seats_total(national, storkreds, kredsmandater)
    total_ao = conn.execute("SELECT COUNT(*) FROM afstemningsomraader").fetchone()[0]
    reported_ao = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results"
    ).fetchone()[0]
    state = {
        "parties": [{"letter": k, "votes": v, "seats": seats.get(k, 0)} for k, v in national.items()],
        "districts_reported": reported_ao,
        "districts_total": total_ao,
    }
    commentary = get_commentary(state)
    if commentary:
        console.print(commentary)


def cmd_fetch(conn, args):
    from valg.fetcher import get_sftp_client, sync_election_folder, commit_data_repo, push_data_repo, discover_election_folder
    import os

    data_repo = Path(os.getenv("VALG_DATA_REPO", "../valg-data"))
    election_folder = args.election_folder

    try:
        ssh, sftp = get_sftp_client()
    except Exception as e:
        console.print(f"[yellow]SFTP unavailable: {e} — skipping fetch[/yellow]")
        return

    try:
        # Try configured folder first; if it yields nothing, discover by year
        downloaded = sync_election_folder(sftp, election_folder, data_repo)
        if downloaded == 0 and getattr(args, "discover_year", None):
            discovered = discover_election_folder(sftp, args.discover_year)
            if discovered and discovered != election_folder:
                console.print(f"[dim]Configured folder empty, discovered: {discovered}[/dim]")
                election_folder = discovered
                downloaded = sync_election_folder(sftp, election_folder, data_repo)
        console.print(f"Downloaded {downloaded} files from {election_folder}")
    finally:
        sftp.close()
        ssh.close()

    commit_data_repo(data_repo)
    push_data_repo(data_repo)


def cmd_process(conn, args):
    from valg.processor import process_directory
    from valg.plugins import load_plugins
    from datetime import datetime, timezone

    load_plugins()
    snapshot_at = datetime.now(timezone.utc).isoformat()
    data_repo = Path(args.data_repo)

    total = process_directory(conn, data_repo, snapshot_at=snapshot_at)
    console.print(f"Processed {total} rows")


def cmd_validate(conn, args):
    import json
    import os
    from valg.validator import run_validation

    allowed_emails = [e.strip() for e in args.allowed_emails.split(",") if e.strip()]
    verdict = run_validation(args.data_repo, allowed_emails=allowed_emails)
    print(json.dumps(verdict, indent=2))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as fh:
            fh.write(f"unknown_files={json.dumps(verdict['unknown_files'])}\n")


def cmd_check_anomalies(conn, args):
    import subprocess
    from valg.validator import check_anomaly_rate

    threshold = float(os.environ.get("VALG_ANOMALY_THRESHOLD", "0.2"))
    total_files = conn.execute("SELECT COUNT(*) FROM anomalies").fetchone()[0] or 1
    result = check_anomaly_rate(conn, total_files=total_files, threshold=threshold)
    console.print(f"Anomaly rate: {result['rate']*100:.1f}% ({result['anomaly_count']} anomalies) — {'PASS' if result['passed'] else 'FAIL'}")

    if not result["passed"] and os.environ.get("GITHUB_ACTIONS"):
        subprocess.run([
            "gh", "issue", "create",
            "--title", f"High anomaly rate: {result['rate']*100:.1f}%",
            "--body", f"Anomaly count: {result['anomaly_count']}, rate: {result['rate']*100:.1f}% exceeds threshold {threshold*100:.1f}%",
        ])


def cmd_sync(conn, args):
    from valg.processor import process_directory
    from valg.plugins import load_plugins
    from datetime import datetime, timezone

    load_plugins()
    snapshot_at = datetime.now(timezone.utc).isoformat()

    if getattr(args, "fake", False):
        from valg.fake_fetcher import make_election, setup_db, write_wave
        from valg.processor import process_raw_file as _process_file
        import tempfile

        data_dir = args.data_dir or Path(tempfile.mkdtemp(prefix="valg-fake-"))
        election = make_election()

        written = write_wave(data_dir, election, args.wave)
        console.print(f"[dim]Fake wave {args.wave}: {len(written)} files written to {data_dir}[/dim]")
        # Skip kandidatdata files — candidates are fully seeded by setup_db with opstillingskreds_id
        to_process = [p for p in written if not p.name.startswith("kandidat-data")]
        total = sum(_process_file(conn, p, snapshot_at=snapshot_at) for p in to_process)

        if args.wave == 0:
            setup_db(conn, election)
        console.print(f"Processed {total} rows (wave {args.wave})")
        return

    import os

    cmd_fetch(conn, args)
    data_repo = Path(os.getenv("VALG_DATA_REPO", "../valg-data"))
    args_process = argparse.Namespace(data_repo=str(data_repo), db=args.db)
    cmd_process(conn, args_process)


# ── Argument parser ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="valg",
        description="Danish Folketing election results tracker",
    )
    parser.add_argument("--db", type=Path, default=None, help="Path to valg.db")

    sub = parser.add_subparsers(dest="command")

    # fetch
    fetch_p = sub.add_parser("fetch", help="Fetch from SFTP, commit, and push data repo")
    fetch_p.add_argument("--election-folder", required=True)
    fetch_p.add_argument("--discover-year", default=None,
                         help="If configured folder is empty, discover latest folder containing this year (e.g. 2026)")

    # process
    process_p = sub.add_parser("process", help="Process downloaded data into DB")
    process_p.add_argument("--data-repo", required=True)

    # sync
    sync_p = sub.add_parser("sync", help="Fetch from SFTP and process data")
    sync_p.add_argument("--election-folder", default="/Folketingsvalg-1-2024")
    sync_p.add_argument("--interval", type=int, default=0,
                        help="Loop interval in seconds (0 = run once)")
    sync_p.add_argument("--fake", action="store_true",
                        help="Use fake fetcher instead of SFTP (firedrill mode)")
    sync_p.add_argument("--wave", type=int, default=0,
                        help="Fake fetcher wave index (0=setup, 1-3=preliminary, 4-5=final)")
    sync_p.add_argument("--data-dir", type=Path, default=None,
                        help="Override data directory (used with --fake)")

    # status
    sub.add_parser("status", help="Show election status")

    # party
    party_p = sub.add_parser("party", help="Party drilldown")
    party_p.add_argument("party_letter")

    # candidate
    cand_p = sub.add_parser("candidate", help="Candidate tracking")
    cand_p.add_argument("candidate_name")

    # flip
    sub.add_parser("flip", help="Top seat flip margins")

    # kreds
    kreds_p = sub.add_parser("kreds", help="Constituency drilldown")
    kreds_p.add_argument("kreds_name")

    # feed
    feed_p = sub.add_parser("feed", help="Live event feed")
    feed_p.add_argument("--since", default=None)
    feed_p.add_argument("--type", default=None, dest="type")
    feed_p.add_argument("--limit", type=int, default=50)

    # commentary
    sub.add_parser("commentary", help="AI commentary on current state")

    # validate
    validate_p = sub.add_parser("validate", help="Validate data repo integrity")
    validate_p.add_argument("--data-repo", required=True)
    validate_p.add_argument(
        "--allowed-emails",
        default=os.environ.get("VALG_ALLOWED_EMAILS", ""),
        help="Comma-separated list of allowed commit author emails",
    )

    # check-anomalies
    sub.add_parser("check-anomalies", help="Check anomaly rate for current sync cycle")

    return parser


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    from valg.models import DB_PATH
    parser = build_parser()
    args = parser.parse_args()

    db_path = args.db if args.db else DB_PATH
    conn = _get_conn(db_path)

    dispatch = {
        "status": cmd_status,
        "flip": cmd_flip,
        "party": cmd_party,
        "candidate": cmd_candidate,
        "kreds": cmd_kreds,
        "feed": cmd_feed,
        "commentary": cmd_commentary,
        "sync": cmd_sync,
        "fetch": cmd_fetch,
        "process": cmd_process,
        "validate": cmd_validate,
        "check-anomalies": cmd_check_anomalies,
    }

    if args.command is None:
        parser.print_help()
        return

    handler = dispatch.get(args.command)
    if handler:
        handler(conn, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
