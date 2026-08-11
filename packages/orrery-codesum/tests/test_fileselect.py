"""Hidden/dot directories are build/config/cache artifacts, not source intent."""
from orrery_codesum.fileselect import should_skip_dir, should_skip_file


def test_hidden_dirs_skipped():
    for name in (".godot", ".git", ".next", ".idea", ".vscode", ".cache", ".pytest_cache"):
        assert should_skip_dir(name), name


def test_named_build_dirs_skipped():
    for name in ("node_modules", "target", "dist", "__pycache__", "venv"):
        assert should_skip_dir(name), name
    assert should_skip_dir("mypkg.egg-info")


def test_source_dirs_not_skipped():
    for name in ("src", "lib", "components", "coordinator", "micam"):
        assert not should_skip_dir(name), name


def test_dotfiles_still_skipped():
    assert should_skip_file(".env")
    assert should_skip_file(".gitignore")
    assert not should_skip_file("main.rs")


def test_uppercase_suffixes_are_skipped_too():
    """The skip list is lowercase; filesystems are not.

    `diagram.PNG` sailed past it, so binary bytes reached the summarizer — and on a
    case-insensitive filesystem the same file skipped or not purely by how it was
    spelled, which is not a property anyone can reason about.
    """
    from orrery_codesum.fileselect import should_skip_file
    for name in ("diagram.PNG", "bundle.ZIP", "photo.JPEG", "lib.SO"):
        assert should_skip_file(name), f"{name} should be skipped"
    # Source files are still kept, whatever their case.
    assert not should_skip_file("Main.PY")
    assert not should_skip_file("app.ts")
