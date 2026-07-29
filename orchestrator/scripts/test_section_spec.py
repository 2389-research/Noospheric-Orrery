# ABOUTME: Standalone CLI to test a research_paper section spec against a real PDF.
# ABOUTME: Prints a raw entity dump per chunk for manual spec iteration — no scoring.
#
# Requires the orchestrator's dependencies to be installed (e.g. `cd orchestrator && uv sync
# --extra dev` or `pip install -e .`) and a working .env / backend configuration per CLAUDE.md's
# "Starting the Services" section (any of gateway/bedrock/ollama). Run with:
#   uv run python scripts/test_section_spec.py --paper ../pi0/papers/kimOpenVLA2024.pdf --all-sections

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
from src.pipeline.chunker import chunk_document
from src.pipeline.extractor import extract_entities_from_chunk
from src.pipeline.file_extractor import extract_text_from_pdf
from src.pipeline.section_splitter import label_sections
from orrery_relay import Relay

_SPECS_DIR = Path(__file__).resolve().parent.parent / "specs" / "research_paper"


def _load_section_spec(section: str) -> str:
    shared = (_SPECS_DIR / "shared.md").read_text()
    section_file = _SPECS_DIR / f"{section}.md"
    if not section_file.exists():
        section_file = _SPECS_DIR / "default.md"
    return shared + "\n\n---\n\n" + section_file.read_text()


async def run(paper_path: str, target_section: str | None) -> None:
    settings = get_settings()
    relay = Relay.from_settings(settings)

    file_bytes = Path(paper_path).read_bytes()
    text = extract_text_from_pdf(file_bytes)

    spans = await label_sections(relay, text, model=settings.extraction_model)
    print(f"Detected {len(spans)} section span(s):")
    for span in spans:
        print(f"  [{span['section']}] chars {span['start']}-{span['end']} ({span['end'] - span['start']} chars)")
    print()

    for span in spans:
        if target_section and span["section"] != target_section:
            continue
        span_text = text[span["start"]:span["end"]]
        spec = _load_section_spec(span["section"])
        chunks = chunk_document(span_text, chunk_size=settings.chunk_size)
        print(f"=== Section: {span['section']} ({len(chunks)} chunk(s)) ===")
        for i, chunk in enumerate(chunks):
            entities = await extract_entities_from_chunk(
                relay=relay, chunk_text=chunk["text"], spec=spec, model=settings.extraction_model,
            )
            print(f"  --- chunk {i} ---")
            for entity in entities:
                print(f"    {entity['type']}: {entity['name']}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test a research_paper section spec against a real PDF")
    parser.add_argument("--paper", required=True, help="Path to a PDF file, e.g. pi0/papers/kimOpenVLA2024.pdf")
    parser.add_argument("--section", help="Only test this section (introduction, method, etc.)")
    parser.add_argument("--all-sections", action="store_true", help="Test every detected section")
    args = parser.parse_args()

    if not args.section and not args.all_sections:
        parser.error("Pass --section <name> or --all-sections")

    asyncio.run(run(args.paper, args.section))


if __name__ == "__main__":
    main()
