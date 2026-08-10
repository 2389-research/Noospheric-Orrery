# ABOUTME: Git-provenance capture for ingest_repo — normalizing remotes and
# ABOUTME: reading (remote, sha) from a checkout so agents can fetch real source.
import subprocess

from src.jobs.ingest_repo import _normalize_remote, _git_coordinates


def test_normalize_remote_variants():
    assert _normalize_remote("https://github.com/2389-research/tracker.git") == "github.com/2389-research/tracker"
    assert _normalize_remote("https://github.com/2389-research/tracker") == "github.com/2389-research/tracker"
    assert _normalize_remote("git@github.com:2389-research/tracker.git") == "github.com/2389-research/tracker"
    assert _normalize_remote("https://user@github.com/org/repo.git") == "github.com/org/repo"
    assert _normalize_remote(None) is None
    assert _normalize_remote("") is None


def test_git_coordinates_non_repo_returns_none(tmp_path):
    # Best-effort: a plain directory is not a git checkout.
    assert _git_coordinates(str(tmp_path)) == (None, None)


def _git(*args, cwd):
    subprocess.run(  # noqa: S603 — fixed argv, test-only, no shell
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def _init_repo(d):
    d.mkdir()
    _git("init", cwd=d)
    _git("remote", "add", "origin", "git@github.com:2389-research/tracker.git", cwd=d)
    (d / "f.txt").write_text("x")
    _git("add", "-A", cwd=d)
    _git("commit", "-m", "init", cwd=d)


def test_git_coordinates_reads_remote_and_sha(tmp_path):
    d = tmp_path / "collection"
    _init_repo(d)
    remote, sha = _git_coordinates(str(d))
    assert remote == "github.com/2389-research/tracker"
    assert sha and len(sha) == 40


def test_git_coordinates_dirty_returns_none(tmp_path):
    # A dirty working tree can't be reproduced from any GitHub ref -> no provenance.
    d = tmp_path / "collection"
    _init_repo(d)
    (d / "f.txt").write_text("uncommitted change")
    assert _git_coordinates(str(d)) == (None, None)


def test_git_coordinates_no_remote_returns_none(tmp_path):
    # Committed but no 'origin' remote -> can't fetch it -> all-or-nothing -> None.
    d = tmp_path / "collection"
    d.mkdir()
    _git("init", cwd=d)
    (d / "f.txt").write_text("x")
    _git("add", "-A", cwd=d)
    _git("commit", "-m", "init", cwd=d)
    assert _git_coordinates(str(d)) == (None, None)
