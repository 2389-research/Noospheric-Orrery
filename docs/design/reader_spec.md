# Document Reader — Implementation Spec

## Overview

The document reader is a mode within the batch extraction page (`/extraction/{job_id}`). It activates when a user clicks a doc row in the doc list. It replaces the entity grid in the right pane — the doc list on the left stays visible and active.

The reader has one job: **make extracted entities legible in context.** Every design decision serves that goal. The user should be able to read the document naturally and discover entities by interacting with the text, or navigate entities by interacting with the sidebar and watch the text respond.

---

## Where it fits in the page

```
/extraction/{job_id}  — default state
┌─────────────────┬──────────────────────────────────┐
│ Doc list        │ Entity grid (batch mode)          │
│                 │                                   │
│ > q3-plan… 31  │ [Sarah Chen] [Marcus Webb] ...    │
│   investor… 28  │ [Orbit Dashboard] [DataSync] ...  │
│   roadmap… 24   │                                   │
└─────────────────┴──────────────────────────────────┘

Click a doc row → reader mode activates in right pane
┌─────────────────┬────────────┬──────────────────────┐
│ Doc list        │ Entity     │ Document text         │
│                 │ sidebar    │                       │
│ > q3-plan… 31  │ Person     │ Meeting notes —       │
│   investor… 28  │  Sarah C.  │ Q3 planning session   │
│   roadmap… 24   │  Marcus W. │                       │
│                 │ Product    │ Attendees: [Sarah C.] │
│                 │  Orbit D.  │ (facilitator),        │
│                 │  DataSync  │ [Marcus Webb] (infra)  │
└─────────────────┴────────────┴──────────────────────┘
```

The right pane splits into two columns: entity sidebar (fixed ~172px) and document text (fills remaining). This is a grid layout change on the right pane only — the outer doc list column does not change.

---

## Component hierarchy

```
ExtractionPage (existing)
└── RightPane
    ├── [batch mode]  EntityPanel + BottomRow   ← default
    └── [reader mode] ReaderPane                ← on doc click
        ├── ReaderHeader
        ├── ReaderShell (two-column grid)
        │   ├── EntitySidebar
        │   │   ├── SidebarHeader
        │   │   └── SidebarGroup × N (one per type)
        │   │       └── SidebarRow × N (one per entity)
        │   │           ├── EntityName
        │   │           ├── NewBadge (conditional)
        │   │           └── OccurrenceMinimap
        │   └── DocumentPanel
        │       ├── DocumentHeader
        │       └── DocumentBody
        │           └── mixed spans: plain text + HighlightSpan × N
        └── Tooltip (fixed positioned, shared)
```

---

## State model

One shared state object drives everything. Both sidebar and document are derived views of this state — they never diverge.

```typescript
type ReaderId = string; // entity id e.g. "e1"

interface ReaderState {
  activeDoc: string | null;      // which doc is open
  hovered: ReaderId | null;      // from mouseover, either surface
  pinned: ReaderId | null;       // from click, either surface
}

// Derived — what is "selected" right now
function getActive(state: ReaderState): ReaderId | null {
  return state.pinned ?? state.hovered ?? null;
}
```

**Rule:** `pinned` takes precedence over `hovered`. When something is pinned, hover events from both surfaces still update `hovered` in state but don't change the visual selection — only `pinned` drives the display. This means the user can click to lock a selection, then continue reading without the selection jumping around.

---

## Highlight states

This is the most important design decision in the component. Three distinct visual states per entity span:

```
State        Background       Text color      Border-bottom
─────────────────────────────────────────────────────────────
default      tinted (0.13α)   entity color    1.5px entity color
dim          transparent      inherit (body)  transparent
lit          tinted (0.13α)   entity color    1.5px entity color
             + brightness(1.15)
```

**When nothing is selected:** all spans are `default`. The document reads naturally with gentle color tints and underlines showing the entity layer.

**When an entity is selected:** the selected entity's spans become `lit`. All other spans become `dim` — background and underline disappear, text reverts to body color. Dimmed text reads as plain text. The selected entity floats on top of readable prose.

