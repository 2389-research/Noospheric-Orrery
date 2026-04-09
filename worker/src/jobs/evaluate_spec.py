#!/usr/bin/env python
# ABOUTME: Standalone evaluator for simmer Phase 2 — runs candidate spec against sample docs with Haiku.
# ABOUTME: Produces quantitative metrics + raw outputs for qualitative judge review.

"""
Spec evaluator for extraction spec simmering.

Invoked as a subprocess by simmer-sdk's evaluator mechanism.
Runs the candidate extraction spec against sample documents using Haiku,
diffs results against the golden set, writes raw outputs for judges to
inspect, and prints a quantitative summary to stdout.
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path


def parse_golden_set(text: str) -> list[tuple[str, str]]:
    """Parse golden set text into (name, type) tuples.

    Expects a JSON array of {"name": ..., "type": ...} objects embedded in the
    golden set text (possibly inside a markdown code fence). This is the format
    Phase 1 is instructed to produce.

    Returns an empty list if no valid JSON entities are found — the caller
    should treat this as a fatal error.
    """
    entities: list[tuple[str, str]] = []

    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "name" in item and "type" in item:
                        entities.append((item["name"].lower().strip(), item["type"].lower().strip()))
    except (json.JSONDecodeError, ValueError):
        pass

    return entities


def chunk_text(text: str, chunk_size: int = 2000, overlap: int = 200) -> list[str]:
    """Split text into chunks, matching the real pipeline's chunker."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        start = end - overlap if end < len(text) else end
    return chunks


def diff_entities(
    extracted: list[dict], golden: list[tuple[str, str]]
) -> dict:
    """Compare extracted entities against golden set.

    Dedup uses case-sensitive type (matching real pipeline).
    Golden set matching uses case-insensitive on both name and type.
    """
    # Dedup extracted (matches extract_document behavior)
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for e in extracted:
        key = (e["name"].lower().strip(), e["type"])  # case-sensitive type for dedup
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    # Build golden lookup (case-insensitive on both)
    golden_set = {(n.lower().strip(), t.lower().strip()) for n, t in golden}

    hits = []
    false_positives = []
    near_misses = []

    for e in deduped:
        name_lower = e["name"].lower().strip()
        type_lower = e["type"].lower().strip()
        if (name_lower, type_lower) in golden_set:
            hits.append(e)
        elif any(name_lower == gn for gn, _ in golden_set):
            near_misses.append(e)
        else:
            false_positives.append(e)

    # Use unique hit keys to avoid double-counting case variants
    hit_keys = {(e["name"].lower().strip(), e["type"].lower().strip()) for e in hits}
    misses = [(n, t) for n, t in golden_set if (n, t) not in hit_keys]

    total_extracted = len(deduped)
    matched_count = len(hit_keys)
    precision = matched_count / total_extracted if total_extracted > 0 else 0.0
    recall = matched_count / len(golden_set) if golden_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "hits": hits,
        "hit_keys": hit_keys,
        "misses": misses,
        "false_positives": false_positives,
        "near_misses": near_misses,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "total_extracted": total_extracted,
        "total_golden": len(golden_set),
    }


EXTRACTION_PROMPT = """You are an entity extraction system. Follow the extraction spec below exactly.

EXTRACTION SPEC:
{spec}

TEXT TO EXTRACT FROM:
{chunk_text}

Extract all entities mentioned in the text according to the spec. Only extract entities explicitly present — do not hallucinate or infer. Normalize names: lowercase, strip extra whitespace."""

ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entity name, lowercase, stripped"},
                    "type": {"type": "string", "description": "Entity type from the spec"},
                },
                "required": ["name", "type"],
            },
        },
    },
    "required": ["entities"],
}


async def extract_chunk(relay, chunk_text: str, spec: str, model: str) -> list[dict]:
    """Run extraction on a single chunk using tool use for guaranteed JSON."""
    result = await relay.complete_structured(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(spec=spec, chunk_text=chunk_text)}],
        schema=ENTITY_SCHEMA,
        tool_name="extract_entities",
        tool_description="Extract named entities from the text according to the extraction spec",
    )
    return result.get("entities", [])


