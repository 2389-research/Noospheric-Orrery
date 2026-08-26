# ABOUTME: Guards the sync_repo git helpers — they must pass `-c safe.directory=<root>`
# ABOUTME: (or they fail with "dubious ownership" on a mounted checkout) and read HEAD/diffs.
import asyncio
import subprocess

from src.db import get_connection
from src.jobs.sync_repo import _git_head_sha, _git_changed_files, sync_repo


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


def test_short_circuit_backfills_remote_url(test_db, tmp_path):
    """Finding 1 regression: a repo already at its stored commit_sha (every repo synced
    before remote_url capture existed) takes ONLY the HEAD-unchanged short-circuit, so
    that path must backfill a NULL remote_url — else the fetchable ref never appears."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git(repo, "remote", "add", "origin", "https://github.com/2389-research/mux-rs.git")
    head = _git_head_sha(str(repo))
    assert head

    conn = get_connection(test_db)
    coll_id, src_id = "coll-1", "src-1"
    # Legacy state: commit_sha set (old code stored bare HEAD), remote_url still NULL.
    conn.execute(
        "INSERT INTO collections (id, name, path, root_path, kind, commit_sha, remote_url) "
        "VALUES (?, ?, ?, ?, 'git_repo', ?, NULL)",
        (coll_id, "repo", "repo", str(repo), head))
    conn.commit()
    ws = {"uri": str(repo), "type": "repo"}
    source_config = {"_collection_id": coll_id, "_domain": "x/y"}

    res = asyncio.run(sync_repo(conn, None, None, ws, source_config, src_id))

    assert res.get("unchanged") is True   # short-circuit was taken (no re-summarize)
    row = conn.execute(
        "SELECT remote_url, commit_sha FROM collections WHERE id = ?", (coll_id,)).fetchone()
    assert row["remote_url"] == "github.com/2389-research/mux-rs"   # backfilled
    assert row["commit_sha"] == head
