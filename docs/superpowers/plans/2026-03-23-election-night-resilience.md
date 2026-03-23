# Election Night Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the election night pipeline self-healing, tamper-resistant, and autonomous — running unattended in GitHub Actions with a deterministic validator and an LLM-based plugin repair agent.

**Architecture:** Split the existing `sync` command into `fetch` / `validate` / `process` / `check-anomalies` steps. Add a deterministic validator (`valg/validator.py`) that checks git author allowlist, file inventory, and schema conformance. Add a conditional repair job that invokes Claude Code CLI to write plugins for unknown file formats. Harden valg-data with branch protection.

**Tech Stack:** Python 3.11, SQLite, GitHub Actions, Claude Code CLI, `gh` CLI

**Spec:** `docs/superpowers/specs/2026-03-23-election-night-resilience-design.md`

---

### Task 1: Verify empty-state sync behavior and add explicit test

**Files:**
- Modify: `tests/test_fetcher.py`

Note: `walk_remote()` already catches exceptions internally (line 34-37 of `fetcher.py`) and yields nothing when the remote folder is missing or empty. So `sync_election_folder` already returns 0 gracefully. This task adds explicit regression tests to lock in that behavior, and adds an `--empty-ok` log message for clarity.

- [ ] **Step 1: Write test confirming missing folder returns zero**

```python
def test_sync_missing_folder_returns_zero(tmp_path, mock_sftp):
    """sync_election_folder returns 0 when walk_remote yields nothing (folder missing)."""
    mock_sftp.listdir_attr.side_effect = IOError("No such folder")
    count = sync_election_folder(mock_sftp, "/NoSuchFolder", tmp_path)
    assert count == 0
```

- [ ] **Step 2: Run test to verify it passes (existing behavior)**

Run: `pytest tests/test_fetcher.py::test_sync_missing_folder_returns_zero -v`
Expected: PASS (walk_remote swallows the exception)

- [ ] **Step 3: Write test for empty folder**

```python
def test_sync_empty_folder_returns_zero(tmp_path, mock_sftp):
    """sync_election_folder returns 0 when remote folder exists but is empty."""
    mock_sftp.listdir_attr.return_value = []
    count = sync_election_folder(mock_sftp, "/EmptyFolder", tmp_path)
    assert count == 0
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_fetcher.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_fetcher.py
git commit -m "test: explicit regression tests for empty-state sync"
```

---

### Task 2: Split sync into fetch and process CLI commands

**Files:**
- Modify: `valg/cli.py:231-276` (`cmd_sync`), `valg/cli.py:280-350` (`build_parser`)
- Test: `tests/test_cli.py`

Extract the SFTP fetch and the process_directory calls into separate functions so the workflow can run them independently with a validator step in between.

**Important:** All existing `cmd_*` functions take `(conn, args)` — the dispatch in `main()` at `cli.py:358` calls `handler(conn, args)`. New commands must follow this signature. `cmd_fetch` won't use `conn` but must accept it.

Also note: the existing `cmd_sync` does NOT call `push_data_repo`. The `cmd_fetch` command adds push as a new capability (needed for the workflow to push from within the fetch step).

- [ ] **Step 1: Write test for `cmd_fetch`**

```python
def test_cmd_fetch_calls_sync_commit_push(mock_sftp, tmp_path):
    """cmd_fetch fetches from SFTP, commits, and pushes data repo."""
    args = argparse.Namespace(
        election_folder="/test",
        db=str(tmp_path / "test.db"),
    )
    with patch("valg.cli.get_sftp_client") as mock_client, \
         patch("valg.cli.sync_election_folder", return_value=3) as mock_sync, \
         patch("valg.cli.commit_data_repo") as mock_commit, \
         patch("valg.cli.push_data_repo") as mock_push:
        mock_client.return_value = (MagicMock(), mock_sftp)
        cmd_fetch(None, args)  # conn is unused but required by dispatch
        mock_sync.assert_called_once()
        mock_commit.assert_called_once()
        mock_push.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_cmd_fetch_calls_sync_commit_push -v`
Expected: FAIL (cmd_fetch not defined)

- [ ] **Step 3: Implement cmd_fetch**

