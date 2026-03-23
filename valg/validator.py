import json
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


SCHEMA_EXPECTATIONS = {
    "partistemmer": {"expected_type": "dict", "required_keys": ["Valg"]},
    "geografi": {"expected_type": "list"},
    "geografi_ok": {"expected_type": "list"},
    "geografi_ao": {"expected_type": "list"},
    "valgresultater_fv": {"expected_type": "dict", "required_keys": ["Valg"]},
    "valgdeltagelse": {"expected_type": "dict", "required_keys": ["Valg"]},
}


def check_schema(data_repo):
    """Spot-check known files for expected structure."""
    load_plugins()
    violations = []
    for f in Path(data_repo).glob("*.json"):
        plugin = find_plugin(f.name)
        if not plugin:
            continue
        plugin_name = plugin.__name__.rsplit(".", 1)[-1]
        expectation = SCHEMA_EXPECTATIONS.get(plugin_name)
        if not expectation:
            continue
        try:
            data = json.loads(f.read_text())
        except json.JSONDecodeError:
            violations.append({"file": f.name, "issue": "invalid JSON"})
            continue
        expected_type = expectation.get("expected_type", "dict")
        if expected_type == "dict" and not isinstance(data, dict):
            violations.append({"file": f.name, "issue": "expected dict, got " + type(data).__name__})
            continue
        if expected_type == "list" and not isinstance(data, list):
            violations.append({"file": f.name, "issue": "expected list, got " + type(data).__name__})
            continue
        for key in expectation.get("required_keys", []):
            if isinstance(data, dict) and key not in data:
                violations.append({"file": f.name, "issue": f"missing required key: {key}"})
    return violations


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


def run_validation(data_repo, allowed_emails, since_commit=None):
    """Run all pre-process validation checks. Returns verdict dict."""
    unauthorized = check_authors(data_repo, allowed_emails, since_commit)
    inventory = check_inventory(data_repo)
    violations = check_schema(data_repo)

    if unauthorized:
        logger.warning("Unauthorized commits detected: %s", unauthorized)

    status = "pass"
    if inventory["unknown_files"]:
        status = "repair_needed"

    return {
        "status": status,
        "unauthorized_commits": unauthorized,
        "unknown_files": inventory["unknown_files"],
        "schema_violations": violations,
    }
