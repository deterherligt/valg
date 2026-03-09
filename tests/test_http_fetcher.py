import json
import pytest
from unittest.mock import patch, MagicMock
from valg.http_fetcher import fetch_tree, download_file, sync_from_github


def _mock_response(data):
    cm = MagicMock()
    cm.__enter__ = lambda s: s
    cm.__exit__ = MagicMock(return_value=False)
    cm.read = MagicMock(
        return_value=json.dumps(data).encode() if isinstance(data, dict) else data
    )
    return cm


def test_fetch_tree_returns_only_json_blobs():
    tree = {
        "tree": [
            {"path": "Storkreds.json", "sha": "abc", "type": "blob"},
            {"path": "README.md", "sha": "def", "type": "blob"},
            {"path": "subdir/votes.json", "sha": "ghi", "type": "blob"},
            {"path": "subdir", "sha": "jkl", "type": "tree"},
        ]
    }
    with patch("urllib.request.urlopen", return_value=_mock_response(tree)):
        result = fetch_tree()
    assert len(result) == 2
    assert all(f["path"].endswith(".json") for f in result)


def test_fetch_tree_excludes_non_json():
    tree = {"tree": [{"path": "README.md", "sha": "abc", "type": "blob"}]}
    with patch("urllib.request.urlopen", return_value=_mock_response(tree)):
        result = fetch_tree()
    assert result == []


def test_download_file_writes_content(tmp_path):
    with patch("urllib.request.urlopen", return_value=_mock_response(b'{"ok":true}')):
        download_file("Storkreds.json", tmp_path / "Storkreds.json")
    assert (tmp_path / "Storkreds.json").read_bytes() == b'{"ok":true}'


def test_download_file_creates_parent_dirs(tmp_path):
    with patch("urllib.request.urlopen", return_value=_mock_response(b'{}')):
        download_file("a/b/file.json", tmp_path / "a" / "b" / "file.json")
    assert (tmp_path / "a" / "b" / "file.json").exists()


def test_sync_downloads_new_files(tmp_path):
    tree = {"tree": [{"path": "Storkreds.json", "sha": "abc123", "type": "blob"}]}

    def fake_urlopen(url, timeout=10):
        if "api.github.com" in url:
            return _mock_response(tree)
        return _mock_response(b'[{"Kode":"SK1","Navn":"Test","AntalKredsmandater":10,"ValgId":"FV"}]')

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        count = sync_from_github(tmp_path)
    assert count == 1
    assert (tmp_path / "Storkreds.json").exists()


def test_sync_skips_unchanged_files(tmp_path):
    (tmp_path / ".sha_cache.json").write_text(json.dumps({"Storkreds.json": "abc123"}))
    tree = {"tree": [{"path": "Storkreds.json", "sha": "abc123", "type": "blob"}]}
    with patch("urllib.request.urlopen", return_value=_mock_response(tree)):
        count = sync_from_github(tmp_path)
    assert count == 0


def test_sync_downloads_when_sha_changed(tmp_path):
    (tmp_path / ".sha_cache.json").write_text(json.dumps({"Storkreds.json": "old_sha"}))
    tree = {"tree": [{"path": "Storkreds.json", "sha": "new_sha", "type": "blob"}]}

    def fake_urlopen(url, timeout=10):
        if "api.github.com" in url:
            return _mock_response(tree)
        return _mock_response(b'[]')

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        count = sync_from_github(tmp_path)
    assert count == 1
