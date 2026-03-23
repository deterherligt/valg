import logging
import os
import stat as stat_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import paramiko
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

DATA_REPO = Path(os.getenv("VALG_DATA_REPO", "../valg-data"))


def get_sftp_client() -> tuple:
    """Return (ssh, sftp) connected to the valg SFTP server."""
    host = os.getenv("VALG_SFTP_HOST", "data.valg.dk")
    port = int(os.getenv("VALG_SFTP_PORT", "22"))
    user = os.getenv("VALG_SFTP_USER", "Valg")
    password = os.getenv("VALG_SFTP_PASSWORD", "Valg")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=user, password=password)
    sftp = ssh.open_sftp()
    return ssh, sftp


def discover_election_folder(sftp, year: str) -> Optional[str]:
    """Find the latest election folder on SFTP containing the given year."""
    try:
        attrs = sftp.listdir_attr("/")
    except Exception as e:
        log.warning("Cannot list SFTP root: %s", e)
        return None
    candidates = []
    for attr in attrs:
        if stat_module.S_ISDIR(attr.st_mode) and year in attr.filename:
            candidates.append((attr.st_mtime or 0, "/" + attr.filename))
    if not candidates:
        log.info("No election folder found containing '%s'", year)
        return None
    candidates.sort(reverse=True)
    winner = candidates[0][1]
    log.info("Discovered election folder: %s", winner)
    return winner


def walk_remote(sftp, remote_path: str):
    """Yield (remote_path, size, mtime) for all .json files under remote_path."""
    try:
        attrs = sftp.listdir_attr(remote_path)
    except Exception as e:
        log.warning("Cannot list %s: %s", remote_path, e)
        return

    for attr in attrs:
        full_path = f"{remote_path}/{attr.filename}".replace("//", "/")
        if stat_module.S_ISDIR(attr.st_mode):
            yield from walk_remote(sftp, full_path)
        elif attr.filename.endswith(".json"):
            yield (full_path, attr.st_size, attr.st_mtime)


def download_file(sftp, remote_path: str, local_path: Path) -> None:
    """Download a single file from SFTP to local_path."""
    local_path.parent.mkdir(parents=True, exist_ok=True)
    sftp.get(remote_path, str(local_path))
    log.debug("Downloaded %s", remote_path)


def sync_election_folder(
    sftp,
    remote_election_folder: str,
    data_repo: Path,
) -> int:
    """
    Sync changed JSON files from remote_election_folder to data_repo.
    Uses mtime comparison to skip unchanged files.
    Returns the number of files downloaded.
    """
    downloaded = 0
    for remote_path, size, remote_mtime in walk_remote(sftp, remote_election_folder):
        # Build local path: strip the election folder prefix
        relative = remote_path.lstrip("/")
        # Remove the election folder prefix from the relative path
        parts = relative.split("/")
        # Find where the election folder ends and use the rest
        local_path = data_repo / Path(*parts[1:]) if len(parts) > 1 else data_repo / parts[0]

        if local_path.exists() and remote_mtime is not None:
            local_mtime = local_path.stat().st_mtime
            if local_mtime >= remote_mtime:
                log.debug("Skipping unchanged %s", remote_path)
                continue

        download_file(sftp, remote_path, local_path)
        downloaded += 1

    log.info("Sync complete: %d files downloaded", downloaded)
    return downloaded


def commit_data_repo(data_repo: Path, message: Optional[str] = None) -> bool:
    """
    Git add -A and commit in data_repo.
    Returns True if a commit was made, False if nothing to commit.
    """
    import subprocess

    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(data_repo),
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        log.info("Nothing to commit in data repo")
        return False

    if message is None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        message = f"sync {now}"

    subprocess.run(["git", "add", "-A"], cwd=str(data_repo), check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(data_repo),
        check=True,
        capture_output=True,
    )
    log.info("Committed data repo: %s", message)
    return True


def push_data_repo(data_repo: Path) -> bool:
    """
    Push data repo to remote. Returns True on success, False on failure.
    Failure is logged but does not raise — local repo is the source of truth.
    """
    import subprocess

    result = subprocess.run(
        ["git", "push"],
        cwd=str(data_repo),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.warning("Push failed (will retry next cycle): %s", result.stderr.strip())
        return False
    log.info("Pushed data repo to remote")
    return True


def run_sync_loop(
    election_folder: str,
    data_repo: Path,
    interval: int = 300,
) -> None:
    """
    Main sync loop. Runs indefinitely, sleeping `interval` seconds between cycles.
    """
    import time

    log.info("Starting sync loop: %s every %ds", election_folder, interval)
    while True:
        try:
            ssh, sftp = get_sftp_client()
            try:
                downloaded = sync_election_folder(sftp, election_folder, data_repo)
                if downloaded > 0:
                    commit_data_repo(data_repo)
                    push_data_repo(data_repo)
            finally:
                sftp.close()
                ssh.close()
        except Exception as e:
            log.error("Sync cycle failed: %s", e)
        time.sleep(interval)
