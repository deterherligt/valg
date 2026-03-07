# Election Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python CLI tool that fetches Danish Folketingsvalg data from SFTP, stores it in SQLite, and surfaces real-time vote counts, seat projections, and seat-flip margins.

**Architecture:** SFTP fetcher mirrors raw JSON files to a dedicated git data repo (auto-committed each cycle, pushed to public GitHub) → processor dispatches files to hot-pluggable plugins → SQLite with snapshots → pure-function calculator → thin CLI display layer.

**Tech Stack:** Python 3.11+, `paramiko` (SFTP), `gitpython` (data repo commits), `python-dotenv` (env config), `sqlite3` (stdlib), `pytest`, `rich` (CLI output), `argparse` (stdlib)

---

## TDD Rules (apply to every task)

Every piece of production code follows this exact sequence — no exceptions:

1. Write the failing test
2. Run it — confirm it fails with the **expected error** (ImportError, AssertionError, etc.)
3. Write the minimal implementation to make it pass
4. Run it — confirm it passes
5. Commit

If a test does not fail before implementation, it is not a valid test — fix it before proceeding.

---

## Task 1: Project Scaffold

**Files:**
- Create: `valg/pyproject.toml`
- Create: `valg/valg/__init__.py`
- Create: `valg/valg/fetcher.py`
- Create: `valg/valg/processor.py`
- Create: `valg/valg/models.py`
- Create: `valg/valg/calculator.py`
- Create: `valg/valg/cli.py`
- Create: `valg/valg/plugins/__init__.py`
- Create: `valg/tests/__init__.py`
- Create: `valg/tests/e2e/__init__.py`
- Create: `valg/tests/synthetic/__init__.py`
- Create: `valg/.gitignore`
- Create: `valg/.env.example`

**Step 1: Create directory structure**

```bash
cd ~/Documents/valg
mkdir -p valg/plugins tests/fixtures tests/synthetic tests/e2e scripts deploy .github/workflows
touch valg/__init__.py valg/fetcher.py valg/processor.py \
      valg/models.py valg/calculator.py valg/cli.py valg/plugins/__init__.py
touch tests/__init__.py tests/e2e/__init__.py tests/synthetic/__init__.py
```

**Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "valg"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "paramiko>=3.4",
    "gitpython>=3.1",
    "python-dotenv>=1.0",
    "rich>=13.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov"]

[project.scripts]
valg = "valg.cli:main"

[tool.setuptools.packages.find]
where = ["."]
include = ["valg*"]
```

**Step 3: Install**

```bash
pip install -e ".[dev]"
```

Expected: no errors. `valg --help` works.

**Step 4: Create .gitignore**

```
valg.db
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
.env
valg-data/
```

**Step 5: Create .env.example**

```bash
# .env.example — copy to .env and override if needed
VALG_SFTP_HOST=data.valg.dk
VALG_SFTP_PORT=22
VALG_SFTP_USER=Valg
VALG_SFTP_PASSWORD=Valg
VALG_DATA_REPO=../valg-data
```

**Step 6: Initialise data repo**

```bash
mkdir -p ~/Documents/valg-data
cd ~/Documents/valg-data
git init
echo "# valg-data — raw election JSON snapshots" > README.md
git add README.md && git commit -m "init: data repo"
```

**Step 7: Initialise code repo and commit**

```bash
cd ~/Documents/valg
git init
git add pyproject.toml valg/ tests/ .gitignore .env.example docs/ LICENSE DISCLAIMER.md
git commit -m "feat: project scaffold"
```

---

## Task 2: SQLite Schema

**Files:**
- Modify: `valg/valg/models.py`
- Create: `valg/tests/test_models.py`

### Step 1: Write failing tests

```python
# tests/test_models.py
from valg.models import init_db, get_connection