async def run_evaluation(args: argparse.Namespace) -> None:
    # Ensure worker root is on path for config import
    worker_root = str(Path(__file__).resolve().parent.parent.parent)
    if worker_root not in sys.path:
        sys.path.insert(0, worker_root)
    from orrery_relay import Relay
    from src.config import get_settings

    settings = get_settings()
    relay = Relay.from_settings(settings)
    model = settings.extraction_model
    chunk_size = settings.chunk_size

    # Load inputs
    candidate_spec = Path(args.candidate).read_text()
    golden_text = Path(args.golden_set).read_text()
    golden_entities = parse_golden_set(golden_text)

    if not golden_entities:
        print("ERROR: Golden set parsing yielded zero entities. Cannot evaluate.", file=sys.stderr)
        print(f"Golden set file: {args.golden_set}", file=sys.stderr)
        print(f"First 500 chars:\n{golden_text[:500]}", file=sys.stderr)
        sys.exit(1)

    sample_dir = Path(args.samples_dir)
    sample_files = sorted(sample_dir.glob("*.txt"))
    if not sample_files:
        print(f"ERROR: No .txt files found in {sample_dir}", file=sys.stderr)
        sys.exit(1)

    # Create eval output directory
    eval_dir = Path(args.output_dir) / f"eval-{args.iteration}"
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Run Haiku on each sample doc
    all_doc_results = []
    aggregate_hits = 0
    aggregate_misses = 0
    aggregate_fps = 0
    aggregate_near = 0
    aggregate_extracted = 0

    for doc_path in sample_files:
        doc_text = doc_path.read_text()
        chunks = chunk_text(doc_text, chunk_size=chunk_size)

        # Extract from each chunk, dedup per doc
        doc_entities: list[dict] = []
        seen: set[tuple[str, str]] = set()
        chunks_succeeded = 0
        for chunk in chunks:
            try:
                entities = await extract_chunk(
                    relay=relay, chunk_text=chunk, spec=candidate_spec, model=model
                )
                chunks_succeeded += 1
                for e in entities:
                    key = (e["name"].lower().strip(), e["type"])
                    if key not in seen:
                        seen.add(key)
                        doc_entities.append(e)
            except Exception as exc:
                print(f"  Warning: Haiku extraction failed on chunk of {doc_path.name}: {exc}", file=sys.stderr)

        if chunks and chunks_succeeded == 0:
            print(f"ERROR: All {len(chunks)} chunks failed for {doc_path.name}. Auth/model/network issue.", file=sys.stderr)
            sys.exit(1)

        # Write raw output
        output_file = eval_dir / f"{doc_path.stem}.json"
        output_file.write_text(json.dumps(doc_entities, indent=2))

        # Diff against golden set
        result = diff_entities(doc_entities, golden_entities)
        result["doc"] = doc_path.name
        all_doc_results.append(result)

        aggregate_hits += len(result["hits"])
        aggregate_misses += len(result["misses"])
        aggregate_fps += len(result["false_positives"])
        aggregate_near += len(result["near_misses"])
        aggregate_extracted += result["total_extracted"]

    # Compute cross-doc coverage: unique golden set entities found across ALL docs
    golden_set_tuples = {(n.lower().strip(), t.lower().strip()) for n, t in golden_entities}
    all_hit_keys: set[tuple[str, str]] = set()
    all_fp_keys: set[tuple[str, str]] = set()
    all_near_count = 0
    for r in all_doc_results:
        for e in r["hits"]:
            all_hit_keys.add((e["name"].lower().strip(), e["type"].lower().strip()))
        for e in r["false_positives"]:
            all_fp_keys.add((e["name"].lower().strip(), e["type"].lower().strip()))
        all_near_count += len(r["near_misses"])

    unique_extracted = all_hit_keys | all_fp_keys
    corpus_recall = len(all_hit_keys) / len(golden_set_tuples) if golden_set_tuples else 0.0
    corpus_precision = len(all_hit_keys) / len(unique_extracted) if unique_extracted else 0.0
    corpus_f1 = 2 * corpus_precision * corpus_recall / (corpus_precision + corpus_recall) if (corpus_precision + corpus_recall) > 0 else 0.0
    corpus_missed = golden_set_tuples - all_hit_keys

    # Print summary to stdout (this becomes evaluator_output for judges)
    print(f"=== Spec Evaluation — Iteration {args.iteration} ===")
    print()
    print("IMPORTANT: These metrics are APPROXIMATE. You MUST read the raw extraction")
    print("JSON files to score accurately. Open the files listed below and review what")
    print("Haiku actually extracted — the numbers alone cannot capture extraction quality.")
    print()
    print(f"CORPUS-WIDE COVERAGE:")
    print(f"  Golden set entities found: {len(all_hit_keys)}/{len(golden_set_tuples)} = {corpus_recall:.0%}")
    print(f"  Precision (across all docs): {corpus_precision:.0%}")
    print(f"  F1: {corpus_f1:.0%}")
    print(f"  Unique false positives: {len(all_fp_keys)}  |  Near-misses total: {all_near_count}")
    if corpus_missed:
        missed_str = ", ".join(f"{n} ({t})" for n, t in sorted(corpus_missed)[:15])
        extra = f" ... and {len(corpus_missed) - 15} more" if len(corpus_missed) > 15 else ""
        print(f"  NOT FOUND ANYWHERE: {missed_str}{extra}")
    print(f"\nTotal entities extracted across all docs: {aggregate_extracted}")
    print()

    print("--- Per-doc breakdown ---")
    for r in all_doc_results:
        print(f"{r['doc']}: extracted={r['total_extracted']}, hits={len(r['hits'])}, misses={len(r['misses'])}, false_pos={len(r['false_positives'])}, near_miss={len(r['near_misses'])}")
        if r["near_misses"]:
            near_str = ", ".join(f"{e['name']} ({e['type']})" for e in r["near_misses"])
            print(f"  Near-misses (name match, type differs): {near_str}")
        if r["misses"]:
            miss_str = ", ".join(f"{n} ({t})" for n, t in r["misses"][:10])
            extra = f" ... and {len(r['misses']) - 10} more" if len(r["misses"]) > 10 else ""
            print(f"  Missed: {miss_str}{extra}")
    print()

    print("--- Raw outputs ---")
    print(f"Read the full extraction results at: {eval_dir}")
    print(f"Files: {', '.join(f.name for f in sorted(eval_dir.glob('*.json')))}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate extraction spec against sample docs")
    parser.add_argument("--candidate", required=True, help="Path to candidate spec file")
    parser.add_argument("--samples-dir", required=True, help="Directory of sample .txt docs")
    parser.add_argument("--golden-set", required=True, help="Path to golden set file")
    parser.add_argument("--output-dir", required=True, help="Simmer output directory")
    parser.add_argument("--iteration", type=int, required=True, help="Iteration number")
    args = parser.parse_args()
    asyncio.run(run_evaluation(args))


if __name__ == "__main__":
    main()
