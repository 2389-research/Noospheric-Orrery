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


def test_a_subdirectory_of_another_checkout_records_no_provenance(tmp_path):
    """`git -C` ASCENDS to find .git, so a plain subdir answers for the OUTER repo.

    Left unchecked, the job persists a remote and SHA describing a repository that is
    not the ingested tree, and the stored relative paths do not resolve against it. That
    is worse than no provenance, because it looks valid — an agent following the ref
    lands in the wrong codebase.
    """
    import subprocess
    from src.jobs.ingest_repo import _git_coordinates

    outer = tmp_path / "outer"
    (outer / "sub" / "nested").mkdir(parents=True)
    (outer / "file.txt").write_text("x")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c"]):
        subprocess.run(["git", "-C", str(outer), *args], check=True,
                       capture_output=True)
    subprocess.run(["git", "-C", str(outer), "remote", "add", "origin",
                    "https://github.com/org/outer.git"], check=True, capture_output=True)

    # The real root still reports provenance...
    remote, sha = _git_coordinates(str(outer))
    assert remote == "github.com/org/outer" and sha

    # ...but a subdirectory of it must not inherit the outer repo's identity.
    assert _git_coordinates(str(outer / "sub")) == (None, None)
    assert _git_coordinates(str(outer / "sub" / "nested")) == (None, None)
