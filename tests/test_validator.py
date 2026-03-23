import git
from valg.validator import check_authors, check_inventory


def test_check_authors_passes_for_allowed_email(tmp_path):
    """All commits from allowed author → no unauthorized commits."""
    repo = git.Repo.init(tmp_path)
    (tmp_path / "file.txt").write_text("data")
    repo.index.add(["file.txt"])
    repo.index.commit("sync", author=git.Actor("Mads", "mads@example.com"))
    result = check_authors(tmp_path, allowed_emails=["mads@example.com"])
    assert result == []


def test_check_authors_flags_unauthorized_email(tmp_path):
    """Commit from unknown author → returned in unauthorized list."""
    repo = git.Repo.init(tmp_path)
    (tmp_path / "file.txt").write_text("data")
    repo.index.add(["file.txt"])
    repo.index.commit("hack", author=git.Actor("Evil", "evil@bad.com"))
    result = check_authors(tmp_path, allowed_emails=["mads@example.com"])
    assert len(result) == 1
    assert result[0]["email"] == "evil@bad.com"


def test_check_inventory_all_matched(tmp_path):
    """All files match a plugin → no unknown files."""
    (tmp_path / "Region.json").write_text("{}")
    (tmp_path / "partistemmefordeling-ok1.json").write_text("{}")
    result = check_inventory(tmp_path)
    assert result["unknown_files"] == []


def test_check_inventory_flags_unknown_files(tmp_path):
    """Files that no plugin matches → listed as unknown."""
    (tmp_path / "Region.json").write_text("{}")
    (tmp_path / "BrandNewFormat.json").write_text("{}")
    result = check_inventory(tmp_path)
    assert "BrandNewFormat.json" in result["unknown_files"]
    assert "Region.json" not in result["unknown_files"]
