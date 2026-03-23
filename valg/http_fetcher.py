# valg/http_fetcher.py
"""
Fetches election JSON files from a public GitHub repo via HTTPS.
No SFTP, no git, no credentials required.
"""
import json
import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

REPO = "deterherligt/valg-data"
BRANCH = "master"
_CACHE = ".sha_cache.json"


def _make_request(url: str) -> urllib.request.Request:
    req = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    return req


def fetch_tree(repo: str = REPO, branch: str = BRANCH) -> list[dict]:
    """Return list of {path, sha} for all .json blobs in the repo."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    with urllib.request.urlopen(_make_request(url), timeout=10) as resp:
        data = json.loads(resp.read())
    return [
        f for f in data.get("tree", [])
        if f.get("type") == "blob" and f["path"].endswith(".json")
    ]


def download_file(path: str, dest: Path, repo: str = REPO, branch: str = BRANCH) -> None:
    """Download a single file from GitHub raw."""
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{urllib.parse.quote(path)}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(_make_request(url), timeout=10) as resp:
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
