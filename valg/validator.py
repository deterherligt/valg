import subprocess
import logging
from pathlib import Path
from valg.plugins import load_plugins, find_plugin

logger = logging.getLogger(__name__)


def check_authors(data_repo, allowed_emails, since_commit=None):
    """Return list of unauthorized commits in data_repo."""
    cmd = ["git", "-C", str(data_repo), "log", "--format=%H %ae"]
    if since_commit:
        cmd.append(f"{since_commit}..HEAD")
    result = subprocess.run(cmd, capture_output=True, text=True)
    unauthorized = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        sha, email = line.split(" ", 1)
        if email not in allowed_emails:
            unauthorized.append({"sha": sha, "email": email})
    return unauthorized


def check_inventory(data_repo):
    """Check which JSON files match known plugins."""
    load_plugins()
    json_files = sorted(Path(data_repo).glob("*.json"))
    unknown = []
    matched = []
    for f in json_files:
        plugin = find_plugin(f.name)
        if plugin:
            matched.append(f.name)
        else:
            unknown.append(f.name)
    return {"matched_files": matched, "unknown_files": unknown}