**Why dim means invisible-as-entity:** fading to 0.4 opacity makes everything harder to read without making the document scannable. Stripping background + underline entirely on non-selected spans means you're reading normal text with one entity highlighted — not fighting through a fog. The document remains legible at all times.

```
Default (no selection):
  "...shipping [Orbit Dashboard] v2 to [Acme Corp]. This is..."
   ─────────────── subtle tints everywhere ────────────────

Orbit Dashboard selected:
  "...shipping [Orbit Dashboard] v2 to Acme Corp. This is..."
               ─── lit ───         ── plain ──
```

---

## Sidebar row anatomy

```
┌────────────────────────────────────────────────┐
│ 2px left border (entity color, only when active)│
│                                                 │
│  Sarah Chen          [new]  ┌──────┐           │
│  ──────────────── →         │  ·   │ minimap   │
│  truncated name             │    · │           │
│                             │  ·   │           │
│                             └──────┘           │
└────────────────────────────────────────────────┘
```

**Left border:** 2px, entity type color, only visible when row is active. Acts as the selection indicator — mirrors the highlight state in the document.

**Name:** 11px, truncated with ellipsis. Body text color (not entity color) — the group label above provides the type/color signal so the name doesn't need to repeat it.

**New badge:** 8px, success color background. Only shown if `entity.is_new === true`.

**Minimap:** 24×36px track. One 2px tick per mention in this document, positioned vertically at `(mention_index / total_segments) * 32px`. Tick color is the entity type color. Opacity 0.45 at rest, 1.0 when row is active. The minimap communicates mention density and distribution at a glance — an entity with one tick near the bottom is a single late mention; an entity with four ticks spread evenly is woven through the document.

---

## Occurrence minimap — implementation detail

The minimap is not based on character offsets — it's based on segment position. When you have the document as an array of segments (plain text and entity spans), each entity mention's position in that array gives you a 0–1 normalized value:

```typescript
function occPositions(entityId: string, segments: Segment[]): number[] {
  return segments.reduce((acc, seg, i) => {
    if (seg.entityId === entityId) acc.push(i / segments.length);
    return acc;
  }, [] as number[]);
}

// Render as absolutely positioned divs inside a 36px track:
// top = Math.round(position * 32)  // 2px bottom padding
// height = 2px, left/right = 2px padding
```

This is an approximation (segment count ≠ character count) but it's visually accurate enough and requires no character offset data from the API.

---

## Interaction matrix

Every interaction from every surface, and what it updates:

```
Trigger                    hovered   pinned    visual result
──────────────────────────────────────────────────────────────────
mouseenter doc span        set eid   —         eid lit, others dim
mouseleave doc span        null      —         all default (if no pin)
click doc span (unpin)     —         set eid   eid lit, others dim
click doc span (pin same)  —         null      all default
click doc span (pin diff)  —         set eid   new eid lit

mouseenter sb row          set eid   —         eid lit, others dim
mouseleave sb row          null      —         all default (if no pin)
click sb row (unpin)       —         set eid   eid lit, others dim
click sb row (pin same)    —         null      all default
click sb row (pin diff)    —         set eid   new eid lit

mouseenter doc span        set eid   pinned    tooltip shows, no state change
  (while pinned)                               sidebar row for hovered updates
                                               BUT visual selection stays pinned
mouseleave doc span        null      pinned    tooltip hides, selection stays
  (while pinned)
```

**When pinned, hovering doc spans still shows the tooltip and updates sidebar row hover state** — but does not change the lit/dim selection. The pin is sticky.

**When pinned, hovering a different sidebar row** does NOT update the visual selection either — only clicking changes pinned state.

---

## Tooltip

Fixed-positioned, pointer-events none. Appears on `mouseenter` of any doc highlight span (not on sidebar hover — sidebar hover is visible enough without a tooltip).

