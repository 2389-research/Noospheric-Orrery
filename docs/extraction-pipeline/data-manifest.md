# Data Manifest: Extracted Entity Data for Graph

## Extraction Output (20 tutorials, 228 entities)

**Directory:** `/Users/michaelsugimura/Documents/GitHub/DS-scratch/warhammer_mini_sizes/experiments/adaptive-spec-simmering/haiku_20_tutorial_extraction/`

**Files:** 20 JSON files, one per video tutorial.

### Per-file structure:

```json
{
  "video_id": "S7-At4qVC84",
  "title": "Ultimate guide to painting your first miniature",
  "chunks": 8,
  "raw_entities": 45,
  "deduped_entities": 14,
  "entities": [
    {
      "name": "priming",
      "type": "technique",
      "rationale": "Described as the first step before painting — applying primer coat"
    },
    {
      "name": "Citadel",
      "type": "paint_brand",
      "rationale": "Named paint brand used throughout tutorial"
    }
  ]
}
```

### Entity fields:
- `name` (string): Canonical entity name, garble-corrected where applicable
- `type` (string): One of 15 types (see taxonomy below)
- `rationale` (string): Why this entity was extracted — source attribution

### Video fields:
- `video_id` (string): YouTube video ID
- `title` (string): Video title (may be empty for some)
- `chunks` (int): Number of 5-min transcript chunks processed
- `raw_entities` (int): Entities before deduplication
- `deduped_entities` (int): Entities after within-video dedup
- `entities` (array): The deduplicated entity list

## Gold Standard (20 eval segments, 156 entities)

**Directory:** `/Users/michaelsugimura/Documents/GitHub/DS-scratch/warhammer_mini_sizes/experiments/adaptive-spec-simmering/sdk_gold_standard/`

**Files:** 20 JSON files, named `{video_id}_{start_s}_{end_s}_gold.json`

### Per-file structure:

```json
{
  "video_id": "BLOT1Jkq9wk",
  "start_s": 1200,
  "end_s": 1500,
  "entities": [
    {
      "name": "Squidmar",
      "type": "person",
      "rationale": "Channel creator delivering an airbrush tutorial"
    }
  ]
}
```

## Extraction Spec (what generated the entities)

**Best spec:** `/Users/michaelsugimura/Documents/GitHub/DS-scratch/warhammer_mini_sizes/experiments/adaptive-spec-simmering/sdk_spec_simmer_haiku/iteration-1-candidate.md`

This is the prompt that was given to Claude Haiku to extract entities from transcript chunks. It was generated automatically via the simmer-sdk pipeline.

## Entity Type Taxonomy (15 types)

| Type | Description | Example entities |
|------|-------------|-----------------|
| `technique` | Painting or modeling method | layering, drybrushing, edge highlighting, glazing, priming, wet blending |
| `game_ref` | Game system, faction, universe | Warhammer 40k, Space Marines, Age of Sigmar, Wood Elves |
| `tool` | Physical tool or equipment | airbrush, wet palette, compressor, brush, sculpting tool |
| `paint_brand` | Paint manufacturer or line | Citadel, Vallejo, Games Workshop, Army Painter, Scale75 |
| `principle` | Guiding rule or best practice | thin your paints, light from above, paint dark to light |
| `medium` | Additive, thinner, or liquid | primer, thinner, contrast medium, flow improver |
| `model_part` | Component/area of miniature | face, armor, scales, knee pads, base, shoulder pad |
| `color` | Abstract color reference | white, gold, blue, orange brown, dark green |
| `person` | Named individual | Emil, Marco Frisoni, Duncan Rhodes |
| `concept` | Abstract idea or theory | color theory, gradient, OSL, NMM, focal point |
| `topic` | Overarching subject | miniature painting, competition judging, airbrush basics |
| `paint` | Specific paint product | contrast paints, Rhinox Hide, Nuln Oil |
| `material` | Physical material | cork, sand, Green Stuff, rust pigments |
| `model` | Specific miniature or kit | Sanguinor, Imperial Knight, Space Marine Terminator |
| `assembly` | Assembly/construction method | kitbash, magnetizing |

## Graph Design Notes

**Node identity:** Use `name.lower().strip()` as the dedup key. Entities with the same normalized name across videos should merge into a single node.

**Edge construction:** Two entities appearing in the same video get a co-occurrence edge. Weight = number of videos where both appear.

**Provenance:** Each node should track which `video_id`s it came from. The `rationale` field provides per-extraction citation text.

**Known issues:**
- Person/speaker names (Squidmar, Trovarion) are inconsistently extracted — the model can't infer who's speaking from transcript alone
- Some entities need normalization: "paint thinning" and "thinning paint" are the same technique
- Type taxonomy was auto-discovered — some overlap with broader domain types

## Full Design Spec

For the complete adaptive extraction system design, see:
`/Users/michaelsugimura/Documents/GitHub/infodesk/docs/superpowers/specs/2026-03-24-adaptive-knowledge-graph-extraction-design.md`

## Experiment Notes

For detailed pipeline notes, results, and analysis, see:
`/Users/michaelsugimura/Documents/GitHub/DS-scratch/warhammer_mini_sizes/experiments/adaptive-spec-simmering/sdk_experiment_notes.md`
