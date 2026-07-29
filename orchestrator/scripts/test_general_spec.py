# ABOUTME: Standalone CLI to run the general_text.md spec against a slice of a real PDF.
# ABOUTME: Companion to test_section_spec.py, for comparing general vs. domain extraction side by side.

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
from src.pipeline.chunker import chunk_document
from src.pipeline.extractor import extract_entities_from_chunk
from src.pipeline.file_extractor import extract_text_with_font_runs
from src.pipeline.section_splitter import label_sections, SKIP_SECTIONS
from orrery_relay import Relay

_GENERAL_SPEC_PATH = Path(__file__).resolve().parent.parent / "specs" / "general_text.md"


async def run(paper_path: str, target_section: str | None) -> None:
    settings = get_settings()
    relay = Relay.from_settings(settings)
    spec = _GENERAL_SPEC_PATH.read_text()

    file_bytes = Path(paper_path).read_bytes()
    text, font_runs = extract_text_with_font_runs(file_bytes)

    spans = await label_sections(relay, text, model=settings.extraction_model, font_runs=font_runs)
    print(f"Detected {len(spans)} section span(s):")
    for span in spans:
        print(f"  [{span['section']}] chars {span['start']}-{span['end']} ({span['end'] - span['start']} chars)")
    print()

    for span in spans:
        if target_section and span["section"] != target_section:
            continue
        if span["section"] in SKIP_SECTIONS:
            print(f"=== Section: {span['section']} — skipped (never extracted) ===\n")
            continue
        span_text = text[span["start"]:span["end"]]
        chunks = chunk_document(span_text, chunk_size=settings.chunk_size)
        print(f"=== Section: {span['section']} ({len(chunks)} chunk(s)) — GENERAL SPEC ===")
        for i, chunk in enumerate(chunks):
            entities = await extract_entities_from_chunk(
                relay=relay, chunk_text=chunk["text"], spec=spec, model=settings.extraction_model,
            )
            print(f"  --- chunk {i} ---")
            for entity in entities:
                print(f"    {entity['type']}: {entity['name']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the general_text.md spec against a section of a real PDF")
    parser.add_argument("--paper", required=True, help="Path to a PDF file, e.g. pi0/papers/kimOpenVLA2024.pdf")
    parser.add_argument("--section", help="Only test this section (introduction, method, etc.)")
    parser.add_argument("--all-sections", action="store_true", help="Test every detected section")
    args = parser.parse_args()

    if not args.section and not args.all_sections:
        parser.error("Pass --section <name> or --all-sections")

    asyncio.run(run(args.paper, args.section))


if __name__ == "__main__":
    main()
