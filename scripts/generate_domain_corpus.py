"""Generate a diverse corpus of ~100 domain paths via Sonnet.

Outputs: orchestrator/specs/universal_domains.json

Review the output before using it to train the UMAP model.
"""
import json
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "orrery-relay", "src"))
from orrery_relay import Relay

CATEGORIES = [
    "business and finance (startups, fundraising, operations, marketing, strategy, consulting, real estate, accounting)",
    "science and research (physics, chemistry, biology, neuroscience, ecology, astronomy, geology, materials science)",
    "technology and engineering (AI/ML, web development, mobile, DevOps, robotics, embedded systems, security, databases)",
    "arts and creative (painting, music, film, photography, sculpture, writing, theater, graphic design)",
    "hobbies and crafts (miniature painting, woodworking, gardening, cooking, brewing, sewing, model building, ceramics)",
    "health and medicine (cardiology, oncology, mental health, nutrition, physical therapy, epidemiology, genomics)",
    "education and academia (pedagogy, curriculum design, educational technology, student assessment, research methodology)",
    "sports and fitness (basketball, climbing, swimming, martial arts, cycling, yoga, track and field)",
    "history and humanities (ancient history, philosophy, linguistics, archaeology, anthropology, religious studies)",
    "environment and sustainability (renewable energy, conservation, urban planning, waste management, climate science)",
]


class FakeSettings:
    anthropic_backend = os.environ.get("ANTHROPIC_BACKEND", "bedrock")
    gateway_url = os.environ.get("GATEWAY_URL", "")
    aws_access_key = os.environ.get("AWS_ACCESS_KEY", "")
    aws_secret_key = os.environ.get("AWS_SECRET_KEY", "")
    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    ollama_url = os.environ.get("OLLAMA_URL", "")


async def generate_batch(relay, category, n=10):
    prompt = f"""Generate exactly {n} domain classification paths for documents about: {category}

Each path should be 3 levels deep using / as separator, lowercase with hyphens.
Format: one path per line, nothing else.

Example format:
business/fundraising/seed-rounds
science/physics/quantum-mechanics
hobbies/miniature-painting/wet-blending

Be specific and diverse within the category. No duplicates. No numbering."""

    response = await relay.complete(
        model=os.environ.get("CLASSIFICATION_MODEL", "claude-sonnet-4-6"),
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    paths = [line.strip() for line in response.text.strip().split("\n") if "/" in line and len(line.strip()) > 5]
    return paths[:n]


async def main():
    relay = Relay.from_settings(FakeSettings())

    all_domains = []
    for i, category in enumerate(CATEGORIES):
        print(f"[{i+1}/{len(CATEGORIES)}] {category[:50]}...")
        try:
            domains = await generate_batch(relay, category, n=10)
            all_domains.extend(domains)
            for d in domains:
                print(f"  {d}")
        except Exception as e:
            print(f"  FAILED: {e}")

    # Deduplicate
    all_domains = list(dict.fromkeys(all_domains))

    # Group by top-level for review
    groups = {}
    for d in all_domains:
        top = d.split("/")[0]
        groups.setdefault(top, []).append(d)

    print(f"\n{'='*60}")
    print(f"Total: {len(all_domains)} unique domains across {len(groups)} top-level categories")
    for top, paths in sorted(groups.items()):
        print(f"  {top}: {len(paths)}")

    # Save
    output_path = os.environ.get("OUTPUT_PATH", os.path.join(os.path.dirname(__file__), "..", "orchestrator", "specs", "universal_domains.json"))
    with open(output_path, "w") as f:
        json.dump({"domains": all_domains, "count": len(all_domains), "categories": list(groups.keys())}, f, indent=2)
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