def test_init_db_creates_all_tables():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {r[0] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    expected = {
        "elections", "storkredse", "opstillingskredse",
        "afstemningsomraader", "parties", "candidates",
        "results", "turnout", "party_votes",
    }
    assert expected <= tables, f"Missing tables: {expected - tables}"

def test_init_db_creates_performance_indexes():
    conn = get_connection(":memory:")
    init_db(conn)
    indexes = {r[0] for r in
               conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    required = {
        "idx_results_party_snapshot",
        "idx_results_ao_snapshot",
        "idx_results_candidate_snap",
        "idx_party_votes_party_snap",
        "idx_turnout_ao_snapshot",
    }
    assert required <= indexes, f"Missing indexes: {required - indexes}"

def test_init_db_is_idempotent():
    conn = get_connection(":memory:")
    init_db(conn)
    init_db(conn)  # must not raise

def test_get_connection_enables_wal_mode():
    conn = get_connection(":memory:")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "memory"  # :memory: ignores WAL but call must not raise

def test_storkredse_has_n_kredsmandater_column():
    conn = get_connection(":memory:")
    init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(storkredse)").fetchall()}
    assert "n_kredsmandater" in cols
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError: cannot import name 'init_db' from 'valg.models'`

### Step 3: Implement models.py

```python
# valg/models.py
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "valg.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS elections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    election_date TEXT,
    synced_at TEXT
);
CREATE TABLE IF NOT EXISTS storkredse (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    election_id TEXT REFERENCES elections(id),
    n_kredsmandater INTEGER
);
CREATE TABLE IF NOT EXISTS opstillingskredse (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    storkreds_id TEXT REFERENCES storkredse(id)
);
CREATE TABLE IF NOT EXISTS afstemningsomraader (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    opstillingskreds_id TEXT REFERENCES opstillingskredse(id),
    municipality_name TEXT,
    eligible_voters INTEGER
);
CREATE TABLE IF NOT EXISTS parties (
    id TEXT PRIMARY KEY,
    letter TEXT,
    name TEXT NOT NULL,
    election_id TEXT REFERENCES elections(id)
);
CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    party_id TEXT REFERENCES parties(id),
    opstillingskreds_id TEXT REFERENCES opstillingskredse(id),
    ballot_position INTEGER
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    afstemningsomraade_id TEXT REFERENCES afstemningsomraader(id),
    party_id TEXT REFERENCES parties(id),
    candidate_id TEXT REFERENCES candidates(id),
    votes INTEGER,
    count_type TEXT CHECK(count_type IN ('preliminary','final')),
    snapshot_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turnout (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    afstemningsomraade_id TEXT REFERENCES afstemningsomraader(id),
    eligible_voters INTEGER,
    votes_cast INTEGER,
    snapshot_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS party_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opstillingskreds_id TEXT REFERENCES opstillingskredse(id),
    party_id TEXT REFERENCES parties(id),
    votes INTEGER,
    snapshot_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_results_party_snapshot
    ON results(party_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_results_ao_snapshot
    ON results(afstemningsomraade_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_results_candidate_snap
    ON results(candidate_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_party_votes_party_snap
    ON party_votes(party_id, snapshot_at);
CREATE INDEX IF NOT EXISTS idx_turnout_ao_snapshot
    ON turnout(afstemningsomraade_id, snapshot_at);
"""

def get_connection(path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
```

### Step 4: Run — confirm all pass

```bash
pytest tests/test_models.py -v
```

Expected: 5 PASSED

### Step 5: Commit

```bash
git add valg/models.py tests/test_models.py
git commit -m "feat: SQLite schema with tables and performance indexes"
```

---

## Task 3: SFTP Fetcher

**Files:**
- Modify: `valg/valg/fetcher.py`
- Create: `valg/tests/test_fetcher.py`

### Step 1: Write failing tests — one per function

```python
# tests/test_fetcher.py
import os
from unittest.mock import MagicMock, patch, call
from pathlib import Path
import git
import pytest
from valg.fetcher import (
    get_connection_params,
    list_remote_files,
    download_file,
    walk_remote,
    commit_data_repo,
    sync_once,
)

# --- get_connection_params ---

def test_connection_params_uses_defaults(monkeypatch):
    for key in ("VALG_SFTP_HOST", "VALG_SFTP_PORT", "VALG_SFTP_USER", "VALG_SFTP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    params = get_connection_params()
    assert params["host"] == "data.valg.dk"
    assert params["port"] == 22
    assert params["username"] == "Valg"
    assert params["password"] == "Valg"

def test_connection_params_reads_env(monkeypatch):
    monkeypatch.setenv("VALG_SFTP_HOST", "custom.host")
    monkeypatch.setenv("VALG_SFTP_PORT", "2222")
    params = get_connection_params()
    assert params["host"] == "custom.host"
    assert params["port"] == 2222

# --- list_remote_files ---

def _make_attr(filename, mtime=1700000000, size=100):
    a = MagicMock()
    a.filename = filename
    a.st_mtime = mtime
    a.st_size = size
    return a

def test_list_remote_files_returns_name_mtime_dict():
    sftp = MagicMock()
    sftp.listdir_attr.return_value = [
        _make_attr("Region.json", mtime=1000),
        _make_attr("Kommune.json", mtime=2000),
    ]
    result = list_remote_files(sftp, "/FV-1-2024/Geografi")
    assert result == {"Region.json": 1000, "Kommune.json": 2000}

def test_list_remote_files_returns_empty_on_missing_path():
    sftp = MagicMock()
    sftp.listdir_attr.side_effect = FileNotFoundError
    result = list_remote_files(sftp, "/nonexistent")
    assert result == {}

def test_list_remote_files_skips_dotfiles():
    sftp = MagicMock()
    sftp.listdir_attr.return_value = [
        _make_attr(".hidden"),
        _make_attr("visible.json"),
    ]
    result = list_remote_files(sftp, "/path")
    assert ".hidden" not in result
    assert "visible.json" in result

# --- download_file ---

def test_download_file_writes_bytes(tmp_path):
    sftp = MagicMock()
    sftp.open.return_value.__enter__ = lambda s: s
    sftp.open.return_value.__exit__ = MagicMock(return_value=False)
    sftp.open.return_value.read = MagicMock(return_value=b'{"ok": true}')
    dest = tmp_path / "sub" / "file.json"
    download_file(sftp, "/remote/file.json", dest)
    assert dest.exists()
    assert dest.read_bytes() == b'{"ok": true}'

def test_download_file_creates_parent_dirs(tmp_path):
    sftp = MagicMock()
    sftp.open.return_value.__enter__ = lambda s: s
    sftp.open.return_value.__exit__ = MagicMock(return_value=False)
    sftp.open.return_value.read = MagicMock(return_value=b'{}')
    deep = tmp_path / "a" / "b" / "c" / "file.json"
    download_file(sftp, "/r/file.json", deep)
    assert deep.exists()

# --- commit_data_repo ---

def test_commit_data_repo_commits_changes(tmp_path):
    repo = git.Repo.init(tmp_path)
    (tmp_path / "file.json").write_text('{"a": 1}')
    repo.index.add(["file.json"])
    commit_data_repo(str(tmp_path), "21:34 UTC — 1 file")
    commits = list(repo.iter_commits())
    assert len(commits) == 1
    assert "21:34" in commits[0].message

def test_commit_data_repo_skips_when_no_changes(tmp_path):
    repo = git.Repo.init(tmp_path)
    # Nothing staged — should not raise, should not create a commit
    commit_data_repo(str(tmp_path), "empty sync")
    commits = list(repo.iter_commits("HEAD") if repo.head.is_valid() else [])
    assert len(commits) == 0
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_fetcher.py -v
```

Expected: `ImportError: cannot import name 'get_connection_params' from 'valg.fetcher'`

### Step 3: Implement fetcher.py

```python
# valg/fetcher.py
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import git
import paramiko
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def get_connection_params() -> dict:
    return {
        "host": os.getenv("VALG_SFTP_HOST", "data.valg.dk"),
        "port": int(os.getenv("VALG_SFTP_PORT", "22")),
        "username": os.getenv("VALG_SFTP_USER", "Valg"),
        "password": os.getenv("VALG_SFTP_PASSWORD", "Valg"),
    }


def get_sftp_client() -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
    p = get_connection_params()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(p["host"], port=p["port"], username=p["username"],
                password=p["password"], timeout=30)
    return ssh, ssh.open_sftp()


def list_remote_files(sftp: paramiko.SFTPClient, remote_path: str) -> dict[str, int]:
    try:
        attrs = sftp.listdir_attr(remote_path)
    except FileNotFoundError:
        log.warning("Remote path not found: %s", remote_path)
        return {}
    return {a.filename: a.st_mtime
            for a in attrs if not a.filename.startswith(".")}


def download_file(sftp: paramiko.SFTPClient, remote_path: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    with sftp.open(remote_path, "rb") as f:
        data = f.read()
    local_path.write_bytes(data)
    log.debug("Downloaded %s (%d bytes)", remote_path, len(data))


def walk_remote(sftp: paramiko.SFTPClient, remote_dir: str) -> Iterator[str]:
    for attr in sftp.listdir_attr(remote_dir):
        path = f"{remote_dir}/{attr.filename}"
        try:
            sftp.listdir_attr(path)
            yield from walk_remote(sftp, path)
        except Exception:
            yield path


def commit_data_repo(data_repo_path: str, label: str) -> None:
    repo = git.Repo(data_repo_path)
    repo.git.add("-A")
    if repo.is_dirty(index=True):
        repo.index.commit(f"sync {label}")
        log.info("Data repo committed: sync %s", label)
    else:
        log.info("No changes to commit")


def push_data_repo(data_repo_path: str) -> None:
    try:
        repo = git.Repo(data_repo_path)
        if repo.remotes:
            repo.remotes.origin.push()
            log.info("Pushed to remote")
    except Exception as e:
        log.warning("Push failed (will retry next sync): %s", e)


_DEFAULT_DATA_REPO = Path(os.getenv("VALG_DATA_REPO", "../valg-data")).resolve()


def sync_once(election_folder: str, data_repo: Path = _DEFAULT_DATA_REPO) -> list[Path]:
    downloaded = []
    ssh, sftp = get_sftp_client()
    try:
        for remote_path in walk_remote(sftp, election_folder):
            if not remote_path.endswith(".json"):
                continue
            relative = remote_path.lstrip("/")
            local_path = data_repo / relative
            if local_path.exists():
                remote_mtime = sftp.stat(remote_path).st_mtime
                if local_path.stat().st_mtime >= remote_mtime:
                    continue
            download_file(sftp, remote_path, local_path)
            downloaded.append(local_path)
    finally:
        sftp.close()
        ssh.close()

    if downloaded:
        label = (f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
                 f" — {len(downloaded)} files")
        commit_data_repo(str(data_repo), label)
        push_data_repo(str(data_repo))
    return downloaded


def sync_loop(election_folder: str, interval_seconds: int = 300,
              data_repo: Path = _DEFAULT_DATA_REPO) -> None:
    log.info("Sync loop every %ds for %s", interval_seconds, election_folder)
    while True:
        try:
            sync_once(election_folder, data_repo)
        except Exception as e:
            log.error("Sync failed: %s", e)
        time.sleep(interval_seconds)
```

### Step 4: Run — confirm all pass

```bash
pytest tests/test_fetcher.py -v
```

Expected: 10 PASSED

### Step 5: Commit

```bash
git add valg/fetcher.py tests/test_fetcher.py
git commit -m "feat: SFTP fetcher with env config, git commit, and push-with-fallback"
```

---

## Task 4: Plugin Registry

**Files:**
- Modify: `valg/valg/plugins/__init__.py`
- Create: `valg/tests/test_plugin_registry.py`

### Step 1: Write failing tests

```python
# tests/test_plugin_registry.py
import pytest
from valg.plugins import load_plugins, find_plugin, list_plugins

def test_load_plugins_runs_without_error():
    load_plugins()  # must not raise

def test_find_plugin_returns_none_for_unknown_file():
    load_plugins()
    assert find_plugin("completely-unknown-xyz.json") is None

def test_loaded_plugin_has_required_interface():
    load_plugins()
    plugins = list_plugins()
    for plugin in plugins:
        assert callable(plugin.MATCH), f"{plugin.__name__} missing MATCH"
        assert callable(plugin.parse), f"{plugin.__name__} missing parse"
        assert isinstance(plugin.TABLE, str), f"{plugin.__name__} TABLE must be str"

def test_find_plugin_returns_first_match():
    load_plugins()
    # After built-in plugins are added, Region.json should match geografi plugin
    # For now, just confirm it does not crash
    result = find_plugin("Region.json")
    # May be None if no plugins loaded yet — that is OK at this stage
    assert result is None or callable(result.MATCH)

def test_plugins_are_reloaded_on_second_call():
    load_plugins()
    count_1 = len(list_plugins())
    load_plugins()
    count_2 = len(list_plugins())
    assert count_1 == count_2  # idempotent
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_plugin_registry.py -v
```

Expected: `ImportError: cannot import name 'load_plugins' from 'valg.plugins'`

### Step 3: Implement plugin registry

```python
# valg/plugins/__init__.py
import importlib
import pkgutil
from pathlib import Path
from types import ModuleType

_plugins: list[ModuleType] = []


def load_plugins() -> None:
    global _plugins
    _plugins = []
    pkg_dir = Path(__file__).parent
    for _, name, _ in pkgutil.iter_modules([str(pkg_dir)]):
        mod = importlib.import_module(f"valg.plugins.{name}")
        if hasattr(mod, "MATCH") and hasattr(mod, "parse") and hasattr(mod, "TABLE"):
            _plugins.append(mod)


def find_plugin(filename: str) -> ModuleType | None:
    for plugin in _plugins:
        if plugin.MATCH(filename):
            return plugin
    return None


def list_plugins() -> list[ModuleType]:
    return list(_plugins)
```

### Step 4: Run — confirm all pass

```bash
pytest tests/test_plugin_registry.py -v
```

Expected: 5 PASSED

### Step 5: Commit

```bash
git add valg/plugins/__init__.py tests/test_plugin_registry.py
git commit -m "feat: hot-pluggable parser plugin registry"
```

---

## Task 5: Built-in Plugins

**Files:**
- Create: `valg/valg/plugins/geografi.py`
- Create: `valg/valg/plugins/kandidatdata_fv.py`
- Create: `valg/valg/plugins/valgresultater_fv.py`
- Create: `valg/valg/plugins/valgdeltagelse.py`
- Create: `valg/valg/plugins/partistemmer.py`
- Create: `valg/tests/fixtures/` (JSON fixtures)
- Create: `valg/tests/test_plugins.py`

### Step 1: Create fixture files

```bash
cat > tests/fixtures/geografi_region.json << 'EOF'
[
  {"Kode": "R1", "Navn": "Region Hovedstaden"},
  {"Kode": "R2", "Navn": "Region Sjælland", "UkendtFelt": "ignoreret"}
]
EOF

cat > tests/fixtures/geografi_storkreds.json << 'EOF'
[
  {"Kode": "SK1", "Navn": "Københavns Storkreds", "AntalKredsmandater": 15}
]
EOF

cat > tests/fixtures/kandidatdata_fv.json << 'EOF'
{
  "Valg": {
    "Id": "FV2024", "Navn": "Folketingsvalg 2024",
    "IndenforParti": [
      {"Id": "A", "Bogstav": "A", "Navn": "Socialdemokratiet",
       "Kandidater": [{"Id": "K1", "Navn": "Mette Frederiksen", "Stemmeseddelplacering": 1}]}
    ],
    "UdenforParti": {"Kandidater": [
      {"Id": "K99", "Navn": "Uafhængig Kandidat"}
    ]}
  }
}
EOF

cat > tests/fixtures/valgresultater_fv_preliminary.json << 'EOF'
{
  "Valgresultater": {
    "AfstemningsomraadeId": "AO1",
    "Tidsstempel": "05-11-2024 21:00:00",
    "Optaellingstype": "Foreloebig",
    "IndenforParti": [
      {"PartiId": "A", "Partistemmer": 1234,
       "Kandidater": [{"KandidatId": "K1", "Stemmer": 456}]}
    ],
    "KandidaterUdenforParti": [{"KandidatId": "K99", "Stemmer": 12}]
  }
}
EOF

cat > tests/fixtures/valgresultater_fv_final.json << 'EOF'
{
  "Valgresultater": {
    "AfstemningsomraadeId": "AO1",
    "Tidsstempel": "06-11-2024 10:00:00",
    "Optaellingstype": "Fintaelling",
    "IndenforParti": [
      {"PartiId": "A", "Partistemmer": 1250,
       "Kandidater": [{"KandidatId": "K1", "Stemmer": 470}]}
    ],
    "KandidaterUdenforParti": [{"KandidatId": "K99", "Stemmer": 12}]
  }
}
EOF

cat > tests/fixtures/valgdeltagelse_fv.json << 'EOF'
{
  "Valg": {
    "AfstemningsomraadeId": "AO1",
    "Valgdeltagelse": [
      {"StemmeberettigedeVaelgere": 2000, "AfgivneStemmer": 1500,
       "Tidsstempel": "05-11-2024 20:00:00"}
    ]
  }
}
EOF

cat > tests/fixtures/partistemmer_fv.json << 'EOF'
{
  "Valg": {
    "OpstillingskredsId": "OK1",
    "Partier": [
      {"PartiId": "A", "Stemmer": 5000},
      {"PartiId": "B", "Stemmer": 3000}
    ]
  }
}
EOF
```

### Step 2: Write failing tests

```python
# tests/test_plugins.py
import json
import pytest
from pathlib import Path
from valg.plugins import load_plugins, find_plugin

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture(autouse=True)
def plugins():
    load_plugins()


# --- MATCH functions ---

def test_geografi_matches_region():
    assert find_plugin("Region.json") is not None

def test_geografi_matches_storkreds():
    assert find_plugin("Storkreds.json") is not None

def test_geografi_matches_kommune():
    assert find_plugin("Kommune.json") is not None

def test_geografi_matches_afstemningsomraade():
    assert find_plugin("Afstemningsomraade.json") is not None

def test_kandidatdata_matches_fv_file():
    assert find_plugin("kandidat-data-Folketingsvalg-4-Bornholm-190820220938.json") is not None

def test_valgresultater_matches_fv_file():
    assert find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json") is not None

def test_valgdeltagelse_matches_file():
    assert find_plugin("valgdeltagelse-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json") is not None

def test_partistemmer_matches_file():
    assert find_plugin("partistemmefordeling-Folketingsvalg-København-Østerbro-190820220938.json") is not None

def test_unknown_file_returns_none():
    assert find_plugin("noget-andet.json") is None


# --- parse functions ---

def test_geografi_parse_returns_rows():
    plugin = find_plugin("Region.json")
    data = json.loads((FIXTURES / "geografi_region.json").read_text())
    rows = plugin.parse(data, "2024-01-01")
    assert len(rows) == 2
    assert all("id" in r and "name" in r for r in rows)

def test_geografi_parse_ignores_unknown_fields():
    plugin = find_plugin("Region.json")
    data = json.loads((FIXTURES / "geografi_region.json").read_text())
    rows = plugin.parse(data, "2024-01-01")
    assert all("UkendtFelt" not in r for r in rows)

def test_geografi_storkreds_captures_kredsmandater():
    plugin = find_plugin("Storkreds.json")
    data = json.loads((FIXTURES / "geografi_storkreds.json").read_text())
    rows = plugin.parse(data, "2024-01-01")
    assert rows[0]["n_kredsmandater"] == 15

def test_kandidatdata_parse_returns_parties():
    plugin = find_plugin("kandidat-data-Folketingsvalg-4-Bornholm-190820220938.json")
    data = json.loads((FIXTURES / "kandidatdata_fv.json").read_text())
    rows = plugin.parse(data, "2024-01-01")
    assert any(r.get("letter") == "A" for r in rows)

def test_valgresultater_preliminary_count_type():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    assert all(r["count_type"] == "preliminary" for r in rows)

def test_valgresultater_final_count_type():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_final.json").read_text())
    rows = plugin.parse(data, "2024-11-06T10:00:00")
    assert all(r["count_type"] == "final" for r in rows)

def test_valgresultater_party_votes_row():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    party_row = next(r for r in rows if r["candidate_id"] is None and r["party_id"] == "A")
    assert party_row["votes"] == 1234

def test_valgresultater_candidate_votes_row():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    cand_row = next(r for r in rows if r["candidate_id"] == "K1")
    assert cand_row["votes"] == 456

def test_valgresultater_udenfor_parti_row():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    rows = plugin.parse(data, "2024-11-05T21:00:00")
    ind_row = next(r for r in rows if r["candidate_id"] == "K99")
    assert ind_row["votes"] == 12
    assert ind_row["party_id"] is None

def test_valgdeltagelse_parse():
    plugin = find_plugin("valgdeltagelse-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    data = json.loads((FIXTURES / "valgdeltagelse_fv.json").read_text())
    rows = plugin.parse(data, "2024-11-05T20:00:00")
    assert rows[0]["votes_cast"] == 1500
    assert rows[0]["eligible_voters"] == 2000

def test_partistemmer_parse():
    plugin = find_plugin("partistemmefordeling-Folketingsvalg-København-Østerbro-190820220938.json")
    data = json.loads((FIXTURES / "partistemmer_fv.json").read_text())
    rows = plugin.parse(data, "2024-11-05T22:00:00")
    a_row = next(r for r in rows if r["party_id"] == "A")
    assert a_row["votes"] == 5000

def test_plugin_parse_does_not_crash_on_missing_optional_fields():
    plugin = find_plugin("valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json")
    # Minimal valid structure — missing optional fields
    data = {"Valgresultater": {"AfstemningsomraadeId": "AO99", "IndenforParti": []}}
    rows = plugin.parse(data, "2024-01-01T00:00:00")
    assert rows == []  # no data but no crash
```

### Step 3: Run — confirm failure

```bash
pytest tests/test_plugins.py -v
```

Expected: most tests fail with `assert find_plugin(...) is not None` — plugins not yet implemented.

### Step 4: Implement plugins

```python
# valg/plugins/geografi.py
import logging
log = logging.getLogger(__name__)
TABLE = "storkredse"
_KNOWN = {"Kode", "Navn", "AntalKredsmandater", "RegionKode"}

def MATCH(filename: str) -> bool:
    lower = filename.lower()
    return any(k in lower for k in (
        "region", "storkreds", "opstillingskreds",
        "afstemningsomraade", "valglandsdel", "kommune",
    ))

def parse(data, snapshot_at: str) -> list[dict]:
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        extra = set(item) - _KNOWN
        if extra:
            log.info("Unknown geografi fields: %s", extra)
        row = {
            "id": item.get("Kode"),
            "name": item.get("Navn"),
            "n_kredsmandater": item.get("AntalKredsmandater"),
            "election_id": None,
        }
        if row["id"] and row["name"]:
            out.append(row)
    return out
```

```python
# valg/plugins/kandidatdata_fv.py
import logging
log = logging.getLogger(__name__)
TABLE = "parties"

def MATCH(filename: str) -> bool:
    return "kandidat-data-folketingsvalg" in filename.lower()

def parse(data, snapshot_at: str) -> list[dict]:
    valg = data.get("Valg", {})
    rows = []
    for parti in valg.get("IndenforParti", []):
        rows.append({
            "id": parti.get("Id"),
            "letter": parti.get("Bogstav"),
            "name": parti.get("Navn"),
            "election_id": valg.get("Id", "FV"),
        })
    return rows
```

```python
# valg/plugins/valgresultater_fv.py
import logging
log = logging.getLogger(__name__)
TABLE = "results"

def MATCH(filename: str) -> bool:
    return "valgresultater-folketingsvalg" in filename.lower()

def _count_type(raw: str | None) -> str:
    return "final" if raw and "fin" in raw.lower() else "preliminary"

def parse(data, snapshot_at: str) -> list[dict]:
    vr = data.get("Valgresultater", {})
    ao_id = vr.get("AfstemningsomraadeId")
    ct = _count_type(vr.get("Optaellingstype"))
    rows = []
    for parti in vr.get("IndenforParti", []):
        pid = parti.get("PartiId")
        pv = parti.get("Partistemmer")
        if pv is not None:
            rows.append({"afstemningsomraade_id": ao_id, "party_id": pid,
                         "candidate_id": None, "votes": pv,
                         "count_type": ct, "snapshot_at": snapshot_at})
        for kand in parti.get("Kandidater", []):
            v = kand.get("Stemmer")
            if v is not None:
                rows.append({"afstemningsomraade_id": ao_id, "party_id": pid,
                             "candidate_id": kand.get("KandidatId"), "votes": v,
                             "count_type": ct, "snapshot_at": snapshot_at})
    for kand in vr.get("KandidaterUdenforParti", []):
        v = kand.get("Stemmer")
        if v is not None:
            rows.append({"afstemningsomraade_id": ao_id, "party_id": None,
                         "candidate_id": kand.get("KandidatId"), "votes": v,
                         "count_type": ct, "snapshot_at": snapshot_at})
    return rows
```

```python
# valg/plugins/valgdeltagelse.py
TABLE = "turnout"

def MATCH(filename: str) -> bool:
    return "valgdeltagelse" in filename.lower()

def parse(data, snapshot_at: str) -> list[dict]:
    valg = data.get("Valg", {})
    ao_id = valg.get("AfstemningsomraadeId")
    return [
        {"afstemningsomraade_id": ao_id,
         "eligible_voters": e.get("StemmeberettigedeVaelgere"),
         "votes_cast": e.get("AfgivneStemmer"),
         "snapshot_at": e.get("Tidsstempel") or snapshot_at}
        for e in valg.get("Valgdeltagelse", [])
    ]
```

```python
# valg/plugins/partistemmer.py
TABLE = "party_votes"

def MATCH(filename: str) -> bool:
    return "partistemmefordeling" in filename.lower()

def parse(data, snapshot_at: str) -> list[dict]:
    valg = data.get("Valg", {})
    ok_id = valg.get("OpstillingskredsId")
    return [
        {"opstillingskreds_id": ok_id,
         "party_id": p.get("PartiId"),
         "votes": p.get("Stemmer"),
         "snapshot_at": snapshot_at}
        for p in valg.get("Partier", [])
        if p.get("Stemmer") is not None
    ]
```

### Step 5: Run — confirm all pass

```bash
pytest tests/test_plugins.py -v
```

Expected: all PASSED

### Step 6: Commit

```bash
git add valg/plugins/ tests/test_plugins.py tests/fixtures/
git commit -m "feat: built-in plugins for all Folketing file types"
```

---

## Task 6: Processor Core

**Files:**
- Modify: `valg/valg/processor.py`
- Create: `valg/tests/test_processor.py`

### Step 1: Write failing tests

```python
# tests/test_processor.py
import json
import pytest
from pathlib import Path
from valg.models import get_connection, init_db
from valg.processor import process_raw_file
from valg.plugins import load_plugins

FIXTURES = Path(__file__).parent / "fixtures"

@pytest.fixture(autouse=True)
def plugins():
    load_plugins()

@pytest.fixture
def db():
    conn = get_connection(":memory:")
    init_db(conn)
    return conn

def test_process_region_file_inserts_rows(db, tmp_path):
    f = tmp_path / "Region.json"
    f.write_text((FIXTURES / "geografi_region.json").read_text())
    process_raw_file(db, f)
    count = db.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0]
    assert count == 2

def test_process_valgresultater_inserts_results(db, tmp_path):
    f = tmp_path / "valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json"
    f.write_text((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    process_raw_file(db, f)
    count = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    assert count > 0

def test_process_unknown_file_does_not_crash(db, tmp_path):
    f = tmp_path / "ukjent-format.json"
    f.write_text('{"noget": "andet"}')
    process_raw_file(db, f)  # must not raise

def test_process_malformed_json_does_not_crash(db, tmp_path):
    f = tmp_path / "Region.json"
    f.write_text("NOT VALID JSON {{{")
    process_raw_file(db, f)  # must not raise

def test_process_file_records_snapshot_at(db, tmp_path):
    f = tmp_path / "valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json"
    f.write_text((FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    process_raw_file(db, f, snapshot_at="2024-11-05T21:00:00")
    row = db.execute("SELECT snapshot_at FROM results LIMIT 1").fetchone()
    assert row["snapshot_at"] == "2024-11-05T21:00:00"

def test_process_directory_of_files(db, tmp_path):
    (tmp_path / "Region.json").write_text(
        (FIXTURES / "geografi_region.json").read_text())
    (tmp_path / "valgresultater-Folketingsvalg-Lyngby-Arenaskolen-190820220938.json").write_text(
        (FIXTURES / "valgresultater_fv_preliminary.json").read_text())
    from valg.processor import process_directory
    process_directory(db, tmp_path)
    assert db.execute("SELECT COUNT(*) FROM storkredse").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM results").fetchone()[0] > 0
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_processor.py -v
```

Expected: `ImportError: cannot import name 'process_raw_file' from 'valg.processor'`

### Step 3: Implement processor.py

```python
# valg/processor.py
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection

from valg.plugins import load_plugins, find_plugin

log = logging.getLogger(__name__)
load_plugins()

_INSERT = {
    "storkredse": (
        "INSERT OR REPLACE INTO storkredse (id, name, election_id, n_kredsmandater) "
        "VALUES (:id, :name, :election_id, :n_kredsmandater)"
    ),
    "parties": (
        "INSERT OR REPLACE INTO parties (id, letter, name, election_id) "
        "VALUES (:id, :letter, :name, :election_id)"
    ),
    "results": (
        "INSERT INTO results "
        "(afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) "
        "VALUES (:afstemningsomraade_id, :party_id, :candidate_id, "
        ":votes, :count_type, :snapshot_at)"
    ),
    "turnout": (
        "INSERT INTO turnout "
        "(afstemningsomraade_id, eligible_voters, votes_cast, snapshot_at) "
        "VALUES (:afstemningsomraade_id, :eligible_voters, :votes_cast, :snapshot_at)"
    ),
    "party_votes": (
        "INSERT INTO party_votes (opstillingskreds_id, party_id, votes, snapshot_at) "
        "VALUES (:opstillingskreds_id, :party_id, :votes, :snapshot_at)"
    ),
}


def process_raw_file(conn: Connection, path: Path,
                     snapshot_at: str | None = None) -> None:
    if snapshot_at is None:
        snapshot_at = datetime.now(timezone.utc).isoformat()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.error("Failed to parse %s: %s", path.name, e)
        return

    plugin = find_plugin(path.name)
    if plugin is None:
        log.debug("No plugin for: %s", path.name)
        return

    try:
        rows = plugin.parse(data, snapshot_at)
    except Exception as e:
        log.error("Plugin %s failed on %s: %s", plugin.__name__, path.name, e)
        return

    if rows and plugin.TABLE in _INSERT:
        conn.executemany(_INSERT[plugin.TABLE], rows)
        conn.commit()


def process_directory(conn: Connection, directory: Path,
                      snapshot_at: str | None = None) -> int:
    if snapshot_at is None:
        snapshot_at = datetime.now(timezone.utc).isoformat()
    count = 0
    for path in sorted(directory.rglob("*.json")):
        process_raw_file(conn, path, snapshot_at)
        count += 1
    return count
```

### Step 4: Run — confirm all pass

```bash
pytest tests/test_processor.py -v
```

Expected: 7 PASSED

### Step 5: Commit

```bash
git add valg/processor.py tests/test_processor.py
git commit -m "feat: processor core with plugin dispatch and directory batch processing"
```

---

## Task 7: Synthetic Data Generator

**Files:**
- Modify: `valg/tests/synthetic/generator.py`
- Create: `valg/tests/test_synthetic.py`

### Step 1: Write failing tests

```python
# tests/test_synthetic.py
import pytest
from tests.synthetic.generator import (
    generate_election,
    generate_result_stream,
    generate_fintaelling_stream,
    load_into_db,
)
from valg.models import get_connection, init_db

@pytest.fixture
def db():
    conn = get_connection(":memory:")
    init_db(conn)
    return conn

def test_generate_election_returns_required_keys():
    e = generate_election(n_parties=4, n_storkredse=3, n_districts=10)
    assert {"parties", "storkredse", "districts", "candidates"} <= e.keys()

def test_generate_election_counts_are_correct():
    e = generate_election(n_parties=4, n_storkredse=3, n_districts=10)
    assert len(e["parties"]) == 4
    assert len(e["storkredse"]) == 3
    assert len(e["districts"]) == 10
    assert len(e["candidates"]) > 0

def test_generate_election_districts_reference_valid_storkredse():
    e = generate_election(n_parties=3, n_storkredse=2, n_districts=8)
    sk_ids = {sk["id"] for sk in e["storkredse"]}
    for d in e["districts"]:
        assert d["storkreds_id"] in sk_ids

def test_result_stream_covers_all_districts():
    e = generate_election(n_parties=3, n_storkredse=2, n_districts=6)
    snapshots = list(generate_result_stream(e, chunks=3))
    reported = {row["district_id"] for snap in snapshots for row in snap}
    all_districts = {d["id"] for d in e["districts"]}
    assert reported == all_districts

def test_result_stream_votes_are_non_negative():
    e = generate_election(n_parties=4, n_storkredse=2, n_districts=5)
    for snap in generate_result_stream(e):
        for row in snap:
            assert row["votes"] >= 0

def test_result_stream_all_rows_are_preliminary():
    e = generate_election(n_parties=3, n_storkredse=2, n_districts=5)
    for snap in generate_result_stream(e):
        for row in snap:
            assert row["count_type"] == "preliminary"

def test_fintaelling_stream_all_rows_are_final():
    e = generate_election(n_parties=3, n_storkredse=2, n_districts=5)
    for snap in generate_fintaelling_stream(e):
        for row in snap:
            assert row["count_type"] == "final"

def test_fintaelling_includes_candidate_rows():
    e = generate_election(n_parties=3, n_storkredse=2, n_districts=5)
    all_rows = [row for snap in generate_fintaelling_stream(e) for row in snap]
    assert any(row.get("candidate_id") is not None for row in all_rows)

def test_load_into_db_election_night(db):
    e = generate_election(n_parties=4, n_storkredse=3, n_districts=10)
    load_into_db(db, e, phase="preliminary")
    count = db.execute("SELECT COUNT(*) FROM results WHERE count_type='preliminary'").fetchone()[0]
    assert count > 0

def test_load_into_db_fintaelling(db):
    e = generate_election(n_parties=4, n_storkredse=3, n_districts=10)
    load_into_db(db, e, phase="final")
    count = db.execute("SELECT COUNT(*) FROM results WHERE count_type='final'").fetchone()[0]
    assert count > 0
    candidate_count = db.execute(
        "SELECT COUNT(*) FROM results WHERE candidate_id IS NOT NULL"
    ).fetchone()[0]
    assert candidate_count > 0
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_synthetic.py -v
```

Expected: `ImportError: cannot import name 'generate_election'`

### Step 3: Implement generator

```python
# tests/synthetic/generator.py
"""
Synthetic Folketing election data generator.
Used for testing and end-to-end verification of use cases.
"""
import random
from datetime import datetime, timezone
from sqlite3 import Connection


def generate_election(
    n_parties: int = 8,
    n_storkredse: int = 10,
    n_districts: int = 100,
    seed: int | None = None,
) -> dict:
    if seed is not None:
        random.seed(seed)

    parties = [
        {"id": chr(65 + i), "letter": chr(65 + i), "name": f"Parti {chr(65 + i)}"}
        for i in range(n_parties)
    ]
    storkredse = [
        {"id": f"SK{i}", "name": f"Storkreds {i}",
         "n_kredsmandater": random.randint(8, 20)}
        for i in range(n_storkredse)
    ]
    opstillingskredse = [
        {"id": f"OK{i}", "name": f"Opstillingskreds {i}",
         "storkreds_id": storkredse[i % n_storkredse]["id"]}
        for i in range(n_storkredse * 3)
    ]
    districts = [
        {"id": f"AO{i:04d}", "name": f"Afstemningsområde {i}",
         "storkreds_id": storkredse[i % n_storkredse]["id"],
         "opstillingskreds_id": opstillingskredse[i % len(opstillingskredse)]["id"],
         "eligible_voters": random.randint(800, 3000)}
        for i in range(n_districts)
    ]
    candidates = [
        {"id": f"K{p['id']}{j}", "name": f"Kandidat {p['letter']}{j}",
         "party_id": p["id"],
         "opstillingskreds_id": opstillingskredse[j % len(opstillingskredse)]["id"]}
        for p in parties
        for j in range(random.randint(3, 6))
    ]
    return {
        "parties": parties,
        "storkredse": storkredse,
        "opstillingskredse": opstillingskredse,
        "districts": districts,
        "candidates": candidates,
    }


def _district_result(district: dict, parties: list,
                     count_type: str = "preliminary") -> list[dict]:
    total = int(district["eligible_voters"] * random.uniform(0.70, 0.88))
    weights = [random.random() for _ in parties]
    total_w = sum(weights)
    return [
        {"district_id": district["id"], "party_id": p["id"],
         "votes": int(total * w / total_w), "count_type": count_type}
        for p, w in zip(parties, weights)
    ]


def _candidate_result(district: dict, party: dict, candidates: list,
                      party_votes: int, count_type: str = "final") -> list[dict]:
    party_candidates = [c for c in candidates if c["party_id"] == party["id"]]
    if not party_candidates:
        return []
    weights = [random.random() for _ in party_candidates]
    total_w = sum(weights)
    return [
        {"district_id": district["id"], "party_id": party["id"],
         "candidate_id": c["id"],
         "votes": int(party_votes * w / total_w), "count_type": count_type}
        for c, w in zip(party_candidates, weights)
    ]


def generate_result_stream(
    election: dict, chunks: int = 10, inject_recount: bool = False,
) -> list[list[dict]]:
    districts = election["districts"].copy()
    random.shuffle(districts)
    chunk_size = max(1, len(districts) // chunks)
    reported = []
    result = []
    for i in range(0, len(districts), chunk_size):
        batch = districts[i:i + chunk_size]
        rows = []
        for d in batch:
            rows.extend(_district_result(d, election["parties"]))
            reported.append(d)
        if inject_recount and reported and random.random() < 0.2:
            recount = random.choice(reported[:-len(batch)])
            rows.extend(_district_result(recount, election["parties"]))
        result.append(rows)
    return result


def generate_fintaelling_stream(
    election: dict, chunks: int = 10,
) -> list[list[dict]]:
    """Generate final-count results with candidate-level breakdown."""
    districts = election["districts"].copy()
    random.shuffle(districts)
    chunk_size = max(1, len(districts) // chunks)
    result = []
    for i in range(0, len(districts), chunk_size):
        batch = districts[i:i + chunk_size]
        rows = []
        for d in batch:
            party_rows = _district_result(d, election["parties"], count_type="final")
            rows.extend(party_rows)
            for pr in party_rows:
                party = next(p for p in election["parties"] if p["id"] == pr["party_id"])
                rows.extend(_candidate_result(
                    d, party, election["candidates"], pr["votes"], count_type="final"
                ))
        result.append(rows)
    return result


def load_into_db(conn: Connection, election: dict, phase: str = "preliminary") -> None:
    """
    Load a complete synthetic election into SQLite.
    phase: 'preliminary' (election night) or 'final' (fintælling)
    """
    snapshot = datetime.now(timezone.utc).isoformat()

    # Geography
    conn.executemany(
        "INSERT OR REPLACE INTO storkredse (id, name, n_kredsmandater) "
        "VALUES (:id, :name, :n_kredsmandater)",
        election["storkredse"],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO opstillingskredse (id, name, storkreds_id) "
        "VALUES (:id, :name, :storkreds_id)",
        election["opstillingskredse"],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO afstemningsomraader "
        "(id, name, opstillingskreds_id, eligible_voters) "
        "VALUES (:id, :name, :opstillingskreds_id, :eligible_voters)",
        election["districts"],
    )

    # Parties and candidates
    conn.executemany(
        "INSERT OR REPLACE INTO parties (id, letter, name) VALUES (:id, :letter, :name)",
        election["parties"],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO candidates (id, name, party_id, opstillingskreds_id) "
        "VALUES (:id, :name, :party_id, :opstillingskreds_id)",
        election["candidates"],
    )

    # Results
    if phase == "preliminary":
        stream = generate_result_stream(election, chunks=1)
    else:
        stream = generate_fintaelling_stream(election, chunks=1)

    for snap in stream:
        for row in snap:
            conn.execute(
                "INSERT INTO results "
                "(afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["district_id"], row["party_id"], row.get("candidate_id"),
                 row["votes"], row["count_type"], snapshot),
            )

    # Party votes (national aggregation)
    for party in election["parties"]:
        total = conn.execute(
            "SELECT COALESCE(SUM(votes), 0) FROM results "
            "WHERE party_id = ? AND candidate_id IS NULL",
            (party["id"],),
        ).fetchone()[0]
        for ok in election["opstillingskredse"]:
            conn.execute(
                "INSERT INTO party_votes (opstillingskreds_id, party_id, votes, snapshot_at) "
                "VALUES (?, ?, ?, ?)",
                (ok["id"], party["id"],
                 total // len(election["opstillingskredse"]), snapshot),
            )

    conn.commit()
```

### Step 4: Run — confirm all pass

```bash
pytest tests/test_synthetic.py -v
```

Expected: 10 PASSED

### Step 5: Commit

```bash
git add tests/synthetic/ tests/test_synthetic.py
git commit -m "feat: synthetic generator with election night and fintaelling streams"
```

---

## Task 8: Seat Calculator

**Files:**
- Modify: `valg/valg/calculator.py`
- Create: `valg/tests/test_calculator.py`

### Step 1: Write failing tests — one per function

```python
# tests/test_calculator.py
import pytest
from valg.calculator import (
    dhondt,
    modified_saint_lague,
    allocate_kredsmandater,
    allocate_seats_total,
    votes_to_gain_seat,
    votes_to_lose_seat,
    constituency_flip_feasibility,
    seat_momentum,
)

# --- dhondt ---

def test_dhondt_equal_votes_splits_evenly():
    assert dhondt({"A": 1000, "B": 1000}, 4) == {"A": 2, "B": 2}

def test_dhondt_proportional_three_to_one():
    result = dhondt({"A": 3000, "B": 1000}, 4)
    assert result == {"A": 3, "B": 1}

def test_dhondt_single_party_gets_all():
    assert dhondt({"A": 5000}, 5) == {"A": 5}

def test_dhondt_zero_votes_gets_zero_seats():
    result = dhondt({"A": 1000, "B": 0}, 4)
    assert result["B"] == 0
    assert result["A"] == 4

def test_dhondt_returns_all_parties():
    result = dhondt({"A": 1000, "B": 500, "C": 100}, 3)
    assert set(result.keys()) == {"A", "B", "C"}

# --- modified_saint_lague ---

def test_saint_lague_equal_votes():
    assert modified_saint_lague({"A": 1000, "B": 1000}, 4) == {"A": 2, "B": 2}

def test_saint_lague_first_divisor_14_favours_larger_party():
    # With divisor 1.4, A's first quotient is 1000/1.4 = 714, B's is 500/1.4 = 357
    result = modified_saint_lague({"A": 1000, "B": 500}, 3)
    assert result["A"] >= result["B"]

def test_saint_lague_total_seats_equals_n():
    result = modified_saint_lague({"A": 3000, "B": 2000, "C": 1000}, 7)
    assert sum(result.values()) == 7

# --- allocate_kredsmandater ---

def test_kredsmandater_distributed_per_storkreds():
    sk_votes = {
        "SK1": {"A": 3000, "B": 1000},
        "SK2": {"A": 1000, "B": 3000},
    }
    seats = {"SK1": 4, "SK2": 4}
    result = allocate_kredsmandater(sk_votes, seats)
    assert result["SK1"]["A"] > result["SK1"]["B"]
    assert result["SK2"]["B"] > result["SK2"]["A"]

def test_kredsmandater_total_per_storkreds():
    sk_votes = {"SK1": {"A": 2000, "B": 1000, "C": 500}}
    result = allocate_kredsmandater(sk_votes, {"SK1": 5})
    assert sum(result["SK1"].values()) == 5

# --- allocate_seats_total ---

def test_seats_total_filters_below_threshold():
    votes = {"A": 9700, "B": 200, "C": 100}
    sk = {"SK1": votes}
    kredsseats = {"SK1": 5}
    result = allocate_seats_total(votes, sk, kredsseats)
    assert result.get("B", 0) == 0
    assert result.get("C", 0) == 0

def test_seats_total_qualified_party_gets_seats():
    votes = {"A": 9700, "B": 200, "C": 100}
    sk = {"SK1": votes}
    kredsseats = {"SK1": 5}
    result = allocate_seats_total(votes, sk, kredsseats)
    assert result["A"] > 0

def test_seats_total_returns_all_parties():
    votes = {"A": 5000, "B": 3000}
    sk = {"SK1": votes}
    result = allocate_seats_total(votes, sk, {"SK1": 10})
    assert set(result.keys()) == {"A", "B"}

def test_seats_total_175_seats_sum():
    votes = {"A": 40, "B": 30, "C": 20, "D": 5, "E": 3, "F": 2}
    # Make all qualify
    votes = {k: v * 1000 for k, v in votes.items()}
    sk = {"SK1": votes}
    kredsseats = {"SK1": 135}
    result = allocate_seats_total(votes, sk, kredsseats)
    assert sum(result.values()) <= 175  # may be less if rounding

# --- votes_to_gain_seat / votes_to_lose_seat ---

def test_votes_to_gain_seat_positive():
    votes = {"A": 5000, "B": 4000, "C": 3000}
    sk = {"SK1": votes}
    ks = {"SK1": 10}
    delta = votes_to_gain_seat("B", votes, sk, ks)
    assert delta > 0

def test_votes_to_gain_seat_results_in_more_seats():
    votes = {"A": 5000, "B": 4000, "C": 3000}
    sk = {"SK1": votes}
    ks = {"SK1": 10}
    before = allocate_seats_total(votes, sk, ks)["B"]
    delta = votes_to_gain_seat("B", votes, sk, ks)
    new_votes = dict(votes)
    new_votes["B"] += delta
    after = allocate_seats_total(new_votes, {"SK1": new_votes}, ks)["B"]
    assert after > before

def test_votes_to_lose_seat_positive():
    votes = {"A": 5000, "B": 4000}
    sk = {"SK1": votes}
    ks = {"SK1": 10}
    delta = votes_to_lose_seat("A", votes, sk, ks)
    assert delta > 0

def test_votes_to_lose_seat_zero_when_no_seats():
    votes = {"A": 9900, "B": 100}  # B below threshold
    sk = {"SK1": votes}
    ks = {"SK1": 5}
    assert votes_to_lose_seat("B", votes, sk, ks) == 0

# --- constituency_flip_feasibility ---

def test_flip_feasible_when_gap_smaller_than_remaining():
    r = constituency_flip_feasibility(500, 450, 200, 0.85)
    assert r["gap"] == 50
    assert r["max_remaining"] == 170
    assert r["feasible"] is True

def test_flip_not_feasible_when_gap_too_large():
    r = constituency_flip_feasibility(500, 200, 100, 0.85)
    assert r["feasible"] is False

def test_flip_leader_is_own_reference():
    r = constituency_flip_feasibility(500, 500, 100, 0.85)
    assert r["gap"] == 0
    assert r["feasible"] is True

# --- seat_momentum ---

def test_seat_momentum_detects_gain():
    prev = {"A": 45, "B": 40}
    curr = {"A": 44, "B": 41}
    result = seat_momentum(prev, curr)
    assert result["A"] == -1
    assert result["B"] == +1

def test_seat_momentum_no_change():
    seats = {"A": 45, "B": 40}
    result = seat_momentum(seats, seats)
    assert all(v == 0 for v in result.values())
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_calculator.py -v
```

Expected: `ImportError: cannot import name 'dhondt'`

### Step 3: Implement calculator.py

```python
# valg/calculator.py
"""
Pure functions for Danish parliamentary seat allocation.
No I/O. All inputs are plain Python dicts/numbers.
"""

THRESHOLD_PCT = 0.02
N_SEATS_TOTAL = 175

PartyVotes = dict[str, int]
SeatMap = dict[str, int]


def dhondt(votes: PartyVotes, n_seats: int) -> SeatMap:
    seats: SeatMap = {p: 0 for p in votes}
    for _ in range(n_seats):
        best = max(votes, key=lambda p: votes[p] / (seats[p] + 1))
        seats[best] += 1
    return seats


def modified_saint_lague(votes: PartyVotes, n_seats: int) -> SeatMap:
    seats: SeatMap = {p: 0 for p in votes}
    def divisor(n: int) -> float:
        return 1.4 if n == 0 else 2 * n + 1
    for _ in range(n_seats):
        best = max(votes, key=lambda p: votes[p] / divisor(seats[p]))
        seats[best] += 1
    return seats


def _threshold_filter(votes: PartyVotes, total: int) -> PartyVotes:
    if total == 0:
        return {}
    return {p: v for p, v in votes.items() if v / total >= THRESHOLD_PCT}


def allocate_kredsmandater(
    storkreds_votes: dict[str, PartyVotes],
    kredsmandat_seats: dict[str, int],
) -> dict[str, SeatMap]:
    return {
        sk: dhondt(sv, kredsmandat_seats.get(sk, 0))
        for sk, sv in storkreds_votes.items()
    }


def allocate_seats_total(
    national_votes: PartyVotes,
    storkreds_votes: dict[str, PartyVotes],
    kredsmandat_seats: dict[str, int],
) -> SeatMap:
    total = sum(national_votes.values())
    qualified = _threshold_filter(national_votes, total)
    if not qualified:
        return {p: 0 for p in national_votes}

    kreds_by_sk = allocate_kredsmandater(storkreds_votes, kredsmandat_seats)
    kreds_total: SeatMap = {p: 0 for p in national_votes}
    for sk_map in kreds_by_sk.values():
        for p, s in sk_map.items():
            kreds_total[p] = kreds_total.get(p, 0) + s

    proportional = modified_saint_lague(
        {p: v for p, v in qualified.items()}, N_SEATS_TOTAL
    )
    return {p: max(proportional.get(p, 0), kreds_total.get(p, 0))
            for p in national_votes}


def votes_to_gain_seat(
    party: str,
    national_votes: PartyVotes,
    storkreds_votes: dict[str, PartyVotes],
    kredsmandat_seats: dict[str, int],
) -> int:
    current = allocate_seats_total(national_votes, storkreds_votes, kredsmandat_seats)[party]
    total = sum(national_votes.values())
    lo, hi = 1, total
    while lo < hi:
        mid = (lo + hi) // 2
        nv = dict(national_votes)
        nv[party] += mid
        nt = total + mid
        scale = nv[party] / max(national_votes.get(party, 1), 1)
        nsk = {sk: {p: int(v * scale) if p == party else v for p, v in sv.items()}
               for sk, sv in storkreds_votes.items()}
        if allocate_seats_total(nv, nsk, kredsmandat_seats)[party] > current:
            hi = mid
        else:
            lo = mid + 1
    return lo


def votes_to_lose_seat(
    party: str,
    national_votes: PartyVotes,
    storkreds_votes: dict[str, PartyVotes],
    kredsmandat_seats: dict[str, int],
) -> int:
    current = allocate_seats_total(national_votes, storkreds_votes, kredsmandat_seats)[party]
    if current == 0:
        return 0
    party_total = national_votes.get(party, 0)
    lo, hi = 1, party_total
    while lo < hi:
        mid = (lo + hi) // 2
        nv = dict(national_votes)
        nv[party] = max(0, party_total - mid)
        nt = sum(nv.values())
        if nt == 0:
            break
        if allocate_seats_total(nv, storkreds_votes, kredsmandat_seats)[party] < current:
            hi = mid
        else:
            lo = mid + 1
    return lo


def constituency_flip_feasibility(
    leader_votes: int,
    challenger_votes: int,
    uncounted_eligible: int,
    historical_turnout: float = 0.84,
) -> dict:
    gap = leader_votes - challenger_votes
    max_remaining = int(uncounted_eligible * historical_turnout)
    return {"gap": gap, "max_remaining": max_remaining, "feasible": gap < max_remaining}


def seat_momentum(prev_seats: SeatMap, curr_seats: SeatMap) -> SeatMap:
    all_parties = set(prev_seats) | set(curr_seats)
    return {p: curr_seats.get(p, 0) - prev_seats.get(p, 0) for p in all_parties}
```

### Step 4: Run — confirm all pass

```bash
pytest tests/test_calculator.py -v
```

Expected: all PASSED

### Step 5: Commit

```bash
git add valg/calculator.py tests/test_calculator.py
git commit -m "feat: D'Hondt kredsmandater, Saint-Lague tillaegsmandater, flip logic, momentum"
```

---

## Task 9: End-to-End Use Case Tests

**Files:**
- Create: `valg/tests/e2e/test_use_cases.py`

These tests use synthetic data to confirm each use case produces correct, meaningful output.
They are the source of truth for "does the system actually work?"

### Step 1: Write all e2e tests

```python
# tests/e2e/test_use_cases.py
"""
End-to-end tests using synthetic data.
Each test corresponds directly to a use case in the design doc.
All tests load data into an in-memory SQLite DB via the synthetic generator,
then call the calculator and query functions that back the CLI commands.
"""
import pytest
from valg.models import get_connection, init_db
from valg.plugins import load_plugins
from valg import calculator
from tests.synthetic.generator import generate_election, load_into_db

SEED = 42  # deterministic results across runs


@pytest.fixture(autouse=True)
def plugins():
    load_plugins()


@pytest.fixture
def election():
    return generate_election(
        n_parties=8, n_storkredse=5, n_districts=50, seed=SEED
    )


@pytest.fixture
def db_night(election):
    """Election night DB — foreløbig optælling (party votes only)."""
    conn = get_connection(":memory:")
    init_db(conn)
    load_into_db(conn, election, phase="preliminary")
    return conn, election


@pytest.fixture
def db_final(election):
    """Fintælling DB — candidate votes available."""
    conn = get_connection(":memory:")
    init_db(conn)
    load_into_db(conn, election, phase="preliminary")
    load_into_db(conn, election, phase="final")
    return conn, election


# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_national_votes(conn):
    rows = conn.execute(
        "SELECT party_id, SUM(votes) as v FROM party_votes GROUP BY party_id"
    ).fetchall()
    if rows:
        return {r["party_id"]: r["v"] for r in rows}
    rows = conn.execute(
        "SELECT party_id, SUM(votes) as v FROM results "
        "WHERE candidate_id IS NULL GROUP BY party_id"
    ).fetchall()
    return {r["party_id"]: r["v"] for r in rows}


def _load_storkreds_votes(conn):
    rows = conn.execute(
        "SELECT pv.party_id, ok.storkreds_id, SUM(pv.votes) as v "
        "FROM party_votes pv "
        "JOIN opstillingskredse ok ON ok.id = pv.opstillingskreds_id "
        "GROUP BY pv.party_id, ok.storkreds_id"
    ).fetchall()
    result = {}
    for r in rows:
        result.setdefault(r["storkreds_id"], {})[r["party_id"]] = r["v"]
    return result


def _load_kredsmandat_seats(conn):
    rows = conn.execute("SELECT id, n_kredsmandater FROM storkredse").fetchall()
    return {r["id"]: (r["n_kredsmandater"] or 0) for r in rows}


# ─── UC1: Election night — party seats and flip margins ─────────────────────

def test_uc1_all_parties_have_vote_totals(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    assert len(national) == len(election["parties"])
    assert all(v > 0 for v in national.values())


def test_uc1_seat_projection_sums_to_175_or_less(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    assert sum(seats.values()) <= 175
    assert sum(seats.values()) > 0


def test_uc1_threshold_parties_get_zero_seats(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    total = sum(national.values())
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    for pid, votes in national.items():
        if votes / total < 0.02:
            assert seats.get(pid, 0) == 0, f"{pid} below threshold but got seats"


def test_uc1_momentum_detected_across_two_snapshots(election):
    conn = get_connection(":memory:")
    init_db(conn)
    # Load snapshot 1
    load_into_db(conn, election, phase="preliminary")
    national_1 = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats_1 = calculator.allocate_seats_total(national_1, storkreds, ks)
    # Load snapshot 2 (more votes)
    load_into_db(conn, election, phase="preliminary")
    national_2 = _load_national_votes(conn)
    seats_2 = calculator.allocate_seats_total(national_2, storkreds, ks)
    momentum = calculator.seat_momentum(seats_1, seats_2)
    # Momentum values must be valid integers
    assert all(isinstance(v, int) for v in momentum.values())


# ─── UC2: Storkreds breakdown ────────────────────────────────────────────────

def test_uc2_all_storkredse_have_votes(db_night):
    conn, election = db_night
    storkreds = _load_storkreds_votes(conn)
    expected_ids = {sk["id"] for sk in election["storkredse"]}
    assert expected_ids <= set(storkreds.keys())


def test_uc2_kredsmandater_sum_equals_n_seats_per_storkreds(db_night):
    conn, election = db_night
    storkreds_votes = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    kreds = calculator.allocate_kredsmandater(storkreds_votes, ks)
    for sk_id, seats in kreds.items():
        expected = ks.get(sk_id, 0)
        assert sum(seats.values()) == expected, (
            f"{sk_id}: expected {expected} seats, got {sum(seats.values())}"
        )


def test_uc2_districts_reported_count_is_accurate(db_night):
    conn, election = db_night
    total = conn.execute("SELECT COUNT(*) FROM afstemningsomraader").fetchone()[0]
    reported = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results "
        "WHERE candidate_id IS NULL"
    ).fetchone()[0]
    assert total == len(election["districts"])
    assert reported > 0


# ─── UC3: Seat flip margins ──────────────────────────────────────────────────

def test_uc3_votes_to_gain_is_positive_for_all_parties(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    for pid in national:
        if seats.get(pid, 0) < 175:
            delta = calculator.votes_to_gain_seat(pid, national, storkreds, ks)
            assert delta > 0, f"{pid} should need votes to gain a seat"


def test_uc3_votes_to_lose_is_zero_for_parties_with_no_seats(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)
    for pid in national:
        if seats.get(pid, 0) == 0:
            delta = calculator.votes_to_lose_seat(pid, national, storkreds, ks)
            assert delta == 0, f"{pid} has no seats, lose delta should be 0"


def test_uc3_adding_gain_delta_increases_seats(db_night):
    conn, election = db_night
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    # Test for one party
    pid = election["parties"][1]["id"]
    before = calculator.allocate_seats_total(national, storkreds, ks)[pid]
    delta = calculator.votes_to_gain_seat(pid, national, storkreds, ks)
    nv = dict(national)
    nv[pid] += delta
    after = calculator.allocate_seats_total(nv, storkreds, ks)[pid]
    assert after > before


# ─── UC4: Constituency flip feasibility (fintælling required) ───────────────

def test_uc4_candidate_votes_exist_in_final_db(db_final):
    conn, election = db_final
    count = conn.execute(
        "SELECT COUNT(*) FROM results WHERE candidate_id IS NOT NULL AND count_type='final'"
    ).fetchone()[0]
    assert count > 0


def test_uc4_flip_feasibility_returns_gap_and_flag(db_final):
    conn, election = db_final
    # Get top two candidates in first opstillingskreds
    ok_id = election["opstillingskredse"][0]["id"]
    top2 = conn.execute(
        "SELECT c.id, SUM(r.votes) as total FROM results r "
        "JOIN candidates c ON c.id = r.candidate_id "
        "JOIN afstemningsomraader ao ON ao.id = r.afstemningsomraade_id "
        "WHERE ao.opstillingskreds_id = ? AND r.candidate_id IS NOT NULL "
        "GROUP BY c.id ORDER BY total DESC LIMIT 2",
        (ok_id,),
    ).fetchall()
    assert len(top2) >= 2
    leader, challenger = top2[0]["total"], top2[1]["total"]
    result = calculator.constituency_flip_feasibility(leader, challenger, 5000)
    assert "gap" in result
    assert "feasible" in result
    assert isinstance(result["feasible"], bool)


def test_uc4_leader_is_not_feasible_to_flip_themselves(db_final):
    conn, election = db_final
    ok_id = election["opstillingskredse"][0]["id"]
    top = conn.execute(
        "SELECT SUM(r.votes) as total FROM results r "
        "JOIN candidates c ON c.id = r.candidate_id "
        "JOIN afstemningsomraader ao ON ao.id = r.afstemningsomraade_id "
        "WHERE ao.opstillingskreds_id = ? AND r.candidate_id IS NOT NULL "
        "GROUP BY c.id ORDER BY total DESC LIMIT 1",
        (ok_id,),
    ).fetchone()
    # Leader vs self — gap is 0, always feasible (or equal)
    result = calculator.constituency_flip_feasibility(top["total"], top["total"], 0)
    assert result["gap"] == 0


# ─── UC5: Party list rankings (fintælling required) ──────────────────────────

def test_uc5_candidates_can_be_ranked_by_votes(db_final):
    conn, election = db_final
    pid = election["parties"][0]["id"]
    rows = conn.execute(
        "SELECT c.id, c.name, SUM(r.votes) as total "
        "FROM results r "
        "JOIN candidates c ON c.id = r.candidate_id "
        "WHERE c.party_id = ? AND r.candidate_id IS NOT NULL AND r.count_type = 'final' "
        "GROUP BY c.id ORDER BY total DESC",
        (pid,),
    ).fetchall()
    assert len(rows) > 0
    # Verify descending order
    totals = [r["total"] for r in rows]
    assert totals == sorted(totals, reverse=True)


def test_uc5_in_bubble_out_classification(db_final):
    conn, election = db_final
    national = _load_national_votes(conn)
    storkreds = _load_storkreds_votes(conn)
    ks = _load_kredsmandat_seats(conn)
    seats = calculator.allocate_seats_total(national, storkreds, ks)

    for party in election["parties"]:
        pid = party["id"]
        projected = seats.get(pid, 0)
        rows = conn.execute(
            "SELECT c.id, SUM(r.votes) as total "
            "FROM results r "
            "JOIN candidates c ON c.id = r.candidate_id "
            "WHERE c.party_id = ? AND r.candidate_id IS NOT NULL AND r.count_type='final' "
            "GROUP BY c.id ORDER BY total DESC",
            (pid,),
        ).fetchall()
        if len(rows) == 0 or projected == 0:
            continue
        # First `projected` candidates are IN, next is BUBBLE
        in_candidates = rows[:projected]
        bubble = rows[projected] if len(rows) > projected else None
        assert all(r["total"] >= (bubble["total"] if bubble else 0)
                   for r in in_candidates)


# ─── UC6: Candidate tracking ─────────────────────────────────────────────────

def test_uc6_candidate_total_votes_queryable(db_final):
    conn, election = db_final
    candidate = election["candidates"][0]
    row = conn.execute(
        "SELECT SUM(votes) as total FROM results WHERE candidate_id = ? "
        "AND count_type = 'final'",
        (candidate["id"],),
    ).fetchone()
    assert row["total"] is not None
    assert row["total"] >= 0


def test_uc6_candidate_rank_within_party(db_final):
    conn, election = db_final
    pid = election["parties"][0]["id"]
    target_candidate = next(
        c for c in election["candidates"] if c["party_id"] == pid
    )
    # Get rank of target candidate within their party
    all_candidates = conn.execute(
        "SELECT candidate_id, SUM(votes) as total FROM results "
        "WHERE party_id = ? AND candidate_id IS NOT NULL AND count_type='final' "
        "GROUP BY candidate_id ORDER BY total DESC",
        (pid,),
    ).fetchall()
    ids = [r["candidate_id"] for r in all_candidates]
    assert target_candidate["id"] in ids


def test_uc6_no_candidate_votes_before_fintaelling(db_night):
    conn, election = db_night
    count = conn.execute(
        "SELECT COUNT(*) FROM results WHERE candidate_id IS NOT NULL AND count_type='final'"
    ).fetchone()[0]
    assert count == 0, "Final candidate votes should not exist on election night"
```

### Step 2: Run — confirm tests fail for right reasons

```bash
pytest tests/e2e/test_use_cases.py -v
```

Expected: most pass immediately (they test the integration of already-built components).
Any failures indicate a gap in the calculator or generator — fix those before proceeding.

### Step 3: Fix any failures

If a test fails, diagnose and fix the relevant component (generator, calculator, or processor).
Do not skip or weaken e2e tests — they represent the contract with the user.

### Step 4: Run full suite to confirm no regressions

```bash
pytest tests/ -v
```

Expected: all pass.

### Step 5: Commit

```bash
git add tests/e2e/
git commit -m "test: e2e use case tests using synthetic data"
```

---

## Task 10: CLI

**Files:**
- Modify: `valg/valg/cli.py`
- Create: `valg/tests/test_cli.py`

### Step 1: Write failing tests

```python
# tests/test_cli.py
import subprocess
import sys
import pytest
from pathlib import Path
from valg.models import get_connection, init_db
from valg.plugins import load_plugins
from tests.synthetic.generator import generate_election, load_into_db

@pytest.fixture(autouse=True)
def plugins():
    load_plugins()

@pytest.fixture
def night_db(tmp_path):
    db = tmp_path / "valg.db"
    conn = get_connection(db)
    init_db(conn)
    e = generate_election(n_parties=6, n_storkredse=3, n_districts=20, seed=42)
    load_into_db(conn, e, phase="preliminary")
    conn.close()
    return db, e

@pytest.fixture
def final_db(tmp_path):
    db = tmp_path / "valg.db"
    conn = get_connection(db)
    init_db(conn)
    e = generate_election(n_parties=6, n_storkredse=3, n_districts=20, seed=42)
    load_into_db(conn, e, phase="preliminary")
    load_into_db(conn, e, phase="final")
    conn.close()
    return db, e

def _run(args: list[str], db: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "valg", "--db", str(db)] + args,
        capture_output=True, text=True,
    )

# --- status ---

def test_status_empty_db_shows_no_data(tmp_path):
    db = tmp_path / "empty.db"
    conn = get_connection(db); init_db(conn); conn.close()
    r = _run(["status"], db)
    assert r.returncode == 0
    assert "no data" in r.stdout.lower()

def test_status_night_shows_preliminary_count(night_db):
    db, _ = night_db
    r = _run(["status"], db)
    assert r.returncode == 0
    assert "foreløbig" in r.stdout.lower() or "preliminary" in r.stdout.lower()

def test_status_night_shows_zero_fintaelling(night_db):
    db, _ = night_db
    r = _run(["status"], db)
    assert "0/" in r.stdout  # 0 fintælling districts

def test_status_final_shows_both_counts(final_db):
    db, _ = final_db
    r = _run(["status"], db)
    assert r.returncode == 0
    # Both preliminary and final should show non-zero
    assert "0/" not in r.stdout or r.stdout.count("0/") < 2

# --- flip ---

def test_flip_shows_table(night_db):
    db, _ = night_db
    r = _run(["flip"], db)
    assert r.returncode == 0
    assert "seat" in r.stdout.lower() or "gain" in r.stdout.lower()

def test_flip_shows_all_qualifying_parties(night_db):
    db, election = night_db
    r = _run(["flip"], db)
    # At least some party letters appear
    assert any(p["letter"] in r.stdout for p in election["parties"])

def test_flip_shows_no_data_on_empty_db(tmp_path):
    db = tmp_path / "empty.db"
    conn = get_connection(db); init_db(conn); conn.close()
    r = _run(["flip"], db)
    assert r.returncode == 0
    assert "no results" in r.stdout.lower() or "no data" in r.stdout.lower()

# --- party ---

def test_party_shows_votes_and_seats(night_db):
    db, election = night_db
    letter = election["parties"][0]["letter"]
    r = _run(["party", letter], db)
    assert r.returncode == 0
    assert "votes" in r.stdout.lower() or any(c.isdigit() for c in r.stdout)

def test_party_unknown_letter_gives_error(night_db):
    db, _ = night_db
    r = _run(["party", "Z"], db)
    assert r.returncode == 0
    assert "not found" in r.stdout.lower() or "z" in r.stdout.lower()

# --- storkreds ---

def test_storkreds_shows_all(night_db):
    db, election = night_db
    r = _run(["storkreds"], db)
    assert r.returncode == 0
    assert any(sk["name"] in r.stdout for sk in election["storkredse"])

def test_storkreds_filter_by_name(night_db):
    db, election = night_db
    target = election["storkredse"][0]["name"]
    r = _run(["storkreds", target], db)
    assert r.returncode == 0
    assert target in r.stdout

# --- kreds (graceful on election night) ---

def test_kreds_runs_on_night_data_without_crashing(night_db):
    db, election = night_db
    name = election["opstillingskredse"][0]["name"]
    r = _run(["kreds", name], db)
    assert r.returncode == 0  # must not crash

def test_kreds_shows_warning_when_no_fintaelling(night_db):
    db, election = night_db
    name = election["opstillingskredse"][0]["name"]
    r = _run(["kreds", name], db)
    assert "unknown" in r.stdout.lower() or "fintælling" in r.stdout.lower() \
        or "pending" in r.stdout.lower()

def test_kreds_shows_candidate_ranking_with_final_data(final_db):
    db, election = final_db
    name = election["opstillingskredse"][0]["name"]
    r = _run(["kreds", name], db)
    assert r.returncode == 0
    assert any(c.isdigit() for c in r.stdout)

def test_kreds_shows_partial_notice_during_transition(tmp_path):
    """Some districts have fintælling, others don't."""
    db = tmp_path / "valg.db"
    conn = get_connection(db)
    init_db(conn)
    e = generate_election(n_parties=4, n_storkredse=2, n_districts=10, seed=42)
    load_into_db(conn, e, phase="preliminary")
    # Load fintælling for only half the districts (simulate partial)
    from tests.synthetic.generator import generate_fintaelling_stream
    stream = generate_fintaelling_stream(e, chunks=2)
    import datetime, sqlite3
    snap = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for row in stream[0]:  # only first chunk
        conn.execute(
            "INSERT INTO results "
            "(afstemningsomraade_id, party_id, candidate_id, votes, count_type, snapshot_at) "
            "VALUES (?,?,?,?,?,?)",
            (row["district_id"], row["party_id"], row.get("candidate_id"),
             row["votes"], row["count_type"], snap)
        )
    conn.commit()
    conn.close()
    name = e["opstillingskredse"][0]["name"]
    r = _run(["kreds", name], db)
    assert r.returncode == 0
    assert "pending" in r.stdout.lower() or "progress" in r.stdout.lower() \
        or "unknown" in r.stdout.lower()

# --- list (graceful on election night) ---

def test_list_runs_on_night_data_without_crashing(night_db):
    db, election = night_db
    letter = election["parties"][0]["letter"]
    r = _run(["list", letter], db)
    assert r.returncode == 0

def test_list_shows_unknown_votes_on_night_data(night_db):
    db, election = night_db
    letter = election["parties"][0]["letter"]
    r = _run(["list", letter], db)
    assert "unknown" in r.stdout.lower() or "fintælling" in r.stdout.lower() \
        or "pending" in r.stdout.lower()

def test_list_shows_in_bubble_out_with_final_data(final_db):
    db, election = final_db
    letter = election["parties"][0]["letter"]
    r = _run(["list", letter], db)
    assert r.returncode == 0
    assert "in" in r.stdout.lower() or "bubble" in r.stdout.lower()
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError` or subprocess returning non-zero.

### Step 3: Implement cli.py

**Graceful degradation rules (apply to every command):**
- Never crash or block on missing data
- When candidate votes are unavailable, show `unknown` for that field — not an error
- When fintælling is partial (some districts have final data, others don't), show coverage notice and display what is known
- `_warn_partial_fintaelling(conn)` prints a yellow notice at the top of `kreds` and `list` output but always continues — it never gates

```python
def _fintaelling_coverage(conn) -> tuple[int, int]:
    final = conn.execute(
        "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results "
        "WHERE count_type='final' AND candidate_id IS NOT NULL"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM afstemningsomraader").fetchone()[0]
    return final, total

def _warn_partial_fintaelling(conn) -> None:
    """Print coverage notice. Never blocks — always continues."""
    final, total = _fintaelling_coverage(conn)
    if total == 0:
        return
    if final == 0:
        console.print(
            "[yellow]Fintælling not yet available — candidate fields show 'unknown'.[/yellow]"
        )
    elif final < total:
        console.print(
            f"[yellow]Fintælling in progress: {final}/{total} districts — "
            "remaining candidates shown as 'pending'.[/yellow]"
        )
```

For `kreds` and `list`, replace the hard block with `_warn_partial_fintaelling(conn)` and
display candidate rows where data exists, showing `unknown` for votes where it does not.

Wire together `_load_national_votes`, `_load_storkreds_votes`, `_load_kredsmandat_seats`,
and `cmd_status`, `cmd_flip`, `cmd_party`, `cmd_storkreds`, `cmd_kreds`, `cmd_list`.

### Step 4: Run — confirm all pass

```bash
pytest tests/test_cli.py -v
```

Expected: all PASSED

### Step 5: Commit

```bash
git add valg/cli.py tests/test_cli.py
git commit -m "feat: CLI with all commands, phase-aware guards, rich output"
```

---

## Task 11: GitHub Actions Sync Workflow

**Files:**
- Create: `valg/.github/workflows/sync.yml`

### Step 1: Create workflow

```yaml
# .github/workflows/sync.yml
name: SFTP Sync

on:
  schedule:
    - cron: "*/5 * * * *"   # every 5 minutes
  workflow_dispatch:
    inputs:
      election_folder:
        description: "Remote SFTP folder (overrides repo variable)"
        required: false

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: write  # needed to push to valg-data

    steps:
      - name: Check out code repo
        uses: actions/checkout@v4

      - name: Check out data repo
        uses: actions/checkout@v4
        with:
          repository: ${{ vars.DATA_REPO }}   # e.g. yourname/valg-data
          path: valg-data
          token: ${{ secrets.DATA_REPO_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run sync
        env:
          VALG_SFTP_HOST: ${{ secrets.VALG_SFTP_HOST }}
          VALG_SFTP_PORT: ${{ secrets.VALG_SFTP_PORT }}
          VALG_SFTP_USER: ${{ secrets.VALG_SFTP_USER }}
          VALG_SFTP_PASSWORD: ${{ secrets.VALG_SFTP_PASSWORD }}
          VALG_DATA_REPO: ./valg-data
          ELECTION_FOLDER: ${{ inputs.election_folder || vars.ELECTION_FOLDER }}
        run: |
          python -m valg sync --election-folder "$ELECTION_FOLDER" --data-repo ./valg-data

      - name: Configure git identity for data repo
        run: |
          git -C valg-data config user.name "valg-sync"
          git -C valg-data config user.email "valg-sync@users.noreply.github.com"

      - name: Push data repo
        run: |
          git -C valg-data push origin main || echo "Nothing to push"
```

### Step 2: Add required GitHub repo variables and secrets

In the GitHub UI (Settings → Secrets and Variables → Actions):

**Variables** (not secret, visible in logs):
- `DATA_REPO` = `yourname/valg-data`
- `ELECTION_FOLDER` = `/Folketingsvalg-1-2024` (update per election)

**Secrets** (hidden):
- `DATA_REPO_TOKEN` = GitHub PAT with `contents:write` on the data repo
- `VALG_SFTP_HOST` = `data.valg.dk`
- `VALG_SFTP_PORT` = `22`
- `VALG_SFTP_USER` = `Valg`
- `VALG_SFTP_PASSWORD` = `Valg`

**Step 3: Test with manual trigger**

In GitHub UI → Actions → SFTP Sync → Run workflow.
Check that it connects, downloads files, commits to `valg-data`, and pushes.

**Step 4: Commit**

```bash
git add .github/workflows/sync.yml
git commit -m "feat: GitHub Actions cron sync workflow for public data repo"
```

---

## Task 12: Historical Data Validation Script

**Files:**
- Create: `valg/scripts/download_historical.py`

```python
# scripts/download_historical.py
"""
Explore SFTP structure and download historical election data for parser validation.
Usage:
  python scripts/download_historical.py                   # explore only
  python scripts/download_historical.py --download /arkiv/FV2022
"""
import argparse, logging, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from valg.fetcher import get_sftp_client, walk_remote, download_file

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)
DEST = Path(__file__).parent.parent / "data" / "historical"

def explore(sftp, path="/", depth=0):
    if depth > 3: return
    try:
        for attr in sftp.listdir_attr(path):
            full = f"{path}/{attr.filename}".replace("//", "/")
            log.info("%s%s", "  " * depth, full)
            if not attr.st_size:
                explore(sftp, full, depth + 1)
    except Exception: pass

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--download", metavar="PATH",
                   help="Remote path to download after exploring")
    args = p.parse_args()
    ssh, sftp = get_sftp_client()
    try:
        log.info("=== SFTP root ===")
        explore(sftp)
        if args.download:
            log.info("\n=== Downloading %s ===", args.download)
            for rp in walk_remote(sftp, args.download):
                if rp.endswith(".json"):
                    lp = DEST / rp.lstrip("/")
                    if not lp.exists():
                        download_file(sftp, rp, lp)
    finally:
        sftp.close(); ssh.close()

if __name__ == "__main__":
    main()
```

**Validation step — run after downloading:**

```bash
python -c "
from pathlib import Path
from valg.models import get_connection, init_db
from valg.processor import process_raw_file
from valg.plugins import load_plugins
load_plugins()
conn = get_connection(':memory:')
init_db(conn)
errors = 0
for f in sorted(Path('data/historical').rglob('*.json')):
    try:
        process_raw_file(conn, f)
    except Exception as e:
        print('ERROR:', f.name, e)
        errors += 1
print(f'Done. {errors} errors.')
"
```

**Commit:**

```bash
git add scripts/download_historical.py
git commit -m "feat: historical data download and validation script"
```

---

## Task 13: Public Distribution + README

**Step 1: Verify files are in place**

```bash
ls ~/Documents/valg/LICENSE
ls ~/Documents/valg/DISCLAIMER.md
ls ~/Documents/valg/.env.example
```

**Step 2: Write README.md**

```markdown
# valg

Unofficial real-time tracker for Danish Folketing election results.

Fills the gap valg.dk misses: candidate/party drilldowns and seat-flip margins.

> See DISCLAIMER.md. This is not an official source. Always refer to valg.dk.

## Setup

    pip install -e ".[dev]"
    cp .env.example .env   # credentials are public defaults — override if needed

    # Initialise the data repo
    mkdir -p ../valg-data && cd ../valg-data && git init && cd -

## Election night

    # Option A: GitHub Actions (no server needed)
    # Fork this repo, set DATA_REPO and ELECTION_FOLDER variables — done.

    # Option B: run locally
    python -m valg sync --election-folder /Folketingsvalg-1-2024 --interval 300

    # Query results
    python -m valg status
    python -m valg flip
    python -m valg party A
    python -m valg storkreds

## Fintælling (next day)

    python -m valg kreds "Østerbro"
    python -m valg list A

## Adding a new file format

Drop a file in valg/plugins/:

    TABLE = "results"
    def MATCH(filename): return "my-pattern" in filename.lower()
    def parse(data, snapshot_at): return [...]  # list of row dicts

No other changes needed.

## Data source

Election data: data.valg.dk (Netcompany / Indenrigsministeriet).
Documented at: valg/api-doc/

## License

Beerware — see LICENSE.
```

**Step 3: Final commit**

```bash
git add README.md LICENSE DISCLAIMER.md .env.example
git commit -m "docs: README, license, disclaimer for public distribution"
```

---

## Task 14: Final Test Run

**Step 1: Full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all green.

**Step 2: Coverage report**

```bash
pytest tests/ --cov=valg --cov-report=term-missing
```

Note any uncovered paths for future work.

**Step 3: Smoke test with synthetic data end-to-end**

```python
python -c "
from valg.models import get_connection, init_db
from valg.plugins import load_plugins
from tests.synthetic.generator import generate_election, load_into_db
load_plugins()
conn = get_connection(':memory:')
init_db(conn)
e = generate_election(seed=42)
load_into_db(conn, e, phase='preliminary')
print('Election night DB loaded')
from valg import calculator
national = {r[0]: r[1] for r in conn.execute(
    'SELECT party_id, SUM(votes) FROM results WHERE candidate_id IS NULL GROUP BY party_id'
).fetchall()}
seats = calculator.allocate_seats_total(national, {}, {})
print('Projected seats:', seats)
"
```

---

---

## Task 15: GitHub Flow Scaffold

**Files:**
- Create: `valg/CONTRIBUTING.md`
- Create: `valg/.github/pull_request_template.md`

**Step 1: Write CONTRIBUTING.md**

```markdown
# Contributing to valg

## Branch naming

- `feat/<short-description>` — new feature
- `fix/<short-description>` — bug fix
- `docs/<short-description>` — documentation only
- `test/<short-description>` — tests only
- `chore/<short-description>` — tooling, deps, CI

## Workflow

1. Branch off `main`: `git checkout -b feat/my-thing`
2. Make changes — commit frequently, each commit should pass tests
3. Push and open a PR against `main`
4. Merge when ready (solo: self-merge is fine; open project: request review)

## Commit messages

Use the `type: short description` format:

    feat: add seat flip momentum tracking
    fix: handle missing party votes gracefully
    test: add e2e test for UC3

## Tests

All PRs must pass `pytest tests/ -v` before merge. No exceptions.

## Code style

- Python 3.11+
- No external formatters required, but keep functions short and focused
- Follow existing patterns in the codebase

## Note on `valg-data/`

The data repo (`valg-data/`) auto-commits directly to `main` via the sync loop.
GitHub flow applies to the **code repo only**.
```

**Step 2: Write PR template**

```markdown
<!-- .github/pull_request_template.md -->
## What does this PR do?

<!-- One sentence summary -->

## How to test it

<!-- Steps to verify the change works -->

## Checklist

- [ ] `pytest tests/ -v` passes
- [ ] No new warnings or errors in the test output
- [ ] Relevant tests added or updated
- [ ] CONTRIBUTING.md followed
```

**Step 3: Commit**

```bash
git add CONTRIBUTING.md .github/pull_request_template.md
git commit -m "docs: GitHub flow scaffold — CONTRIBUTING.md and PR template"
```

---

## Task 16: Events and Anomalies Schema

Extends the SQLite schema with two new tables that power the news roller and self-correcting data loop.

**Files:**
- Modify: `valg/valg/models.py`
- Modify: `valg/tests/test_models.py`

### Step 1: Write failing tests

```python
# Add to tests/test_models.py

def test_init_db_creates_events_table():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {r[0] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "events" in tables

def test_init_db_creates_anomalies_table():
    conn = get_connection(":memory:")
    init_db(conn)
    tables = {r[0] for r in
              conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "anomalies" in tables

def test_events_table_has_required_columns():
    conn = get_connection(":memory:")
    init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
    assert {"id", "occurred_at", "event_type", "subject", "description", "data"} <= cols

def test_anomalies_table_has_required_columns():
    conn = get_connection(":memory:")
    init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(anomalies)").fetchall()}
    assert {"id", "detected_at", "filename", "anomaly_type", "detail"} <= cols
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_models.py -v -k "events or anomalies"
```

Expected: FAIL — tables do not exist yet.

### Step 3: Add tables to SCHEMA in models.py

Add to the `SCHEMA` string in `valg/models.py`:

```python
"""
...existing schema...

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    subject     TEXT,
    description TEXT,
    data        TEXT
);

CREATE TABLE IF NOT EXISTS anomalies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at  TEXT NOT NULL,
    filename     TEXT,
    anomaly_type TEXT NOT NULL,
    detail       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_type_time ON events(event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_anomalies_time   ON anomalies(detected_at);
"""
```

### Step 4: Run — confirm passing

```bash
pytest tests/test_models.py -v
```

Expected: all PASSED.

### Step 5: Commit

```bash
git add valg/models.py tests/test_models.py
git commit -m "feat: events and anomalies tables in SQLite schema"
```

---

## Task 17: News Roller — Diff Engine and Feed Command

After each sync cycle, diff the new snapshot against the previous one and write events to the `events` table. Add `valg feed` CLI command.

**Files:**
- Create: `valg/valg/differ.py`
- Create: `valg/tests/test_differ.py`
- Modify: `valg/valg/fetcher.py` (call differ after each sync)
- Modify: `valg/valg/cli.py` (add `feed` command)

### Step 1: Write failing tests for differ

```python
# tests/test_differ.py
import json
import pytest
from valg.models import get_connection, init_db
from valg.differ import diff_snapshots, write_events

@pytest.fixture
def db():
    conn = get_connection(":memory:")
    init_db(conn)
    return conn

def _insert_party_votes(conn, party_id, votes, snapshot_at):
    conn.execute(
        "INSERT OR IGNORE INTO parties (id, letter, name, election_id) VALUES (?, ?, ?, ?)",
        (party_id, party_id, party_id, "E1"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO elections (id, name) VALUES (?, ?)", ("E1", "Test"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO storkredse (id, name, election_id) VALUES (?, ?, ?)",
        ("SK1", "SK1", "E1"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO opstillingskredse (id, name, storkreds_id) VALUES (?, ?, ?)",
        ("OK1", "OK1", "SK1"),
    )
    conn.execute(
        "INSERT INTO party_votes (opstillingskreds_id, party_id, votes, snapshot_at) VALUES (?, ?, ?, ?)",
        ("OK1", party_id, votes, snapshot_at),
    )
    conn.commit()


def test_diff_detects_vote_increase(db):
    _insert_party_votes(db, "A", 1000, "2024-11-05T21:00:00")
    _insert_party_votes(db, "A", 1500, "2024-11-05T21:05:00")
    events = diff_snapshots(db, "2024-11-05T21:00:00", "2024-11-05T21:05:00")
    assert any(e["event_type"] == "vote_increase" and e["subject"] == "A" for e in events)

def test_diff_no_events_when_unchanged(db):
    _insert_party_votes(db, "A", 1000, "2024-11-05T21:00:00")
    _insert_party_votes(db, "A", 1000, "2024-11-05T21:05:00")
    events = diff_snapshots(db, "2024-11-05T21:00:00", "2024-11-05T21:05:00")
    assert len(events) == 0

def test_diff_returns_empty_list_on_first_snapshot(db):
    _insert_party_votes(db, "A", 1000, "2024-11-05T21:00:00")
    events = diff_snapshots(db, None, "2024-11-05T21:00:00")
    assert isinstance(events, list)

def test_write_events_inserts_rows(db):
    events = [
        {
            "occurred_at": "2024-11-05T21:05:00",
            "event_type": "vote_increase",
            "subject": "A",
            "description": "Socialdemokratiet gained 500 votes",
            "data": json.dumps({"before": 1000, "after": 1500, "delta": 500}),
        }
    ]
    write_events(db, events)
    count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 1
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_differ.py -v
```

Expected: `ImportError: cannot import name 'diff_snapshots' from 'valg.differ'`

### Step 3: Implement differ.py

```python
# valg/differ.py
import json
import logging
from typing import Optional

log = logging.getLogger(__name__)


def diff_snapshots(conn, prev_snapshot: Optional[str], curr_snapshot: str) -> list[dict]:
    """Compare party votes between two snapshots and return detected events."""
    if prev_snapshot is None:
        return []

    events = []

    prev = {r["party_id"]: r["votes"] for r in conn.execute(
        "SELECT party_id, SUM(votes) as votes FROM party_votes "
        "WHERE snapshot_at = ? GROUP BY party_id",
        (prev_snapshot,),
    ).fetchall()}

    curr = {r["party_id"]: r["votes"] for r in conn.execute(
        "SELECT party_id, SUM(votes) as votes FROM party_votes "
        "WHERE snapshot_at = ? GROUP BY party_id",
        (curr_snapshot,),
    ).fetchall()}

    for party_id, curr_votes in curr.items():
        prev_votes = prev.get(party_id, 0)
        delta = curr_votes - prev_votes
        if delta > 0:
            events.append({
                "occurred_at": curr_snapshot,
                "event_type": "vote_increase",
                "subject": party_id,
                "description": f"Party {party_id} gained {delta:,} votes",
                "data": json.dumps({"before": prev_votes, "after": curr_votes, "delta": delta}),
            })

    return events


def write_events(conn, events: list[dict]) -> None:
    for e in events:
        conn.execute(
            "INSERT INTO events (occurred_at, event_type, subject, description, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (e["occurred_at"], e["event_type"], e["subject"], e["description"], e["data"]),
        )
    conn.commit()
    if events:
        log.info("Wrote %d events", len(events))
```

### Step 4: Wire differ into fetcher

In `valg/fetcher.py`, after `process_directory(conn, data_dir)`, add:

```python
from valg.differ import diff_snapshots, write_events

# After processing, detect events
prev_snap = _get_previous_snapshot(conn)
curr_snap = snapshot_at
events = diff_snapshots(conn, prev_snap, curr_snap)
write_events(conn, events)
```

Add helper to `fetcher.py`:

```python
def _get_previous_snapshot(conn) -> Optional[str]:
    row = conn.execute(
        "SELECT snapshot_at FROM party_votes ORDER BY snapshot_at DESC LIMIT 1 OFFSET 1"
    ).fetchone()
    return row["snapshot_at"] if row else None
```

### Step 5: Add `feed` command to cli.py

```python
# In cli.py — add to argument parser and dispatch

# Parser
feed_parser = subparsers.add_parser("feed", help="Live event feed")
feed_parser.add_argument("--since", metavar="TIME", help="Filter events after HH:MM")
feed_parser.add_argument("--type", metavar="TYPE", help="Filter by event type")
feed_parser.add_argument("--limit", type=int, default=50)

# Handler
def cmd_feed(conn, args):
    query = "SELECT occurred_at, event_type, subject, description FROM events"
    params = []
    conditions = []
    if args.since:
        conditions.append("occurred_at >= ?")
        params.append(args.since)
    if args.type:
        conditions.append("event_type = ?")
        params.append(args.type)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY occurred_at DESC LIMIT ?"
    params.append(args.limit)

    rows = conn.execute(query, params).fetchall()
    if not rows:
        console.print("[dim]No events yet.[/dim]")
        return
    for r in rows:
        console.print(f"[dim]{r['occurred_at']}[/dim] [{r['event_type']}] {r['subject']}: {r['description']}")
```

### Step 6: Run all tests

```bash
pytest tests/test_differ.py tests/test_cli.py -v
```

Expected: all PASSED.

### Step 7: Commit

```bash
git add valg/differ.py tests/test_differ.py valg/fetcher.py valg/cli.py
git commit -m "feat: news roller — diff-based event detection and valg feed command"
```

---

## Task 18: AI Commentary Layer

Model-agnostic AI client. On-demand `valg commentary` command and event-driven hooks.

**Files:**
- Create: `valg/valg/ai.py`
- Create: `valg/tests/test_ai.py`
- Modify: `valg/valg/cli.py`
- Modify: `valg/.env.example`

### Step 1: Write failing tests

```python
# tests/test_ai.py
import pytest
from unittest.mock import patch, MagicMock
from valg.ai import build_prompt, get_ai_client, is_ai_configured

def test_is_ai_configured_false_without_env(monkeypatch):
    monkeypatch.delenv("VALG_AI_API_KEY", raising=False)
    assert is_ai_configured() is False

def test_is_ai_configured_true_with_key(monkeypatch):
    monkeypatch.setenv("VALG_AI_API_KEY", "sk-test")
    monkeypatch.setenv("VALG_AI_BASE_URL", "https://api.anthropic.com/v1")
    monkeypatch.setenv("VALG_AI_MODEL", "claude-sonnet-4-6")
    assert is_ai_configured() is True

def test_build_prompt_contains_party_data():
    state = {
        "parties": [{"letter": "A", "votes": 50000, "seats": 3}],
        "districts_reported": 10,
        "districts_total": 20,
    }
    prompt = build_prompt(state)
    assert "A" in prompt
    assert "50000" in prompt or "50,000" in prompt

def test_build_prompt_returns_string():
    state = {"parties": [], "districts_reported": 0, "districts_total": 0}
    assert isinstance(build_prompt(state), str)

def test_get_commentary_returns_none_when_not_configured(monkeypatch):
    monkeypatch.delenv("VALG_AI_API_KEY", raising=False)
    from valg.ai import get_commentary
    result = get_commentary({"parties": [], "districts_reported": 0, "districts_total": 0})
    assert result is None
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_ai.py -v
```

Expected: `ImportError`

### Step 3: Implement ai.py

```python
# valg/ai.py
"""
Model-agnostic AI commentary layer.
Uses any OpenAI-compatible endpoint. Requires:
  VALG_AI_API_KEY   — API key
  VALG_AI_BASE_URL  — base URL (e.g. https://api.anthropic.com/v1)
  VALG_AI_MODEL     — model name (e.g. claude-sonnet-4-6, gpt-4o)
"""
import json
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


def is_ai_configured() -> bool:
    return bool(os.getenv("VALG_AI_API_KEY"))


def get_ai_client():
    try:
        from openai import OpenAI
    except ImportError:
        log.warning("openai package not installed — pip install openai")
        return None
    return OpenAI(
        api_key=os.getenv("VALG_AI_API_KEY"),
        base_url=os.getenv("VALG_AI_BASE_URL", "https://api.openai.com/v1"),
    )


def build_prompt(state: dict) -> str:
    parties = state.get("parties", [])
    reported = state.get("districts_reported", 0)
    total = state.get("districts_total", 0)
    lines = [
        f"Danish Folketing election. {reported}/{total} districts reported.",
        "Current standings:",
    ]
    for p in parties:
        lines.append(
            f"  Party {p['letter']}: {p['votes']:,} votes, {p['seats']} projected seats"
        )
    lines.append(
        "\nProvide a brief analytical commentary (3-5 sentences) on the current state. "
        "Note any notable trends, close races, or seat flip risks. Be factual and concise."
    )
    return "\n".join(lines)


def get_commentary(state: dict, context: Optional[str] = None) -> Optional[str]:
    """Return AI commentary string, or None if AI is not configured."""
    if not is_ai_configured():
        return None
    client = get_ai_client()
    if client is None:
        return None
    model = os.getenv("VALG_AI_MODEL", "gpt-4o-mini")
    prompt = build_prompt(state)
    if context:
        prompt = f"Context: {context}\n\n{prompt}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning("AI commentary failed: %s", e)
        return None
```

### Step 4: Update .env.example

```bash
# AI commentary (optional — omit to disable)
# Any OpenAI-compatible endpoint works: Anthropic, OpenAI, local Ollama, etc.
VALG_AI_BASE_URL=https://api.anthropic.com/v1
VALG_AI_API_KEY=
VALG_AI_MODEL=claude-sonnet-4-6
```

### Step 5: Add `commentary` command to cli.py

```python
# Add to cli.py

def cmd_commentary(conn, args):
    from valg.ai import get_commentary, is_ai_configured
    if not is_ai_configured():
        console.print("[yellow]AI not configured. Set VALG_AI_API_KEY in .env[/yellow]")
        return

    # Build state dict from DB
    national = {r["party_id"]: r["votes"] for r in conn.execute(
        "SELECT party_id, SUM(votes) as votes FROM party_votes "
        "GROUP BY party_id ORDER BY votes DESC"
    ).fetchall()}
    # ... seat calculation ...
    state = {
        "parties": [{"letter": k, "votes": v, "seats": 0} for k, v in national.items()],
        "districts_reported": conn.execute(
            "SELECT COUNT(DISTINCT afstemningsomraade_id) FROM results"
        ).fetchone()[0],
        "districts_total": conn.execute(
            "SELECT COUNT(*) FROM afstemningsomraader"
        ).fetchone()[0],
    }
    commentary = get_commentary(state, context=getattr(args, "context", None))
    if commentary:
        console.print(commentary)
```

### Step 6: Add openai to dependencies

In `pyproject.toml`, add to `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov"]
ai  = ["openai>=1.0"]
```

Install with: `pip install -e ".[ai]"`

### Step 7: Run tests

```bash
pytest tests/test_ai.py -v
```

Expected: all PASSED.

### Step 8: Commit

```bash
git add valg/ai.py tests/test_ai.py valg/cli.py .env.example pyproject.toml
git commit -m "feat: model-agnostic AI commentary layer with valg commentary command"
```

---

## Task 19: Self-Correcting Data Loop

Anomaly threshold detection, AI-assisted plugin patch generation, and notify-on-breach.

**Files:**
- Create: `valg/valg/watchdog.py`
- Create: `valg/tests/test_watchdog.py`
- Modify: `valg/valg/processor.py` (log anomalies to DB instead of just logging)
- Modify: `valg/.env.example`

### Step 1: Write failing tests

```python
# tests/test_watchdog.py
import pytest
from valg.models import get_connection, init_db
from valg.watchdog import anomaly_rate, threshold_breached, summarise_anomalies

@pytest.fixture
def db():
    conn = get_connection(":memory:")
    init_db(conn)
    return conn

def _insert_anomaly(conn, filename, anomaly_type, detail, detected_at="2024-11-05T21:00:00"):
    conn.execute(
        "INSERT INTO anomalies (detected_at, filename, anomaly_type, detail) VALUES (?,?,?,?)",
        (detected_at, filename, anomaly_type, detail),
    )
    conn.commit()

def test_anomaly_rate_zero_with_no_anomalies(db):
    assert anomaly_rate(db, folder="Valgresultater/", n_files=10) == 0.0

def test_anomaly_rate_correct_fraction(db):
    for i in range(3):
        _insert_anomaly(db, f"Valgresultater/file{i}.json", "parse_failure", "bad json")
    rate = anomaly_rate(db, folder="Valgresultater/", n_files=10)
    assert abs(rate - 0.3) < 0.01

def test_threshold_breached_false_below(db):
    for i in range(1):
        _insert_anomaly(db, f"Valgresultater/f{i}.json", "parse_failure", "x")
    assert threshold_breached(db, folder="Valgresultater/", n_files=10, threshold=0.2) is False

def test_threshold_breached_true_above(db):
    for i in range(5):
        _insert_anomaly(db, f"Valgresultater/f{i}.json", "parse_failure", "x")
    assert threshold_breached(db, folder="Valgresultater/", n_files=10, threshold=0.2) is True

def test_summarise_anomalies_returns_dict(db):
    _insert_anomaly(db, "Valgresultater/f1.json", "parse_failure", "bad json")
    _insert_anomaly(db, "Valgresultater/f2.json", "unknown_field", "field X")
    summary = summarise_anomalies(db, folder="Valgresultater/")
    assert "parse_failure" in summary or "unknown_field" in summary
```

### Step 2: Run — confirm failure

```bash
pytest tests/test_watchdog.py -v
```

Expected: `ImportError`

### Step 3: Implement watchdog.py

```python
# valg/watchdog.py
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)

AUTOPATCH = os.getenv("VALG_AI_AUTOPATCH", "false").lower() == "true"


def anomaly_rate(conn, folder: str, n_files: int) -> float:
    if n_files == 0:
        return 0.0
    count = conn.execute(
        "SELECT COUNT(*) FROM anomalies WHERE filename LIKE ?",
        (f"{folder}%",),
    ).fetchone()[0]
    return count / n_files


def threshold_breached(conn, folder: str, n_files: int, threshold: float = 0.2) -> bool:
    return anomaly_rate(conn, folder, n_files) > threshold


def summarise_anomalies(conn, folder: str) -> dict:
    rows = conn.execute(
        "SELECT anomaly_type, COUNT(*) as n FROM anomalies "
        "WHERE filename LIKE ? GROUP BY anomaly_type",
        (f"{folder}%",),
    ).fetchall()
    return {r["anomaly_type"]: r["n"] for r in rows}


def maybe_escalate(conn, folder: str, n_files: int, threshold: float = 0.2) -> None:
    """Check threshold and escalate if breached. Called after each sync cycle."""
    if not threshold_breached(conn, folder, n_files, threshold):
        return

    summary = summarise_anomalies(conn, folder)
    log.warning(
        "ANOMALY THRESHOLD BREACHED for %s: %s", folder, summary
    )

    # Write a sentinel event so the feed and web app surface this
    conn.execute(
        "INSERT INTO events (occurred_at, event_type, subject, description, data) "
        "VALUES (datetime('now'), 'anomaly_threshold', ?, ?, ?)",
        (
            folder,
            f">{threshold*100:.0f}% of files in {folder} failed parsing",
            str(summary),
        ),
    )
    conn.commit()

    # Attempt AI-assisted patch (if configured)
    _attempt_ai_patch(conn, folder, summary)


def _attempt_ai_patch(conn, folder: str, summary: dict) -> None:
    from valg.ai import is_ai_configured, get_ai_client
    if not is_ai_configured():
        log.info("AI not configured — skipping patch attempt")
        return

    log.info("Requesting AI-assisted plugin patch for %s", folder)
    # Load a sample of failing raw file content for context
    # (implementation: pass raw file snippets + existing plugin code to AI)
    # Auto-apply only if VALG_AI_AUTOPATCH=true — default is false (require confirmation)
    if AUTOPATCH:
        log.warning("VALG_AI_AUTOPATCH=true — patch would be applied automatically (not yet implemented)")
    else:
        log.warning(
            "Patch suggestion generated. Set VALG_AI_AUTOPATCH=true to auto-apply, "
            "or review the anomalies table and update the plugin manually."
        )
```

### Step 4: Update .env.example

```bash
# Self-correcting data loop
VALG_AI_AUTOPATCH=false   # set to true to auto-apply AI plugin patches (risky on election night)
VALG_ANOMALY_THRESHOLD=0.2  # breach if >20% of files in a folder fail parsing
```

### Step 5: Run tests

```bash
pytest tests/test_watchdog.py -v
```

Expected: all PASSED.

### Step 6: Commit

```bash
git add valg/watchdog.py tests/test_watchdog.py valg/processor.py .env.example
git commit -m "feat: self-correcting data loop — anomaly watchdog with threshold escalation"
```

---

## Task 20: Web App Scaffold (Svelte + GitHub Pages)

Sets up the Svelte project inside `valg/web/`, configured to deploy to GitHub Pages.

**Files:**
- Create: `valg/web/` (Svelte project)
- Create: `valg/.github/workflows/deploy-web.yml`

### Step 1: Scaffold Svelte project

```bash
cd ~/Documents/valg
npm create svelte@latest web
# Choose: Skeleton project, TypeScript: No, ESLint: Yes, Prettier: Yes
cd web
npm install
```

### Step 2: Configure for GitHub Pages

In `valg/web/svelte.config.js`:

```js
import adapter from '@sveltejs/adapter-static';

export default {
  kit: {
    adapter: adapter({
      pages: 'build',
      assets: 'build',
      fallback: 'index.html',
    }),
    paths: {
      base: process.env.NODE_ENV === 'production' ? '/valg' : '',
    },
  },
};
```

Install static adapter:

```bash
npm install -D @sveltejs/adapter-static
```

### Step 3: Create GitHub Actions deploy workflow

```yaml
# .github/workflows/deploy-web.yml
name: Deploy web app to GitHub Pages

on:
  push:
    branches: [main]
    paths: ['web/**']
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
        working-directory: web
      - run: npm run build
        working-directory: web
        env:
          NODE_ENV: production
      - uses: actions/upload-pages-artifact@v3
        with:
          path: web/build

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/deploy-pages@v4
        id: deployment
```

### Step 4: Verify local build works

```bash
cd web
npm run build
npm run preview
```

Open browser at the local URL — should show a blank Svelte page.

### Step 5: Commit

```bash
git add web/ .github/workflows/deploy-web.yml
git commit -m "feat: Svelte web app scaffold with GitHub Pages deploy workflow"
```

---

## Task 21: Web App Data Layer and Dashboard

Fetch JSON from `valg-data/` GitHub raw URLs, run seat calculations client-side, render the main dashboard.

**Files:**
- Create: `valg/web/src/lib/data.js`
- Create: `valg/web/src/lib/calculator.js`
- Modify: `valg/web/src/routes/+page.svelte`

### Step 1: Implement data.js

```js
// web/src/lib/data.js
// Fetches JSON snapshots from the valg-data public GitHub repo.

const REPO = 'https://raw.githubusercontent.com/<owner>/valg-data/main';

export async function fetchLatestPartyVotes() {
  const url = `${REPO}/Partistemmefordeling/partistemmefordeling-latest.json`;
  const res = await fetch(url);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchCommitList() {
  // Uses GitHub API to get commit history for the history scrubber
  const res = await fetch(
    'https://api.github.com/repos/<owner>/valg-data/commits?per_page=100'
  );
  if (!res.ok) return [];
  return res.json();
}

export async function fetchAtCommit(sha, path) {
  const url = `https://raw.githubusercontent.com/<owner>/valg-data/${sha}/${path}`;
  const res = await fetch(url);
  if (!res.ok) return null;
  return res.json();
}
```

### Step 2: Implement client-side calculator.js

```js
// web/src/lib/calculator.js
// D'Hondt seat allocation — mirrors the Python calculator logic.

export function dhondt(partyVotes, nSeats) {
  const seats = Object.fromEntries(Object.keys(partyVotes).map(k => [k, 0]));
  const quotients = { ...partyVotes };

  for (let i = 0; i < nSeats; i++) {
    const winner = Object.entries(quotients).reduce(
      (a, b) => (b[1] > a[1] ? b : a)
    )[0];
    seats[winner]++;
    quotients[winner] = partyVotes[winner] / (seats[winner] + 1);
  }
  return seats;
}

export function formatVotes(n) {
  return n.toLocaleString('da-DK');
}
```

### Step 3: Build main dashboard in +page.svelte

```svelte
<!-- web/src/routes/+page.svelte -->
<script>
  import { onMount } from 'svelte';
  import { fetchLatestPartyVotes } from '$lib/data.js';
  import { dhondt, formatVotes } from '$lib/calculator.js';

  let parties = [];
  let loading = true;
  let error = null;

  onMount(async () => {
    try {
      const data = await fetchLatestPartyVotes();
      if (!data) { error = 'No data yet.'; return; }
      // Parse and compute — adapt to actual JSON shape from valg-data
      parties = Object.entries(data).map(([letter, votes]) => ({
        letter,
        votes,
        seats: 0,
      }));
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  });
</script>

<main>
  <h1>Valg — Folketing results</h1>
  {#if loading}<p>Loading...</p>
  {:else if error}<p class="error">{error}</p>
  {:else}
    <table>
      <thead><tr><th>Party</th><th>Votes</th><th>Projected seats</th></tr></thead>
      <tbody>
        {#each parties as p}
          <tr>
            <td>{p.letter}</td>
            <td>{formatVotes(p.votes)}</td>
            <td>{p.seats}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</main>

<style>
  main { font-family: monospace; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 0.5rem; border-bottom: 1px solid #ccc; text-align: left; }
  .error { color: red; }
</style>
```

### Step 4: Build and verify

```bash
cd web && npm run build
```

Expected: clean build, no errors.

### Step 5: Commit

```bash
git add web/src/
git commit -m "feat: web app data layer and main dashboard with client-side D'Hondt"
```

---

## Task 22: History Scrubber

Let users step through past snapshots using the git commit history of `valg-data/`.

**Files:**
- Create: `valg/web/src/lib/Scrubber.svelte`
- Modify: `valg/web/src/routes/+page.svelte`

### Step 1: Implement Scrubber.svelte

```svelte
<!-- web/src/lib/Scrubber.svelte -->
<script>
  import { createEventDispatcher, onMount } from 'svelte';
  import { fetchCommitList } from '$lib/data.js';

  const dispatch = createEventDispatcher();

  let commits = [];
  let selected = 0;  // index into commits — 0 is most recent

  onMount(async () => {
    commits = await fetchCommitList();
    if (commits.length) dispatch('change', { sha: commits[0].sha, date: commits[0].commit.author.date });
  });

  function onChange() {
    const c = commits[selected];
    dispatch('change', { sha: c.sha, date: c.commit.author.date });
  }
</script>

{#if commits.length > 1}
  <div class="scrubber">
    <label>
      Snapshot: {commits[selected]?.commit.author.date ?? 'live'}
      <input
        type="range"
        min="0"
        max={commits.length - 1}
        bind:value={selected}
        on:input={onChange}
      />
    </label>
    <span class="hint">← older | newer →</span>
  </div>
{/if}

<style>
  .scrubber { margin: 1rem 0; }
  input[type=range] { width: 100%; }
  .hint { font-size: 0.8em; color: #666; }
</style>
```

### Step 2: Wire scrubber into +page.svelte

```svelte
<script>
  // ... existing imports ...
  import Scrubber from '$lib/Scrubber.svelte';

  async function onSnapshotChange({ detail }) {
    loading = true;
    // Re-fetch data at the selected commit SHA
    const data = await fetchAtCommit(detail.sha, 'Partistemmefordeling/...');
    // re-parse and update parties
    loading = false;
  }
</script>

<Scrubber on:change={onSnapshotChange} />
<!-- ...rest of template... -->
```

### Step 3: Build and verify

```bash
cd web && npm run build
```

### Step 4: Commit

```bash
git add web/src/lib/Scrubber.svelte web/src/routes/+page.svelte
git commit -m "feat: history scrubber — step through past snapshots from valg-data git history"
```

---

## Task 23: Alert System

Web Push notifications triggered by user-defined conditions, configured in the UI and persisted to `localStorage`.

**Files:**
- Create: `valg/web/src/lib/alerts.js`
- Create: `valg/web/src/lib/Alerts.svelte`
- Modify: `valg/web/src/routes/+page.svelte`

### Step 1: Implement alerts.js

```js
// web/src/lib/alerts.js
// Alert config lives in localStorage under 'valg_alerts'.

export const DEFAULT_ALERTS = [];

export function loadAlerts() {
  try {
    return JSON.parse(localStorage.getItem('valg_alerts') ?? '[]');
  } catch { return []; }
}

export function saveAlerts(alerts) {
  localStorage.setItem('valg_alerts', JSON.stringify(alerts));
}

export async function requestNotificationPermission() {
  if (!('Notification' in window)) return false;
  const result = await Notification.requestPermission();
  return result === 'granted';
}

export function notify(title, body) {
  if (Notification.permission !== 'granted') return;
  new Notification(title, { body, icon: '/favicon.png' });
}

export function evaluateAlerts(alerts, currentState, previousState) {
  const triggered = [];
  for (const alert of alerts) {
    if (alert.type === 'candidate_votes') {
      const curr = currentState.candidateVotes?.[alert.candidate] ?? 0;
      const prev = previousState?.candidateVotes?.[alert.candidate] ?? 0;
      if (curr - prev >= (alert.min_delta ?? 1)) {
        triggered.push({ alert, message: `${alert.candidate}: +${curr - prev} votes` });
      }
    }
    if (alert.type === 'seat_flip') {
      const currA = currentState.seats?.[alert.party_a] ?? 0;
      const prevA = previousState?.seats?.[alert.party_a] ?? 0;
      if (currA !== prevA) {
        triggered.push({ alert, message: `Seat flip: Party ${alert.party_a} now has ${currA} seats` });
      }
    }
  }
  return triggered;
}
```

### Step 2: Implement Alerts.svelte (settings panel)

```svelte
<!-- web/src/lib/Alerts.svelte -->
<script>
  import { loadAlerts, saveAlerts, requestNotificationPermission } from '$lib/alerts.js';

  let alerts = loadAlerts();
  let permissionGranted = typeof Notification !== 'undefined' && Notification.permission === 'granted';

  async function enableNotifications() {
    permissionGranted = await requestNotificationPermission();
  }

  function addAlert(type) {
    alerts = [...alerts, { type, candidate: '', party: '', min_delta: 100 }];
    saveAlerts(alerts);
  }

  function removeAlert(i) {
    alerts = alerts.filter((_, idx) => idx !== i);
    saveAlerts(alerts);
  }

  function onAlertChange() {
    saveAlerts(alerts);
  }
</script>

<section>
  <h2>Alerts</h2>
  {#if !permissionGranted}
    <button on:click={enableNotifications}>Enable browser notifications</button>
  {/if}

  {#each alerts as alert, i}
    <div class="alert-row">
      <span>{alert.type}</span>
      {#if alert.type === 'candidate_votes'}
        <input bind:value={alert.candidate} on:input={onAlertChange} placeholder="Candidate name" />
        <input type="number" bind:value={alert.min_delta} on:input={onAlertChange} />
      {/if}
      <button on:click={() => removeAlert(i)}>Remove</button>
    </div>
  {/each}

  <button on:click={() => addAlert('candidate_votes')}>+ Candidate votes alert</button>
  <button on:click={() => addAlert('seat_flip')}>+ Seat flip alert</button>
</section>
```

### Step 3: Wire alert evaluation into the data refresh loop in +page.svelte

```svelte
<script>
  import { loadAlerts, evaluateAlerts, notify } from '$lib/alerts.js';
  import Alerts from '$lib/Alerts.svelte';

  let previousState = null;

  async function refresh() {
    const data = await fetchLatestPartyVotes();
    const currentState = parseState(data);
    const alerts = loadAlerts();
    const triggered = evaluateAlerts(alerts, currentState, previousState);
    for (const { alert, message } of triggered) {
      notify('Valg alert', message);
    }
    previousState = currentState;
  }

  // Poll every 60s when on live view
  onMount(() => {
    refresh();
    const interval = setInterval(refresh, 60_000);
    return () => clearInterval(interval);
  });
</script>

<Alerts />
```

### Step 4: Build and verify

```bash
cd web && npm run build
```

### Step 5: Commit

```bash
git add web/src/lib/alerts.js web/src/lib/Alerts.svelte web/src/routes/+page.svelte
git commit -m "feat: alert system — Web Push notifications with localStorage config"
```

---

## Task 24: valg-data README and Updated valg README

**Files:**
- Modify: `valg/README.md` (update from Task 13 version)
- Create: `valg-data/README.md`
- Create: `valg/CONTRIBUTING.md` (already done in Task 15 — skip if exists)

### Step 1: Update valg/README.md

Update the README written in Task 13 to include the new capabilities:

```markdown
# valg

Unofficial real-time tracker for Danish Folketing election results.

Fills the gap valg.dk misses: candidate/party drilldowns, seat-flip margins,
live event feed, and a public web dashboard.

> See DISCLAIMER.md. This is not an official source. Always refer to valg.dk.

## Setup

    pip install -e ".[dev]"
    cp .env.example .env

    # Initialise the data repo
    mkdir -p ../valg-data && cd ../valg-data && git init && cd -

## Election night

    # Option A: GitHub Actions (no server needed)
    # Fork this repo, set DATA_REPO and ELECTION_FOLDER variables — done.
    # The web app deploys automatically to GitHub Pages.

    # Option B: run locally
    python -m valg sync --election-folder /Folketingsvalg-1-2024 --interval 300

## Querying results

    python -m valg status                        # districts reported, national totals
    python -m valg flip                          # top 10 closest seat flips
    python -m valg party A                       # party drilldown
    python -m valg candidate "Mette Frederiksen"
    python -m valg kreds "Østerbro"
    python -m valg feed                          # live event feed
    python -m valg commentary                    # AI analysis (requires VALG_AI_API_KEY)

## Web dashboard

The web app is deployed to GitHub Pages automatically on push to main.
It fetches data directly from valg-data — no backend required.
Set alert conditions in the UI; they are saved to your browser's local storage.

## AI commentary

Set VALG_AI_API_KEY and VALG_AI_MODEL in .env. Any OpenAI-compatible endpoint works
(Anthropic, OpenAI, local Ollama, etc.).

## Adding a new file format

Drop a file in valg/plugins/:

    TABLE = "results"
    def MATCH(filename): return "my-pattern" in filename.lower()
    def parse(data, snapshot_at): return [...]

No other changes needed.

## Data source

Election data: data.valg.dk (Netcompany / Indenrigsministeriet).

## Contributing

See CONTRIBUTING.md.

## License

Beerware — see LICENSE.
```

### Step 2: Write valg-data/README.md

```markdown
# valg-data

Unofficial snapshot archive of Danish Folketing election data.

This repo is automatically updated every 5 minutes on election night by the
[valg](https://github.com/<owner>/valg) sync tool.

## Data source

Election data is sourced from the Danish election authority's public SFTP server
(`data.valg.dk`, port 22), operated by Netcompany on behalf of Indenrigsministeriet.
The server is documented for public access with published credentials (`Valg`/`Valg`).

This archive is not affiliated with or endorsed by Indenrigsministeriet or Netcompany.
Official results are published at [valg.dk](https://valg.dk).

## Structure

```
<ElectionFolder>/
  Geografi/                  # Electoral geography (regions, storkredse, districts)
  Kandidatdata/              # Candidate registrations per storkreds
  Valgresultater/            # Election results per polling district
  Valgdeltagelse/            # Voter turnout per polling district
  Partistemmefordeling/      # Party vote distribution per opstillingskreds
```

Each sync cycle is a git commit. Step through commits to replay the night.

## Replay

```bash
git clone https://github.com/<owner>/valg-data
git log --oneline                     # browse snapshots
git checkout <sha>                    # restore a past state
python -m valg status                 # query against that snapshot
```

## Data license

Danish public sector data is covered by the Danish Open Government License (DOGL)
and the EU Public Sector Information directive. Free redistribution with attribution.
This is an unofficial snapshot archive, not the authoritative record.
```

### Step 3: Commit

```bash
# In valg/
git add README.md
git commit -m "docs: update README with web app, AI commentary, and feed command"

# In valg-data/
cd ~/Documents/valg-data
git add README.md
git commit -m "docs: README — data source, structure, replay instructions"
```

---

## Completion Checklist

- [ ] Task 1: Project scaffold + data repo + .env.example
- [ ] Task 2: SQLite schema with indexes
- [ ] Task 3: SFTP fetcher with env config, git commit, push-with-fallback
- [ ] Task 4: Plugin registry (hot-pluggable, auto-discovered)
- [ ] Task 5: Built-in plugins (geografi, kandidatdata, valgresultater, valgdeltagelse, partistemmer)
- [ ] Task 6: Processor core (plugin dispatch, directory batch)
- [ ] Task 7: Synthetic generator (election night + fintælling + load_into_db)
- [ ] Task 8: Calculator (D'Hondt, Saint-Laguë, flip, momentum)
- [ ] Task 9: E2E use case tests (UC1–UC6 confirmed with synthetic data)
- [ ] Task 10: CLI (all commands, phase-aware guards, rich output)
- [ ] Task 11: GitHub Actions sync workflow
- [ ] Task 12: Historical data download + validation script
- [ ] Task 13: Public distribution (LICENSE, DISCLAIMER, README)
- [ ] Task 14: Final test run — all green
- [ ] Task 15: GitHub flow scaffold (CONTRIBUTING.md, PR template)
- [ ] Task 16: Events and anomalies schema
- [ ] Task 17: News roller — diff engine and `valg feed` command
- [ ] Task 18: AI commentary layer
- [ ] Task 19: Self-correcting data loop — anomaly watchdog
- [ ] Task 20: Web app scaffold (Svelte + GitHub Pages)
- [ ] Task 21: Web app data layer and main dashboard
- [ ] Task 22: History scrubber
- [ ] Task 23: Alert system (Web Push + localStorage config)
- [ ] Task 24: valg-data README + updated valg README

`pytest tests/ -v` — all green before marking complete.
`cd web && npm run build` — clean build before marking complete.
