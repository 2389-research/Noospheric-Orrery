# Domain Classification

How documents get assigned to semantic topic categories in the adaptive knowledge graph.

**Current implementation note:** the live pipeline classifies each document/image against the current taxonomy, stores the assigned paths immediately, and creates new domain rows as needed. Domain label normalization is currently conservative: `domain_merge_map` lookup, exact path match, then insert. The embedding/cluster/LLM review process below remains useful design history, but it is not wired into the ingest path today.

## What Is a Domain?

A domain is an **inferred meta-category** describing what a document is about.

| Property | Description |
|----------|-------------|
| Not explicit | Does not have to appear in the text. Inferred from entity profile + context. |
| Hierarchical | Tree paths: `techniques/blending/wet-on-wet` |
| Multi-assigned | Each document gets one primary domain and 0-3 secondary domains with confidence values |
| Open-ended | New domains can be proposed by the classifier at any time |
| Emergent | Taxonomy grows from the data, not from a predefined schema |

### How Domains Differ From Entities

- **Entities** are grounded — extracted from text, verifiable, countable
- **Domains** are interpretive — a judgment about what the content covers
- An entity CAN name a domain ("non-metallic metal" is both), but the domain is the community/topic, not the single term
- Domains are a layer above entities in the semantic hierarchy

## Classification Process

### Step 1: Generate

For each document, a classifier reads an adaptive excerpt plus the existing taxonomy and proposes one primary and 0-3 secondary hierarchical domain paths. Images are described/classified by the vision-capable classification model and then stored as image documents.

**Input:** Document title/content excerpt, or an image plus optional caption, and the current taxonomy.
**Output:** `primary_domain`, `secondary_domains`, and `confidence`.

```json
{
  "primary_domain": "techniques/blending",
  "secondary_domains": ["fundamentals/beginner-tips"],
  "confidence": 0.82
}
```

**Granularity guidance:**
- Too broad: "Miniature Painting" (everything falls here)
- Too specific: "Thinning Rhinox Hide on a Wet Palette" (one step in one video)
- Right level: "techniques/nmm", "fundamentals/tools", "theory/color-theory"

**The classifier sees the existing taxonomy** and either assigns to known domains or proposes new branches. This is how the taxonomy grows organically.

### Step 2: Normalize

Raw domain labels can proliferate because different documents may independently propose labels like "NMM Techniques" vs "Non-Metallic Metal" vs "Advanced Metal Painting."

**Live implementation:**
1. Check `domain_merge_map` for a known alias
2. Reuse an exact existing domain path when present
3. Otherwise insert a new `domains` row with `parent_path` derived from the slash-separated path
4. Assign the document in `document_domains` and increment `domains.document_count`

**Experimental/desired clustering process:**

1. Embed all unique domain labels with all-MiniLM-L6-v2
2. Cluster by cosine similarity
3. A reviewer (LLM) examines each cluster and picks canonical names
4. Apply merge map to all documents

**Validated merge rules from our experiment (40 → 23 domains):**

| Merge | Reason |
|---|---|
| tool-overview + tool-setup + tool-care → tools | Same conceptual space |
| value-contrast + color-and-value → value-and-contrast | Naming inconsistency |
| lighting + focal-point → lighting-and-composition | Co-dependent concepts |
| oil-washing + chipping + weathering → weathering | Sub-techniques of parent |
| glow-effects + osl → osl | Same technique, two names |
| glazing + volumetric → blending | Sub-methods of blending |
| zenithal → airbrush | Zenithal is an airbrush technique |
| display-artistic + eavy-metal → display | Same style tier |
| sculpting → kitbashing | Co-taught in the hobby |
| community → experiments | Overlapping content types |

**What NOT to merge (from entity normalization learnings):**
- Color shades are distinct (dark beige ≠ light beige)
- Brand ≠ product (artist opus ≠ artist opus one)
- Tool ≠ activity (3d printer ≠ 3d printing)

### Step 3: Reclassify After Simmering

When a domain spec is simmered, the enriched entity profiles may reveal subdomains. In the live app this is exposed separately through `POST /discover-subdomains`, which adds subdomain tags to existing documents without removing earlier assignments. The V3 adaptive experiment discovered 9 new subdomains from 20 tutorials:

