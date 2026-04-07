#!/usr/bin/env python
# ABOUTME: Standalone evaluator for image spec simmering — runs candidate spec against sample images via VLLM.
# ABOUTME: Compares extracted entities + descriptions against the per-image golden set.

"""
Image spec evaluator for simmer Phase 2.

Invoked as a subprocess by simmer-sdk's evaluator mechanism.
Reads the image golden set (per-image entities + descriptions),
runs the candidate spec against each sample image via VLLM,
writes raw outputs, and reports coverage + description quality.
"""

import argparse
import asyncio
import base64
import json
import re
import sys
from pathlib import Path


def parse_image_golden_set(text: str) -> list[dict]:
    """Parse image golden set into per-image reference entries.

    Expected format:
    [
      {
        "image": "filename",
        "entities": [{"name": "...", "type": "..."}, ...],
        "description": "...",
        "tags": [...]
      },
      ...
    ]
    """
    try:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if isinstance(data, list):
                entries = []
                for item in data:
                    if isinstance(item, dict) and "entities" in item:
                        entries.append({
                            "image": item.get("image", ""),
                            "entities": [
                                (e["name"].lower().strip(), e["type"].lower().strip())
                                for e in item.get("entities", [])
                                if isinstance(e, dict) and "name" in e and "type" in e
                            ],
                            "description": item.get("description", ""),
                            "tags": item.get("tags", []),
                        })
                return entries
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def diff_entities(extracted: list[dict], golden: list[tuple[str, str]]) -> dict:
    """Compare extracted entities against golden set for one image."""
    golden_set = {(n, t) for n, t in golden}

    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for e in extracted:
        key = (e["name"].lower().strip(), e["type"].lower().strip())
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    hits = []
    false_positives = []
    for e in deduped:
        key = (e["name"].lower().strip(), e["type"].lower().strip())
        if key in golden_set:
            hits.append(e)
        else:
            false_positives.append(e)

    hit_keys = {(e["name"].lower().strip(), e["type"].lower().strip()) for e in hits}
    misses = [(n, t) for n, t in golden_set if (n, t) not in hit_keys]

    return {
        "hits": len(hits),
        "misses": len(misses),
        "false_positives": len(false_positives),
        "total_extracted": len(deduped),
        "total_golden": len(golden_set),
    }


async def run_evaluation(args: argparse.Namespace) -> None:
    worker_root = str(Path(__file__).resolve().parent.parent.parent)
    if worker_root not in sys.path:
        sys.path.insert(0, worker_root)
    from orrery_relay import Relay
    from src.config import get_settings

    settings = get_settings()
    relay = Relay.from_settings(settings)
    model = settings.extraction_model

    # Load inputs
    candidate_spec = Path(args.candidate).read_text()
    golden_text = Path(args.golden_set).read_text()
    golden_entries = parse_image_golden_set(golden_text)

    if not golden_entries:
        print("ERROR: Golden set parsing yielded zero image entries.", file=sys.stderr)
        sys.exit(1)

    # Flatten all golden entities for corpus-wide metrics
    all_golden = set()
    for entry in golden_entries:
        all_golden.update(entry["entities"])

    print(f"Golden set: {len(golden_entries)} images, {len(all_golden)} unique entities")

    sample_dir = Path(args.samples_dir)
    sample_files = sorted(
        f for f in sample_dir.iterdir()
        if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    )
    if not sample_files:
        print(f"ERROR: No image files in {sample_dir}", file=sys.stderr)
        sys.exit(1)

    eval_dir = Path(args.output_dir) / f"eval-{args.iteration}"
    eval_dir.mkdir(parents=True, exist_ok=True)

    schema = {
        "type": "object",
        "properties": {
            "entities": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "type": {"type": "string"}}, "required": ["name", "type"]}},
            "description": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["entities", "description", "tags"],
    }

    # Run spec against each sample image
    all_doc_results = []
    for img_path in sample_files:
        b64 = base64.b64encode(img_path.read_bytes()).decode()
        suffix = img_path.suffix.lower()
        media_type = "image/jpeg"
        if suffix == ".png": media_type = "image/png"
        elif suffix == ".webp": media_type = "image/webp"

        try:
            result = await relay.complete_structured(
                model=model, max_tokens=4096,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": candidate_spec},
                ]}],
                schema=schema,
                tool_name="extract_image",
                tool_description="Extract entities and metadata from an image",
            )
        except Exception as exc:
            print(f"  Warning: VLLM failed for {img_path.name}: {exc}", file=sys.stderr)
            result = {"entities": [], "description": "", "tags": []}

        # Write raw output
        output_file = eval_dir / f"{img_path.stem}.json"
        output_file.write_text(json.dumps(result, indent=2))

        # Find matching golden entry
        golden_match = None
        for entry in golden_entries:
            if img_path.stem in entry["image"] or entry["image"] in img_path.stem:
                golden_match = entry
                break

        extracted_entities = result.get("entities", [])
        if golden_match:
            diff = diff_entities(extracted_entities, golden_match["entities"])
        else:
            diff = {"hits": 0, "misses": 0, "false_positives": len(extracted_entities), "total_extracted": len(extracted_entities), "total_golden": 0}

        diff["doc"] = img_path.name
        diff["description"] = result.get("description", "")[:100]
        diff["has_golden"] = golden_match is not None
        all_doc_results.append(diff)

    # Corpus-wide metrics
    all_hit_keys: set[tuple[str, str]] = set()
    all_fp_count = 0
    descriptions_generated = 0
    for r in all_doc_results:
        all_fp_count += r["false_positives"]
        if r["description"]:
            descriptions_generated += 1
        # Re-read the raw output to get entity keys
        output_file = eval_dir / f"{r['doc'].rsplit('.', 1)[0]}.json"
        if output_file.exists():
            raw = json.loads(output_file.read_text())
            for e in raw.get("entities", []):
                all_hit_keys.add((e["name"].lower().strip(), e.get("type", "").lower().strip()))

    corpus_hits = all_hit_keys & all_golden
    corpus_recall = len(corpus_hits) / len(all_golden) if all_golden else 0.0
    corpus_precision = len(corpus_hits) / len(all_hit_keys) if all_hit_keys else 0.0

    # Print summary
    print(f"\n=== Image Spec Evaluation — Iteration {args.iteration} ===")
    print()
    print("IMPORTANT: Read the raw extraction JSON files to score accurately.")
    print("Check both entity extraction AND description quality per image.")
    print()
    print(f"CORPUS-WIDE COVERAGE:")
    print(f"  Golden entities matched: {len(corpus_hits)}/{len(all_golden)} = {corpus_recall:.0%}")
    print(f"  Precision: {corpus_precision:.0%}")
    print(f"  Descriptions generated: {descriptions_generated}/{len(sample_files)}")
    print()

    print("--- Per-image breakdown ---")
    for r in all_doc_results:
        golden_tag = "" if r["has_golden"] else " (no golden ref)"
        print(f"  {r['doc']}: {r['total_extracted']} extracted, {r['hits']} hits, {r['misses']} misses, {r['false_positives']} FP{golden_tag}")
        if r["description"]:
            print(f"    desc: {r['description']}...")
    print()

    print(f"--- Raw outputs at: {eval_dir} ---")
    print(f"Files: {', '.join(f.name for f in sorted(eval_dir.glob('*.json')))}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate image extraction spec")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--samples-dir", required=True)
    parser.add_argument("--golden-set", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--iteration", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(run_evaluation(args))


if __name__ == "__main__":
    main()