New function with signature `cmd_fetch(conn, args)`. Import `push_data_repo` from `valg.fetcher`. The function:
1. Calls `get_sftp_client()`
2. Calls `sync_election_folder(sftp, election_folder, data_repo)`
3. Calls `commit_data_repo(data_repo)`
4. Calls `push_data_repo(data_repo)`

`conn` is accepted but unused (required by dispatch convention).

- [ ] **Step 4: Write test for `cmd_process`**

```python
def test_cmd_process_processes_directory(tmp_path):
    """cmd_process runs process_directory on the data repo."""
    conn = get_connection(str(tmp_path / "test.db"))
    init_db(conn)
    args = argparse.Namespace(
        data_repo=str(tmp_path),
        db=str(tmp_path / "test.db"),
    )
    with patch("valg.cli.process_directory", return_value=42) as mock_proc:
        cmd_process(conn, args)
        mock_proc.assert_called_once()
```

- [ ] **Step 5: Implement cmd_process**

New function with signature `cmd_process(conn, args)`:
1. Calls `load_plugins()`
2. Calls `process_directory(conn, Path(args.data_repo), snapshot_at)`

Uses the `conn` passed in by the dispatch (which already calls `init_db`).

Note: `process_directory` uses non-recursive `glob("*.json")`. This matches existing behavior in `cmd_sync`. If SFTP data lands in subdirectories, this is a pre-existing issue orthogonal to this feature.

- [ ] **Step 6: Register new commands in build_parser**

Add `fetch` and `process` subparsers:
- `fetch`: `--election-folder` (required)
- `process`: `--data-repo` (required)

Add both to the dispatch dict.

- [ ] **Step 7: Refactor cmd_sync to delegate to fetch + process logic**

The existing `sync` command's non-fake path should call the same SFTP logic as `cmd_fetch` followed by the same processing logic as `cmd_process`. The `--fake` path stays in `cmd_sync` unchanged.

- [ ] **Step 8: Run all tests**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 9: Commit**

```bash
git add valg/cli.py tests/test_cli.py
git commit -m "feat: split sync into fetch/process CLI commands"
```

---

### Task 3: Validator module — git author check

**Files:**
- Create: `valg/validator.py`
- Create: `tests/test_validator.py`

Start with the git author allowlist check. This inspects recent commits in the valg-data repo and flags any from unauthorized authors.

- [ ] **Step 1: Write test for authorized commits**

