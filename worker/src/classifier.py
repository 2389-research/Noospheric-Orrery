# ABOUTME: Domain classification for repo ingest — classifies on the grounded
# ABOUTME: repo-level summary. CANONICAL COPY: orchestrator/src/pipeline/classifier.py
# ABOUTME: (the CLASSIFICATION_PROMPT / SCHEMA must stay in sync across both, like db.py).

from orrery_relay import Relay

CLASSIFICATION_PROMPT = """You are a domain classifier for a COMPANY knowledge graph that holds code, documents, notes, reports — everything the organization knows. Given an excerpt (a code repo/module/file summary, OR a note/report/doc) and the existing taxonomy, assign it to domain paths.

Domain paths are hierarchical, lowercase, "/"-separated, using hyphenated singular nouns:
  region/category/topic   (e.g. software/backend/rest-api, business/finance/budgeting, product/product-management/roadmap)

Two facets:
  PRIMARY  = the main subject — what this content IS about. It can be in ANY region (software, business, product, operations, people, research, ...), not just software.
  SECONDARY (0-3) = extra context: a second subject area, the industry it serves (under `industry/`), or a notable technology/topic.

Classify by SUBJECT, not by employer. Even at a software company, plenty of notes are not about software: a hiring rubric or interview scorecard is `people/hiring`; a contract/legal/policy doc is `business/legal-compliance`; budgets/expenses/runway are `business/finance`; office, vendor, or logistics notes are `operations/...`; a roadmap or spec is `product/...`. Pick the region that best fits the subject.

Naming rules (follow exactly — consistent naming is what lets equivalent content from different sources merge into one node):
  - all lowercase; words joined by single hyphens; singular nouns (rest-api, not REST_APIs or rest_apis)
  - REUSE a path from the reference vocabulary or the existing taxonomy whenever it fits — never invent a near-duplicate (use `llm-orchestration`, not `llm_agents` or `agent-coordination`)
  - be specific: prefer `business/finance/budgeting` over just `business/finance`

REFERENCE VOCABULARY — a strong baseline. Reuse these; you MAY add a new topic (or, when nothing fits, a new category or region) following the same naming rules:
{reference_vocab}

industry/<sector> — use as SECONDARY when the content clearly serves a sector: fintech, healthtech, edtech, ecommerce, gaming, media-streaming, adtech-martech, govtech-civic, logistics-supply-chain, proptech, hr-tech, legal-tech, biotech, energy-climate, telecom, security-defense

Existing taxonomy (already in this graph — reuse a path from here ONLY when it is the SAME topic; it is NOT a preference, and a graph full of software paths must not pull unrelated content toward software):
{taxonomy}

Document:
{excerpt}

Assign 1 primary domain, 0-3 secondary domains, and a confidence 0.0-1.0.

If (and ONLY if) this excerpt is a CODE REPOSITORY summary, ALSO identify SUBDOMAINS (4-8): finer leaf paths capturing the DISTINCT internal components/topics within the repo (a parser, an async-runtime, ffi-bindings, a cli) — individual files are placed by matching them to these, so make them genuinely distinct facets, not synonyms of the primary. For a single note/document, leave subdomains empty.

Worked examples:
- A React component library with themeable design tokens -> primary software/frontend/design-systems; secondary [software/frontend/accessibility]; subdomains [software/frontend/state-management, software/frontend/accessibility, software/developer-tools/build-systems, software/testing-qa/unit-testing]
- A Django service that processes card payments and runs fraud checks -> primary software/backend/rest-api; secondary [software/security/threat-detection, industry/fintech]; subdomains [software/backend/authentication, software/security/threat-detection, software/databases/relational, software/backend/background-jobs]
- A quarterly board report on runway and hiring plans -> primary business/finance/financial-planning; secondary [people/hiring/recruiting, business/strategy/okrs-goals]; subdomains []
- A meeting note deciding Q3 product roadmap priorities -> primary product/product-management/roadmap; secondary [product/product-management/prioritization]; subdomains []
- A doc describing the internal on-call rotation and incident process -> primary operations/internal-operations/processes-workflows; secondary [software/devops-infra/site-reliability]; subdomains []
"""

CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "primary_domain": {"type": "string", "description": "Primary domain path (region/category/topic)"},
        "secondary_domains": {"type": "array", "items": {"type": "string"}, "description": "0-3 secondary domain paths"},
        "subdomains": {"type": "array", "items": {"type": "string"}, "description": "4-8 finer leaf paths for a code repo's distinct internal components/topics (empty for a single document)"},
        "confidence": {"type": "number", "description": "Classification confidence 0.0-1.0"},
    },
    "required": ["primary_domain", "secondary_domains", "confidence"],
}


async def classify_document(
    relay: Relay, title: str, excerpt: str, existing_taxonomy: list[str], model: str,
) -> dict:
    from .taxonomy import reference_vocab_text
    taxonomy_str = "\n".join(f"  - {d}" for d in existing_taxonomy) if existing_taxonomy else "  (empty — propose new domains)"
    return await relay.complete_structured(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": CLASSIFICATION_PROMPT.format(
            reference_vocab=reference_vocab_text(), taxonomy=taxonomy_str, excerpt=excerpt)}],
        schema=CLASSIFICATION_SCHEMA,
        tool_name="classify_document",
        tool_description="Classify a document into domain paths for the knowledge graph",
    )
