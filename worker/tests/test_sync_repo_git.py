# ABOUTME: Guards the sync_repo git helpers — they must pass `-c safe.directory=<root>`
# ABOUTME: (or they fail with "dubious ownership" on a mounted checkout) and read HEAD/diffs.
import subprocess

from src.jobs.sync_repo import _git_head_sha, _git_changed_files


def _git(d, *args):
    subprocess.run(["git", "-C", str(d), *args], check=True,
                   capture_output=True, text=True)


def _init_repo(d):
    d.mkdir(parents=True, exist_ok=True)
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    (d / "a.txt").write_text("one\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "first")


def test_git_head_sha_returns_head(tmp_path):
    d = tmp_path / "repo"
    _init_repo(d)
    expected = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    assert _git_head_sha(str(d)) == expected


def test_git_head_sha_non_repo_returns_none(tmp_path):
    assert _git_head_sha(str(tmp_path)) is None


def test_git_changed_files_detects_change(tmp_path):
    d = tmp_path / "repo"
    _init_repo(d)
    base = _git_head_sha(str(d))
    (d / "a.txt").write_text("two\n")
    (d / "b.txt").write_text("new\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "second")
    changed, deleted = _git_changed_files(str(d), base)
    assert changed == {"a.txt", "b.txt"}
    assert deleted == set()


def test_helpers_pass_scoped_safe_directory(tmp_path, monkeypatch):
    """The fix: both helpers must invoke git with `-c safe.directory=<root_path>`,
    scoped to the directory (never the global `*`). Without it the call fails as
    'dubious ownership' on a mounted checkout owned by another uid."""
    root = str(tmp_path / "repo")
    _init_repo(tmp_path / "repo")   # BEFORE the spy — only helper calls should be captured

    seen = []
    real_run = subprocess.run

    def spy(argv, *a, **k):
        seen.append(argv)
        return real_run(argv, *a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    _git_head_sha(root)
    _git_changed_files(root, "HEAD")

    git_calls = [c for c in seen if c[:1] == ["git"]]
    assert git_calls, "no git subprocess calls captured"
    for argv in git_calls:
        assert f"safe.directory={root}" in argv, f"missing scoped safe.directory: {argv}"
        assert "safe.directory=*" not in argv, f"must not use global safe.directory: {argv}"