```
techniques/airbrush/equipment-and-setup
techniques/blending/layering-and-glazing
techniques/blending/wet-on-wet
techniques/kitbashing/character-conversion
techniques/speed-painting/volumetric-method
techniques/weathering/chipping-methods
fundamentals/tools/brush-care
fundamentals/tools/wet-palette
theory/value-and-contrast/monochrome
styles/grimdark/oil-paint-methods
```

Each subdomain is a deeper specialization that the general extraction spec would not have caught. Reclassification/subdomain discovery is additive: affected documents gain additional domain assignments.

## The Taxonomy (Final State)

6 top-level regions, 23 parent domains, 9 subdomains = 32 total.

```
techniques/               (8 parents + 5 subdomains)
  airbrush/
    equipment-and-setup*
  blending/
    layering-and-glazing*
    wet-on-wet*
  faces-and-eyes
  kitbashing/
    character-conversion*
  nmm
  osl
  speed-painting/
    volumetric-method*
  weathering/
    chipping-methods*

fundamentals/             (5 parents + 2 subdomains)
  3d-printing
  beginner-tips
  brushes
  first-miniature
  tools/
    brush-care*
    wet-palette*

projects/                 (2 parents)
  army-painting
  competition-piece

theory/                   (3 parents + 1 subdomain)
  color-theory
  lighting-and-composition
  value-and-contrast/
    monochrome*

challenges/               (3 parents)
  24h-painting
  experiments
  golden-demon

styles/                   (2 parents + 1 subdomain)
  display
  grimdark/
    oil-paint-methods*
```

*Items marked with * are subdomains discovered by the V3 adaptive spec.*

## How This Maps to the Adaptive System

Domain classification is **Operation A** from the adaptive extraction design:

1. **Cold start:** Classifier proposes domains from scratch for each document. Taxonomy grows organically.
2. **Steady state:** Classifier sees existing taxonomy. Assigns to known domains or proposes new branches.
3. **After simmering:** Enriched entity profiles can reveal subdomains. `POST /discover-subdomains` can add them as extra assignments.
4. **Validation (optional):** Entity co-occurrence graph confirms domain coherence. Not the driver — just a quality check.

**Leiden/Louvain community detection** was considered for domain discovery but rejected:
- Gives a snapshot that shifts when the graph changes
- Doesn't tell you what the cluster means — still need LLM to name it
- The classifier does the whole thing: discover + name + assign
- Community detection is useful as validation, not discovery

## UMAP Layout for Visualization

Domains get 2D positions via UMAP projection of their semantic embeddings:

```python
embed_input(domain) = concat(
    domain_path_string,
    top_video_titles[:6],
    top_entity_names[:12]
)
# Embedded with all-MiniLM-L6-v2
# UMAP: cosine metric, min_dist=0.15, spread=2.5
```

**Key property:** `umap_model.transform()` places new domains into existing space without moving anything. The map is stable. Only periodic re-projection events (when domain count doubles) rearrange the layout.

Subdomains are positioned via hybrid of UMAP transform + parent-relative offset — close to parent but offset in the direction they semantically diverge.

## Experiment Data

All experiment artifacts:
```
DS-scratch/warhammer_mini_sizes/experiments/domain-classification/
  experiment_notes.md           # Design decisions
  raw_classifications.json      # 40-domain raw taxonomy
  normalized_domains.json       # 23-domain normalized taxonomy
  v3_reclassifications.json     # V3 reclassification + 9 subdomains
```

## Open Questions

1. **Weighting domains per document.** Currently flat (document is "in" a domain or not). Should be weighted (60% NMM, 30% Character Painting). The entity profile can provide this — ratio of entities matching each domain's signature.

2. **Domain lifecycle.** The current text auto-trigger is `DOMAIN_SPEC_THRESHOLD` (default 20 documents), while the UI exposes manual refine buttons at smaller counts for testing. The original adaptive spec's 100-document threshold is design history, not the current default.

3. **Domain name quality.** LLM-generated names can be inconsistent. Need a naming convention or a dedicated naming step post-normalization.

4. **Cross-domain entity attribution.** An entity like "non-metallic metal" appeared in 13 videos but only got NMM domain weight after manual patching. The classifier should use entity-name-to-domain-name semantic similarity as a signal.