```
┌─────────────────────────────────────┐
│ Orbit Dashboard                     │  ← entity name, 13px
│ [Product]                           │  ← type badge, entity bg/color
│                                     │
│ In this doc        4 mentions       │  ← 10px tertiary rows
│ Across corpus      9 docs           │
│ Status             new this batch   │  ← only if is_new
│ ─────────────────────────────────── │
│ MENTIONS IN DOC                     │  ← 9px label
│ ┌───────────────────────────────┐   │
│ │ Orbit Dashboard v2 ships to   │   │  ← snippet, 11px
│ │ Acme Corp.                    │   │
│ └───────────────────────────────┘   │
│ ┌───────────────────────────────┐   │
│ │ Orbit Dashboard redesign      │   │
│ │ ships mid-quarter.            │   │
│ └───────────────────────────────┘   │
└─────────────────────────────────────┘
```

Positioning: `clientX + 14`, `clientY - 10`. Flip left if it would overflow the viewport right edge. Max 3 snippets shown. Snippets are the surrounding sentence for each mention — requires chunk text from the API (see data requirements).

---

## Entry and exit

**Entering reader mode:**
- User clicks a doc row in the doc list
- Doc row gets active state (2px left border, info color)
- Right pane transitions from batch mode to reader mode
- No animation needed — instant swap is fine

**Exiting reader mode:**
- "← all entities" button in reader header
- Clicking the active doc row again (toggle)
- Either returns right pane to batch mode
- Resets `hovered`, `pinned`, clears tooltip

**Switching docs while in reader mode:**
- Click a different doc row
- Right pane re-renders with new doc's content
- State resets: `hovered = null`, `pinned = null`

---

## Data requirements

### Available now (existing API)

```
GET /documents/{id}
→ {
    id, title, status, domains, entity_count,
    entities: [{ id, canonical_name, type, source_count, is_new }]
  }

GET /entities/{id}
→ {
    id, canonical_name, type, source_count, is_new,
    sources: [{ document_id, chunk_id, extraction_pass }],
    merge_history: [...]
  }
```

### Required — not yet exposed

**1. Chunk text by chunk_id**

The highlight spans need actual text placement. Two options:

Option A (preferred): `GET /documents/{id}/chunks` returns ordered array of chunks with entity spans:
```json
[
  {
    "chunk_id": "c1",
    "text": "Attendees: Sarah Chen (facilitator), Marcus Webb (infra)...",
    "entities": [
      { "entity_id": "e1", "start": 11, "end": 21 },
      { "entity_id": "e2", "start": 34, "end": 45 }
    ]
  }
]
```

Option B (fallback): `GET /entities/{id}` already returns `sources[].chunk_id`. If chunk text is retrievable by chunk_id, fetch each unique chunk and reconstruct the document client-side by ordering by chunk sequence.

Option A is cleaner. Option B works if adding a new endpoint is out of scope.

**2. `is_new` flag on entities** (already requested in batch extraction spec)

Required for the "new" badge in the sidebar and corpus confidence in the tooltip.

### What works without new endpoints

If chunk text is not available, the reader mode degrades gracefully:

- Highlights still render — but based on entity name string matching in the raw document text (fuzzy, imperfect)
- Tooltip shows entity metadata and source doc list but no snippet text
- Minimap still works using segment position approximation
- The interaction model (hover/pin/sidebar sync) is fully functional

This is a workable v1 if the chunk endpoint takes time. Flag it as a known limitation.

---

## Entity sidebar — groups and ordering

Entities are grouped by type in a fixed order:
`Person → Organization → Product → Technology → Event → Concept → Location`

Within each group, order by mention count in this document (descending) — most-mentioned entities appear first because they're most likely to be the interesting ones.

Group label: 9px, entity type color, uppercase. Does double duty as the color legend — the user learns "teal = Product" by seeing the group label color match the highlight color.

Only show groups that have at least one entity in the current document. If the doc has no Events, no Event group appears.

---

## Document body rendering

The document body is a single `div` containing an interleaved sequence of plain `<span>` elements and highlight `<span>` elements. No block structure beyond `<br>` for newlines.