```python
def test_check_authors_passes_for_allowed_email(tmp_path):
    """All commits from allowed author → no unauthorized commits."""
    # Set up a real git repo with one commit from allowed email
    repo = git.Repo.init(tmp_path)
    (tmp_path / "file.txt").write_text("data")
    repo.index.add(["file.txt"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))

    result = check_authors(tmp_path, allowed_emails=["mads@example.com"])
    assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validator.py::test_check_authors_passes_for_allowed_email -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement check_authors**

In `valg/validator.py`:

```python
import subprocess
import logging

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validator.py::test_check_authors_passes_for_allowed_email -v`
Expected: PASS

- [ ] **Step 5: Write test for unauthorized commits**

```python
def test_check_authors_flags_unauthorized_email(tmp_path):
    """Commit from unknown author → returned in unauthorized list."""
    repo = git.Repo.init(tmp_path)
    (tmp_path / "file.txt").write_text("data")
    repo.index.add(["file.txt"])
    repo.index.commit("hack", author=git.Actor("Evil", "evil@bad.com"))

    result = check_authors(tmp_path, allowed_emails=["mads@example.com"])
    assert len(result) == 1
    assert result[0]["email"] == "evil@bad.com"
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_validator.py -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add valg/validator.py tests/test_validator.py
git commit -m "feat: validator git author allowlist check"
```

---

### Task 4: Validator — file inventory check

**Files:**
- Modify: `valg/validator.py`
- Modify: `tests/test_validator.py`

Check which JSON files in the data repo match known plugin MATCH patterns and which are unknown.

- [ ] **Step 1: Write test for all files matched**

```python
def test_check_inventory_all_matched(tmp_path):
    """All files match a plugin → no unknown files."""
    (tmp_path / "Region.json").write_text("{}")
    (tmp_path / "partistemmefordeling-ok1.json").write_text("{}")

    result = check_inventory(tmp_path)
    assert result["unknown_files"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validator.py::test_check_inventory_all_matched -v`
Expected: FAIL (function not found)

- [ ] **Step 3: Implement check_inventory**

```python
from valg.plugins import load_plugins, find_plugin

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validator.py::test_check_inventory_all_matched -v`
Expected: PASS

- [ ] **Step 5: Write test for unknown files**

```python
def test_check_inventory_flags_unknown_files(tmp_path):
    """Files that no plugin matches → listed as unknown."""
    (tmp_path / "Region.json").write_text("{}")
    (tmp_path / "BrandNewFormat.json").write_text("{}")

    result = check_inventory(tmp_path)
    assert "BrandNewFormat.json" in result["unknown_files"]
    assert "Region.json" not in result["unknown_files"]
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_validator.py -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add valg/validator.py tests/test_validator.py
git commit -m "feat: validator file inventory check"
```

---

### Task 5: Validator — schema spot-check

**Files:**
- Modify: `valg/validator.py`
- Modify: `tests/test_validator.py`

For known file types, verify expected top-level keys exist and value types are plausible.

- [ ] **Step 1: Write test for valid schema**

```python
def test_check_schema_passes_valid_partistemmer(tmp_path):
    """Valid partistemmefordeling file passes schema check."""
    data = {"Valg": {"OpstillingskredsId": "ok1", "Partier": [{"PartiId": "A", "Stemmer": 1234}]}}
    (tmp_path / "partistemmefordeling-ok1.json").write_text(json.dumps(data))

    violations = check_schema(tmp_path)
    assert violations == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validator.py::test_check_schema_passes_valid_partistemmer -v`
Expected: FAIL (function not found)

- [ ] **Step 3: Implement check_schema**

Define a `SCHEMA_EXPECTATIONS` dict mapping plugin names to expected key paths and types. The checker opens each matched file, validates top-level structure, and returns a list of violations.

```python
SCHEMA_EXPECTATIONS = {
    "partistemmer": {"required_keys": ["Valg"], "nested": {"Valg": ["OpstillingskredsId", "Partier"]}},
    "geografi": {"required_keys": ["Storkredse"]},
    "valgresultater_fv": {"required_keys": ["Valg"]},
    "valgdeltagelse": {"required_keys": ["Valg"]},
    # ... etc
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
        if not isinstance(data, dict):
            violations.append({"file": f.name, "issue": "expected dict, got " + type(data).__name__})
            continue
        for key in expectation.get("required_keys", []):
            if key not in data:
                violations.append({"file": f.name, "issue": f"missing required key: {key}"})
    return violations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validator.py::test_check_schema_passes_valid_partistemmer -v`
Expected: PASS

- [ ] **Step 5: Write test for invalid schema**

```python
def test_check_schema_flags_missing_key(tmp_path):
    """File missing expected key → violation reported."""
    data = {"WrongKey": {}}
    (tmp_path / "partistemmefordeling-ok1.json").write_text(json.dumps(data))

    violations = check_schema(tmp_path)
    assert len(violations) == 1
    assert "Valg" in violations[0]["issue"]
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_validator.py -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add valg/validator.py tests/test_validator.py
git commit -m "feat: validator schema spot-check"
```

---

### Task 6: Validator — run_validation orchestrator and CLI command

**Files:**
- Modify: `valg/validator.py`
- Modify: `valg/cli.py`
- Modify: `tests/test_validator.py`

Wire the individual checks into a single `run_validation` function and add the `validate` CLI command.

- [ ] **Step 1: Write test for run_validation**

```python
def test_run_validation_returns_verdict(tmp_path):
    """run_validation returns structured verdict."""
    # Create a minimal valid data repo
    repo = git.Repo.init(tmp_path)
    (tmp_path / "Region.json").write_text('{"Storkredse": []}')
    repo.index.add(["Region.json"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))

    verdict = run_validation(tmp_path, allowed_emails=["mads@example.com"])
    assert verdict["status"] in ("pass", "repair_needed")
    assert isinstance(verdict["unauthorized_commits"], list)
    assert isinstance(verdict["unknown_files"], list)
    assert isinstance(verdict["schema_violations"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validator.py::test_run_validation_returns_verdict -v`
Expected: FAIL (function not found)

- [ ] **Step 3: Implement run_validation**

```python
def run_validation(data_repo, allowed_emails, since_commit=None):
    """Run all pre-process validation checks. Returns verdict dict."""
    unauthorized = check_authors(data_repo, allowed_emails, since_commit)
    inventory = check_inventory(data_repo)
    violations = check_schema(data_repo)

    if unauthorized:
        logger.warning("Unauthorized commits detected: %s", unauthorized)
        # Create GitHub issue if running in CI
        _create_issue_if_ci("Unauthorized commits in valg-data", unauthorized)

    status = "pass"
    if inventory["unknown_files"]:
        status = "repair_needed"

    return {
        "status": status,
        "unauthorized_commits": unauthorized,
        "unknown_files": inventory["unknown_files"],
        "schema_violations": violations,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validator.py::test_run_validation_returns_verdict -v`
Expected: PASS

- [ ] **Step 5: Implement cmd_validate and register in CLI**

Add to `valg/cli.py`:
- `cmd_validate(conn, args)` — follows the `(conn, args)` dispatch convention. `conn` is unused. Calls `run_validation`, prints verdict JSON, writes `unknown_files` to `$GITHUB_OUTPUT` if `GITHUB_OUTPUT` env var is set.
- Register `validate` subparser with `--data-repo` (required) and `--allowed-emails` (comma-separated, with default from env var `VALG_ALLOWED_EMAILS`).

Note: The spec mentions a `halt` status but the design says the pipeline never halts (SFTP overwrites tampering). The verdict uses only `pass` and `repair_needed`. Schema violations and unauthorized commits are logged/issued but don't change the status — they're informational since the sync already corrected the data.

- [ ] **Step 6: Write test for GITHUB_OUTPUT integration**

```python
def test_cmd_validate_writes_github_output(tmp_path, monkeypatch):
    """In CI, validate writes unknown_files to $GITHUB_OUTPUT."""
    output_file = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    # ... setup repo with an unknown file
    # ... call cmd_validate
    content = output_file.read_text()
    assert "unknown_files=" in content
```

- [ ] **Step 7: Run all tests**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add valg/validator.py valg/cli.py tests/test_validator.py tests/test_cli.py
git commit -m "feat: validate CLI command with structured verdict output"
```

---

### Task 7: check-anomalies CLI command

**Files:**
- Modify: `valg/validator.py`
- Modify: `valg/cli.py`
- Modify: `tests/test_validator.py`

Post-process anomaly rate check. Queries the anomalies table for the current cycle and creates an issue if the rate exceeds the threshold.

- [ ] **Step 1: Write test for anomaly rate check**

```python
def test_check_anomaly_rate_passes_under_threshold(tmp_path):
    """Anomaly rate below threshold → passes."""
    conn = get_connection(str(tmp_path / "test.db"))
    init_db(conn)
    # Insert 10 files processed, 1 anomaly
    conn.execute("INSERT INTO anomalies (detected_at, filename, anomaly_type, detail) VALUES (datetime('now'), 'f.json', 'unknown_field', 'x')")
    conn.commit()

    result = check_anomaly_rate(conn, total_files=10, threshold=0.2)
    assert result["passed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_validator.py::test_check_anomaly_rate_passes_under_threshold -v`
Expected: FAIL (function not found)

- [ ] **Step 3: Implement check_anomaly_rate**

```python
def check_anomaly_rate(conn, total_files, threshold=0.2):
    """Check if anomaly rate exceeds threshold for this cycle."""
    # Count anomalies from the last minute (current cycle)
    row = conn.execute(
        "SELECT COUNT(*) FROM anomalies WHERE detected_at > datetime('now', '-2 minutes')"
    ).fetchone()
    anomaly_count = row[0]
    rate = anomaly_count / max(total_files, 1)
    passed = rate <= threshold
    if not passed:
        logger.warning("Anomaly rate %.1f%% exceeds threshold %.1f%%", rate * 100, threshold * 100)
    return {"passed": passed, "anomaly_count": anomaly_count, "rate": rate}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_validator.py::test_check_anomaly_rate_passes_under_threshold -v`
Expected: PASS

- [ ] **Step 5: Write test for above-threshold**

```python
def test_check_anomaly_rate_fails_above_threshold(tmp_path):
    """Anomaly rate above threshold → fails."""
    conn = get_connection(str(tmp_path / "test.db"))
    init_db(conn)
    for i in range(5):
        conn.execute("INSERT INTO anomalies (detected_at, filename, anomaly_type, detail) VALUES (datetime('now'), ?, 'parse_failure', 'x')", (f"f{i}.json",))
    conn.commit()

    result = check_anomaly_rate(conn, total_files=10, threshold=0.2)
    assert result["passed"] is False
```

- [ ] **Step 6: Implement cmd_check_anomalies CLI command**

`cmd_check_anomalies(conn, args)` — follows `(conn, args)` dispatch convention. Reads threshold from `VALG_ANOMALY_THRESHOLD` env var (default 0.2). Counts total JSON files processed in this cycle. Calls `check_anomaly_rate(conn, total_files, threshold)`. Creates a GitHub issue via `gh issue create` if it fails and `GITHUB_ACTIONS` env var is set.

Register `check-anomalies` subparser (no additional args needed — uses DB from global `--db` flag).

- [ ] **Step 7: Run all tests**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add valg/validator.py valg/cli.py tests/test_validator.py tests/test_cli.py
git commit -m "feat: check-anomalies post-process CLI command"
```

---

### Task 8: Update GitHub Actions workflow

**Files:**
- Modify: `.github/workflows/sync.yml`

Replace the existing workflow with the split fetch/validate/process/check-anomalies/repair pipeline.

- [ ] **Step 1: Read current workflow**

Read `.github/workflows/sync.yml` to understand current structure.

- [ ] **Step 2: Rewrite sync job**

Replace the single `sync` step with the split pipeline:
1. Checkout code + data repos
2. Setup Python, install deps
3. Configure git for valg-data (Mads's identity)
4. `python -m valg fetch --election-folder $ELECTION_FOLDER`
5. `python -m valg validate --data-repo valg-data --allowed-emails $ALLOWED_EMAILS`
6. `python -m valg process --data-repo valg-data`
7. `python -m valg check-anomalies`
8. Upload unknown files as artifact (conditional)

Set job output: `unknown_files` from validate step.

- [ ] **Step 3: Add repair job**

Conditional job (`if: needs.sync.outputs.unknown_files != '[]'`):
1. Checkout code repo
2. Download unknown files artifact
3. Install Claude Code CLI
4. Run agent with `--allowedTools Read,Write,Edit,Glob,Grep` (no Bash)
5. Run `pytest`
6. Create PR on success, issue on failure

- [ ] **Step 4: Add ANTHROPIC_API_KEY and VALG_ALLOWED_EMAILS to workflow secrets/vars**

Document in the workflow comments which secrets and variables need to be configured:
- Secret: `ANTHROPIC_API_KEY`
- Secret: `DATA_REPO_TOKEN`
- Variable: `ELECTION_FOLDER`
- Variable: `DATA_REPO`
- Variable: `VALG_ALLOWED_EMAILS`

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/sync.yml
git commit -m "feat: split sync workflow into fetch/validate/process/repair pipeline"
```

---

### Task 9: Branch protection ruleset for valg-data

**Files:**
- Create: `scripts/setup-branch-protection.sh`

Script to configure the valg-data repo's branch protection via `gh api`.

- [ ] **Step 1: Write the setup script**

```bash
#!/usr/bin/env bash
# Configure branch protection ruleset for valg-data main branch.
# Restricts push to Mads's account only, disables force-push.
# Usage: ./scripts/setup-branch-protection.sh <owner>/<repo>

set -euo pipefail

REPO="${1:?Usage: $0 owner/repo}"

gh api "repos/${REPO}/rulesets" \
  --method POST \
  --field name="main-protection" \
  --field target="branch" \
  --field enforcement="active" \
  -f 'conditions[ref_name][include][]=refs/heads/main' \
  -f 'rules[][type]=non_fast_forward' \
  -f 'rules[][type]=deletion'

echo "Ruleset created. Now add push bypass actors in GitHub UI:"
echo "  Settings > Rules > Rulesets > main-protection > Bypass actors"
echo "  Add your account as the only bypass actor for push."
```

Note: The `gh api` for rulesets with actor bypass requires complex JSON. The script creates the base ruleset; push restriction actors are best configured in the GitHub UI since the API payload for actor-based bypass is verbose and fragile.

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x scripts/setup-branch-protection.sh
git add scripts/setup-branch-protection.sh
git commit -m "feat: branch protection setup script for valg-data"
```

---

### Task 10: Integration test — full pipeline dry run

**Files:**
- Create: `tests/test_election_night.py`

End-to-end test that simulates the full pipeline: fetch returns data, validate checks it, process ingests it, check-anomalies passes.

- [ ] **Step 1: Write integration test**

```python
def test_election_night_pipeline_happy_path(tmp_path):
    """Full pipeline: fetch → validate → process → check-anomalies."""
    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    repo = git.Repo.init(data_repo)

    # Simulate fetched files (copy from test fixtures)
    # ...copy Region.json, partistemmefordeling, etc. to data_repo...
    repo.index.add([...])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))

    # Validate
    verdict = run_validation(data_repo, allowed_emails=["mads@example.com"])
    assert verdict["status"] == "pass"
    assert verdict["unauthorized_commits"] == []

    # Process
    conn = get_connection(str(tmp_path / "test.db"))
    init_db(conn)
    load_plugins()
    rows = process_directory(conn, data_repo)
    assert rows > 0

    # Check anomalies
    result = check_anomaly_rate(conn, total_files=rows, threshold=0.2)
    assert result["passed"] is True
```

- [ ] **Step 2: Write integration test for tampered data**

```python
def test_election_night_pipeline_detects_unauthorized_commit(tmp_path):
    """Pipeline detects commit from unauthorized author."""
    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    repo = git.Repo.init(data_repo)

    (data_repo / "Region.json").write_text('{"Storkredse": []}')
    repo.index.add(["Region.json"])
    repo.index.commit("legit", author=git.Actor("Mads", "mads@example.com"))

    (data_repo / "hacked.json").write_text('{"votes": 999999}')
    repo.index.add(["hacked.json"])
    repo.index.commit("tamper", author=git.Actor("Evil", "evil@bad.com"))

    verdict = run_validation(data_repo, allowed_emails=["mads@example.com"])
    assert len(verdict["unauthorized_commits"]) == 1
    assert verdict["unauthorized_commits"][0]["email"] == "evil@bad.com"
```

- [ ] **Step 3: Write integration test for unknown file format**

```python
def test_election_night_pipeline_flags_unknown_format(tmp_path):
    """Pipeline flags unknown file format for repair agent."""
    data_repo = tmp_path / "valg-data"
    data_repo.mkdir()
    repo = git.Repo.init(data_repo)

    (data_repo / "BrandNewFormat.json").write_text('{"new": "data"}')
    repo.index.add(["BrandNewFormat.json"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))

    verdict = run_validation(data_repo, allowed_emails=["mads@example.com"])
    assert verdict["status"] == "repair_needed"
    assert "BrandNewFormat.json" in verdict["unknown_files"]
```

- [ ] **Step 4: Run all tests**

Run: `pytest -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_election_night.py
git commit -m "test: election night pipeline integration tests"
```

---

### Task 11: Enable the workflow

**Files:** none (GitHub UI / gh CLI)

- [ ] **Step 1: Verify all secrets and variables are set**

```bash
gh variable list
gh secret list
```

Ensure: `ELECTION_FOLDER`, `DATA_REPO`, `VALG_ALLOWED_EMAILS` vars exist. `DATA_REPO_TOKEN`, `ANTHROPIC_API_KEY` secrets exist.

- [ ] **Step 2: Run the workflow manually to verify**

```bash
gh workflow run sync.yml
gh run watch
```

Expected: workflow completes successfully with "0 files synced" (election folder doesn't exist yet on SFTP).

- [ ] **Step 3: Set up branch protection on valg-data**

```bash
./scripts/setup-branch-protection.sh <owner>/valg-data
```

Then configure push bypass actors in GitHub UI.

- [ ] **Step 4: Verify branch protection works**

Try pushing from a different context or verify the ruleset is active:

```bash
gh api repos/<owner>/valg-data/rulesets --jq '.[].name'
```

Expected: `main-protection` listed.
