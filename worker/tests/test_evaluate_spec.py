# ABOUTME: Tests for the spec evaluator's parsing, diffing, and chunking logic.
# ABOUTME: Does not require LLM calls — tests the deterministic parts.

import pytest
from src.jobs.evaluate_spec import parse_golden_set, chunk_text, diff_entities


class TestParseGoldenSet:
    def test_json_array(self):
        text = '[{"name": "Alice", "type": "Person"}, {"name": "Acme", "type": "Organization"}]'
        result = parse_golden_set(text)
        assert ("alice", "person") in result
        assert ("acme", "organization") in result

    def test_json_embedded_in_text(self):
        text = """Here is the golden set:
[{"name": "Bob", "type": "Person"}, {"name": "MIT", "type": "Organization"}]
End of golden set."""
        result = parse_golden_set(text)
        assert ("bob", "person") in result
        assert ("mit", "organization") in result

    def test_markdown_list(self):
        text = """- Alice (Person)
- Acme Corp (Organization)
- Machine Learning (Topic)"""
        result = parse_golden_set(text)
        assert ("alice", "person") in result
        assert ("acme corp", "organization") in result
        assert ("machine learning", "topic") in result

    def test_type_definition_lines(self):
        text = """- Person — people, speakers, authors
- Organization — companies, groups, teams"""
        result = parse_golden_set(text)
        assert any(t == "person" for _, t in result)
        assert any(t == "organization" for _, t in result)

    def test_empty_returns_empty(self):
        assert parse_golden_set("") == []
        assert parse_golden_set("   \n\n  ") == []

    def test_comment_lines_skipped_in_fallback(self):
        text = """# Header
entity one
entity two"""
        result = parse_golden_set(text)
        names = [n for n, _ in result]
        assert "# header" not in names
        assert "entity one" in names

    def test_golden_set_with_taxonomy_and_json(self):
        """JSON array takes priority even when taxonomy lines are present."""
        text = """# Golden Set

## Entity Type Taxonomy
- Person — people, speakers, authors
- Organization — companies, groups

## Reference Entities
```json
[
  {"name": "harper reed", "type": "Person"},
  {"name": "3kvc", "type": "Organization"}
]
```
"""
        result = parse_golden_set(text)
        assert ("harper reed", "person") in result
        assert ("3kvc", "organization") in result
        assert len(result) == 2  # JSON entities only, not taxonomy terms


class TestChunkText:
    def test_short_text_single_chunk(self):
        text = "Hello world"
        chunks = chunk_text(text, chunk_size=2000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_multiple_chunks(self):
        text = "a" * 5000
        chunks = chunk_text(text, chunk_size=2000, overlap=200)
        assert len(chunks) >= 3
        # All text should be covered
        assert all(len(c) <= 2000 for c in chunks)

    def test_overlap_present(self):
        text = "a" * 3000
        chunks = chunk_text(text, chunk_size=2000, overlap=200)
        assert len(chunks) == 2
        # Second chunk should start 200 chars before first chunk ends
        assert len(chunks[0]) == 2000
        assert len(chunks[1]) == 1200  # 3000 - (2000 - 200) = 1200


class TestDiffEntities:
    def test_perfect_match(self):
        extracted = [{"name": "alice", "type": "Person"}, {"name": "acme", "type": "Organization"}]
        golden = [("alice", "person"), ("acme", "organization")]
        result = diff_entities(extracted, golden)
        assert len(result["hits"]) == 2
        assert len(result["misses"]) == 0
        assert len(result["false_positives"]) == 0
        assert result["precision"] == 1.0
        assert result["recall"] == 1.0

    def test_misses(self):
        extracted = [{"name": "alice", "type": "Person"}]
        golden = [("alice", "person"), ("bob", "person")]
        result = diff_entities(extracted, golden)
        assert len(result["hits"]) == 1
        assert len(result["misses"]) == 1
        assert result["recall"] == 0.5

    def test_false_positives(self):
        extracted = [{"name": "alice", "type": "Person"}, {"name": "unknown", "type": "Thing"}]
        golden = [("alice", "person")]
        result = diff_entities(extracted, golden)
        assert len(result["hits"]) == 1
        assert len(result["false_positives"]) == 1
        assert result["precision"] == 0.5

    def test_near_misses(self):
        extracted = [{"name": "alice", "type": "Character"}]  # type differs
        golden = [("alice", "person")]
        result = diff_entities(extracted, golden)
        assert len(result["hits"]) == 0
        assert len(result["near_misses"]) == 1
        assert result["near_misses"][0]["name"] == "alice"

    def test_dedup_case_sensitive_type(self):
        """Dedup uses case-sensitive type to match real pipeline."""
        extracted = [
            {"name": "alice", "type": "Person"},
            {"name": "alice", "type": "person"},  # different case = separate entity in dedup
        ]
        golden = [("alice", "person")]
        result = diff_entities(extracted, golden)
        # Both should survive dedup since types differ in case
        assert result["total_extracted"] == 2

    def test_empty_golden(self):
        extracted = [{"name": "alice", "type": "Person"}]
        golden = []
        result = diff_entities(extracted, golden)
        assert len(result["false_positives"]) == 1
        assert result["total_golden"] == 0

    def test_empty_extracted(self):
        extracted = []
        golden = [("alice", "person")]
        result = diff_entities(extracted, golden)
        assert len(result["misses"]) == 1
        assert result["precision"] == 0.0
        assert result["recall"] == 0.0
