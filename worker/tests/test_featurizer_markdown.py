from src.featurizers.markdown import parse_frontmatter


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
