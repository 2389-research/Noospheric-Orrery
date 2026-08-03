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
