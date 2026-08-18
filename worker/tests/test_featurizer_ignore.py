from src.featurizers.ignore import should_skip_dir, should_skip_file


def test_dotfolders_skipped_by_default():
    assert should_skip_dir(".obsidian")
    assert should_skip_dir(".trash")
    assert should_skip_dir(".git")


def test_content_dir_not_skipped():
    assert not should_skip_dir("Projects")


def test_binary_and_cache_files_skipped():
    assert should_skip_file("diagram.PNG")   # case-folded
    assert should_skip_file("notes.pdf")
    assert not should_skip_file("note.md")


def test_config_extra_dirs_skipped():
    assert should_skip_dir("Templates", extra_dirs={"Templates"})
    assert not should_skip_dir("Templates")
