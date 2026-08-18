from src.featurizers.markdown import parse_frontmatter, clean_markdown


def test_parse_frontmatter_splits_block_and_body():
    text = "---\ntitle: Q3\ntags: [project, roadmap]\n---\n# Q3\nThe body.\n"
    meta, body = parse_frontmatter(text)
    assert meta["title"] == "Q3"
    assert meta["tags"] == ["project", "roadmap"]
    assert body.lstrip().startswith("# Q3")
    assert "tags:" not in body   # frontmatter must not leak into the body


def test_parse_frontmatter_absent():
    meta, body = parse_frontmatter("# Just a note\nno frontmatter\n")
    assert meta == {}
    assert body.startswith("# Just a note")


def test_parse_frontmatter_malformed_yaml_is_safe():
    text = "---\n: : broken\n---\nbody\n"
    meta, body = parse_frontmatter(text)
    assert meta == {}          # never raise on bad YAML
    assert body.strip() == "body"


def test_clean_wikilinks():
    assert clean_markdown("see [[Q3 Planning]] and [[Note|the note]]") == \
        "see Q3 Planning and the note"


def test_clean_wikilink_with_heading_anchor():
    assert clean_markdown("[[Note#Section]] ref") == "Note ref"


def test_drop_embeds_and_comments():
    assert "image.png" not in clean_markdown("![[image.png]]")
    assert clean_markdown("visible %%hidden note%% text") == "visible  text"
