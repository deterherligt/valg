import git
from valg.validator import check_authors


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
