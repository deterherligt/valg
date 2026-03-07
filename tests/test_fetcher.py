import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path
from valg.fetcher import (
    get_sftp_client,
    walk_remote,
    download_file,
    sync_election_folder,
    commit_data_repo,
)

# ── get_sftp_client ────────────────────────────────────────────────────────

def test_get_sftp_client_uses_env_vars(monkeypatch):
    monkeypatch.setenv("VALG_SFTP_HOST", "test.host")
    monkeypatch.setenv("VALG_SFTP_PORT", "2222")
    monkeypatch.setenv("VALG_SFTP_USER", "testuser")
    monkeypatch.setenv("VALG_SFTP_PASSWORD", "testpass")
    with patch("valg.fetcher.paramiko.SSHClient") as mock_ssh_cls:
        mock_ssh = MagicMock()
        mock_ssh_cls.return_value = mock_ssh
        mock_sftp = MagicMock()
        mock_ssh.open_sftp.return_value = mock_sftp
        ssh, sftp = get_sftp_client()
        mock_ssh.connect.assert_called_once_with(
            "test.host", port=2222, username="testuser", password="testpass"
        )
        assert sftp is mock_sftp

def test_get_sftp_client_uses_defaults(monkeypatch):
    for var in ["VALG_SFTP_HOST", "VALG_SFTP_PORT", "VALG_SFTP_USER", "VALG_SFTP_PASSWORD"]:
        monkeypatch.delenv(var, raising=False)
    with patch("valg.fetcher.paramiko.SSHClient") as mock_ssh_cls:
        mock_ssh = MagicMock()
        mock_ssh_cls.return_value = mock_ssh
        mock_ssh.open_sftp.return_value = MagicMock()
        get_sftp_client()
        mock_ssh.connect.assert_called_once_with(
            "data.valg.dk", port=22, username="Valg", password="Valg"
        )

# ── walk_remote ────────────────────────────────────────────────────────────

def test_walk_remote_yields_json_files():
    mock_sftp = MagicMock()
    attr_json = MagicMock()
    attr_json.filename = "results.json"
    attr_json.st_size = 1000
    attr_json.st_mtime = 1000.0
    mock_sftp.listdir_attr.return_value = [attr_json]
    results = list(walk_remote(mock_sftp, "/test"))
    assert len(results) == 1
    assert results[0][0] == "/test/results.json"

def test_walk_remote_recurses_into_directories():
    mock_sftp = MagicMock()
    dir_attr = MagicMock()
    dir_attr.filename = "subdir"
    dir_attr.st_size = 0
    dir_attr.st_mtime = None
    file_attr = MagicMock()
    file_attr.filename = "data.json"
    file_attr.st_size = 500
    file_attr.st_mtime = 2000.0
    mock_sftp.listdir_attr.side_effect = [
        [dir_attr],
        [file_attr],
    ]
    results = list(walk_remote(mock_sftp, "/root"))
    assert any("data.json" in r[0] for r in results)

def test_walk_remote_skips_non_json():
    mock_sftp = MagicMock()
    attr = MagicMock()
    attr.filename = "README.txt"
    attr.st_size = 100
    attr.st_mtime = 1000.0
    mock_sftp.listdir_attr.return_value = [attr]
    results = list(walk_remote(mock_sftp, "/test"))
    assert len(results) == 0

# ── download_file ──────────────────────────────────────────────────────────

def test_download_file_creates_parent_dirs(tmp_path):
    mock_sftp = MagicMock()
    dest = tmp_path / "deep" / "path" / "file.json"
    download_file(mock_sftp, "/remote/file.json", dest)
    assert dest.parent.exists()
    mock_sftp.get.assert_called_once_with("/remote/file.json", str(dest))

def test_download_file_calls_sftp_get(tmp_path):
    mock_sftp = MagicMock()
    dest = tmp_path / "file.json"
    download_file(mock_sftp, "/remote/file.json", dest)
    mock_sftp.get.assert_called_once()

# ── sync_election_folder ───────────────────────────────────────────────────

def test_sync_downloads_new_files(tmp_path, monkeypatch):
    monkeypatch.setenv("VALG_DATA_REPO", str(tmp_path))
    mock_sftp = MagicMock()
    remote_file = ("/election/Valgresultater/result.json", 500, 9999.0)
    with patch("valg.fetcher.walk_remote", return_value=[remote_file]):
        with patch("valg.fetcher.download_file") as mock_dl:
            downloaded = sync_election_folder(mock_sftp, "/election", tmp_path)
            assert downloaded >= 1
            mock_dl.assert_called_once()

def test_sync_skips_unchanged_files(tmp_path, monkeypatch):
    monkeypatch.setenv("VALG_DATA_REPO", str(tmp_path))
    existing = tmp_path / "Valgresultater" / "result.json"
    existing.parent.mkdir(parents=True)
    existing.write_text("{}")
    import os; os.utime(existing, (5000.0, 5000.0))
    mock_sftp = MagicMock()
    remote_file = ("/election/Valgresultater/result.json", 100, 5000.0)
    with patch("valg.fetcher.walk_remote", return_value=[remote_file]):
        with patch("valg.fetcher.download_file") as mock_dl:
            downloaded = sync_election_folder(mock_sftp, "/election", tmp_path)
            mock_dl.assert_not_called()

# ── commit_data_repo ───────────────────────────────────────────────────────

def test_commit_data_repo_commits_changes(tmp_path):
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    (tmp_path / "test.json").write_text('{"x": 1}')
    result = commit_data_repo(tmp_path, message="test: commit")
    assert result is True

def test_commit_data_repo_returns_false_when_nothing_to_commit(tmp_path):
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    result = commit_data_repo(tmp_path, message="test: nothing")
    assert result is False