```html
<div class="doc-body">
  <span>Meeting notes — Q3 planning session</span><br><br>
  <span>Attendees: </span>
  <span class="hl state-default" data-eid="e1"
    style="background:rgba(55,138,221,0.13);color:#378ADD;border-bottom:1.5px solid #378ADD"
    >Sarah Chen</span>
  <span> (facilitator), </span>
  <span class="hl state-default" data-eid="e2" ...>Marcus Webb</span>
  ...
</div>
```

State changes are applied by updating `className` and `style` on existing DOM nodes — no re-render of the full document body. This keeps interaction fast on long documents.

```typescript
function updateHighlightStates(activeId: string | null) {
  document.querySelectorAll('.hl').forEach(el => {
    const eid = el.dataset.eid;
    const state = !activeId ? 'state-default'
                : eid === activeId ? 'state-lit'
                : 'state-dim';
    el.className = `hl ${state}`;
    // update inline styles per state (see highlight states table above)
  });
}
```

---

## Color system

Entity type colors are fixed — not derived from CSS variables — because they need to be consistent between the sidebar, the highlights, the minimap ticks, and the tooltip badge. They should not invert in dark mode.

```
Person:       color #378ADD   bg rgba(55,138,221,0.13)
Organization: color #7F77DD   bg rgba(127,119,221,0.13)
Product:      color #1D9E75   bg rgba(29,158,117,0.13)
Technology:   color #BA7517   bg rgba(186,117,23,0.13)
Event:        color #D85A30   bg rgba(216,90,48,0.13)
Concept:      color #9c9a92   bg rgba(156,154,146,0.13)
Location:     color #5DCAA5   bg rgba(93,202,165,0.13)
```

Background alpha 0.13 is deliberately low — readable against both light and dark backgrounds without obscuring the text. The colored underline (1.5px border-bottom) carries more of the signal than the background fill.

---

## Layout measurements

```
Outer layout (right pane in reader mode):
  grid-template-columns: 172px minmax(0, 1fr)
  gap: 10px

Sidebar:
  width: 172px (fixed by grid)
  position: sticky, top: 0
  group label padding: 5px 10px 2px
  row padding: 5px 10px
  row height: ~32px (natural)
  minimap: 24px × 36px, 2px ticks

Document panel:
  fills remaining width
  body padding: 18px 20px
  font-size: 13px
  line-height: 2.2   ← generous, highlights need vertical breathing room

Tooltip:
  min-width: 190px, max-width: 250px
  offset from cursor: +14px X, -10px Y
  flip threshold: clientX + 250 > window.innerWidth
```

---

## Design philosophy summary

These are the principles behind every decision — useful when making judgment calls during implementation.

**The document is primary.** The text is what the user came to read. Entity highlights are an overlay on that reading experience, not the other way around. When nothing is selected, everything should be readable. When something is selected, everything else should get out of the way.

**Dim means invisible-as-entity, not hard-to-read.** When another entity is selected, dimmed spans should read as plain prose. Background and underline disappear. The text itself stays at full body contrast. This means a user can read a sentence with one entity lit and three dimmed and still understand the full sentence without squinting.

**Bidirectional sync builds trust.** Hovering in either the sidebar or the document updates both surfaces simultaneously. This teaches the user that sidebar and document are the same data viewed two ways. Once they understand that, they'll use whichever surface is more convenient — scan the sidebar to navigate, read the doc to verify.

**The minimap is a confidence signal.** One tick near the bottom of a long document is a warning: this entity appears once, late in the document, and might be noise. Four ticks spread across the document is a confirmation: this entity is central to the document. No numbers or labels needed — the distribution pattern communicates this visually.

**Click to pin, hover to explore.** Hover is cheap and reversible. Click is intentional and sticky. Users who want to casually explore use hover — move across the sidebar and watch the doc respond. Users who want to focus on one entity click to pin it, then can read the full document without managing hover state. Both modes feel natural without any onboarding.
