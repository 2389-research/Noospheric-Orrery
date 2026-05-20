# Noospheric Orrery — Onboarding UX Spec v2
## Exploration-First Design

---

## The Core Principle: Aha Moment First

Every great onboarding in games and SaaS shares one pattern: **show the payoff before teaching the mechanics.**

- Figma drops you into a pre-made design file immediately — you're in the tool, not reading about it
- Genshin Impact shows you flying, combat, and a gorgeous open world before explaining stamina systems
- MTG Arena plays a full game against Sparky before explaining card types
- The original Orrery spec had it backwards: Upload → Pipeline → Entities → Orrery

The Orrery is the most visually striking thing in the product. It's the galaxy viz. It immediately communicates "this is different." **Lead with it.**

The revised structure: **Orrery → Search → Entities → Pipeline → "Now build your own"**

---

## The Magos Noosphere

### Concept

The mascot character is a Magos — a robed, blue-eyed robot scholar. Canonically, a Magos studies, classifies, and maps knowledge. Their Noosphere is a living demonstration of a fully developed knowledge graph.

**The Magos Noosphere is a shared, curated, read-only workspace that every new user enters first.** It has rich content, a beautiful populated Orrery, and serves as both the tutorial environment and a permanent demo. Users cannot add to it or modify it — they can only explore.

At the end of onboarding, the "unlock" moment is: **"Now create your own."**

This is the MTG Arena pattern — Sparky is always available, Color Challenges teach progressively, and then you graduate to your own decks.

### The Magos Noosphere Content

The content should be thematically resonant and dense enough to produce a beautiful Orrery. Given the mascot's aesthetic (Adeptus Mechanicus vibes — red robes, mechanical arms, devotion to knowledge and the machine), the canonical Magos Noosphere covers:

**Option A — "The History of Intelligence"**
Documents covering: Alan Turing and computability, Claude Shannon and information theory, Norbert Wiener and cybernetics, the noosphere concept (Teilhard de Chardin, Vernadsky), early AI history, von Neumann architecture, emergence and complexity.

*Why:* Directly on-brand. Produces rich entities (people, concepts, institutions, dates). Multiple distinct domains naturally emerge (Mathematics, Philosophy of Mind, Computer Science, Earth Systems). The orrery looks like a history of thought.

**Option B — The Magos's Own Research Log**
Written in-character as field notes and research logs from the Magos — covering knowledge about knowledge. Self-referential, charming, fits the aesthetic perfectly. Same factual content as Option A but framed as the mascot's own collected writings.

*Why:* More personality. Explains why the Magos is here. Makes the character feel like an actual inhabitant of this noosphere, not a tutorial overlay.

**Recommendation: Option B.** The in-character framing gives the tutorial genuine narrative pull. The Magos is showing you *their* knowledge graph, not a demo. This is the difference between a museum exhibit and being shown around someone's actual lab.

### Magos Noosphere Specs

- **~15-20 documents**, each 400-800 words
- **6-8 domains** naturally produced by classification
- **~150-300 entities** after simmering against a bespoke spec
- **Orrery:** 6-8 visible nebulae, 150+ stars, rich trade routes between domains
- Pre-simmered with a bespoke extraction spec — not the general spec
- Pre-positioned in UMAP space with the universal model
- Content curated so specific "show-stopping" entities appear by name during the tutorial
- **Read-only for all users.** Enforced at the security rules level. The workspace has no editors — the Magos team maintains it via admin tooling.

### Technical Implementation

The Magos Noosphere is a regular Firestore workspace with a hardcoded workspace ID known to the frontend (`MAGOS_WORKSPACE_ID` env var). The frontend loads it directly for all new users before they have their own workspace. Security rules: all authenticated users have viewer access to this specific workspace ID.

```
workspaces/
  MAGOS_WORKSPACE_ID/         ← hardcoded, maintained by the team
    orgId: "magos-org"
    name: "Magos Noo's Noosphere"
    isDemo: true              ← flag to disable write UI globally
```

The Orrery iframe receives this workspace ID. No pipeline controls, upload buttons, or normalization UI appear when `isDemo: true`. The nav hides the Upload and Pipeline tabs. Search works fully. Entity drilling works fully.

---

## The Three User Flows

### Flow A: New User, No Invite

```
Sign in with Google
  → POST /auth/accept-invite  (no invite)
  → POST /auth/provision      (org + workspace created in background)
  → MAGOS NOOSPHERE EXPERIENCE  (immediately, skipping own workspace)
  → TUTORIAL (exploration-first, 5 steps)
  → NAMING MOMENT  (at the end, not the beginning)
  → Land in own workspace
```

Key difference from v1: **provision happens in the background, naming happens at the END.** The user earns the naming moment by exploring first.

### Flow B: Invited User

```
Sign in with Google
  → POST /auth/accept-invite  (has invite → joined org, claims set)
  → "You've joined [Org Name]" confirmation screen (10 seconds)
  → MAGOS NOOSPHERE EXPERIENCE  (same tutorial, different context note)
  → Land in invited org's workspace (skip naming)
```

### Flow C: Returning User

```
Sign in with Google
  → POST /auth/provision  (no-op, returns existing)
  → Land in lastWorkspaceId from localStorage
  → Normal app
```

The Magos Noosphere persists as an option in the Noosphere switcher for all users forever, labeled "✦ Magos Noo's Noosphere" with a special icon. It's always available as a reference/sandbox.

---

## The Tutorial: 5 Steps, Exploration-First

The tutorial runs entirely inside the Magos Noosphere. No scrim or spotlight until Step 4. For the first three steps, the mascot panel is a floating overlay in the bottom-left — the user can freely explore the screen.

The mascot communicates via a speech bubble panel. Tone: dry wit, scholarly, slightly mysterious. Not cheerful startup energy — this is an entity who has spent a long time collecting knowledge and finds it genuinely delightful that you're here.

---

### Step 1 — The Orrery (The Wow)

*User lands directly on the Orrery tab of the Magos Noosphere. The galaxy viz fills the screen. The mascot panel appears after a 2-second delay.*

**Mascot pose:** Holding the galaxy orrery device. This is their moment.

**No scrim. No spotlight. Full Orrery visible and interactive.**

```
┌──────────────────────────────┐
│  [MASCOT: galaxy pose]       │
│                              │
│  "My Noosphere."             │
│                              │
│  "Fifteen years of          │
│  accumulated reading.        │
│  Finally organized."         │
│                              │
│  "Each nebula is a domain   │
│  of knowledge. Each star     │
│  is an entity I've          │
│  encountered."               │
│                              │
│  "Explore if you like."      │
│                              │
│  [  I'm ready  ]            │
│                              │
│                     1 of 5  │
└──────────────────────────────┘
```

The user can interact with the Orrery freely here — click nebulae, hover stars, explore. The "I'm ready" button just advances to Step 2. There's no time pressure. Let them look.

**What they're experiencing:** The orrery is alive. Stars glow. Nebulae pulse. Trade routes arc between domains. Clicking a star shows an entity. This is the product at its best, immediately.

---

### Step 2 — Search (The Power Move)

*Spotlight: the search bar at the top of the interface*

**Mascot pose:** Pointing (finger extended toward the search bar)

```
"The Orrery responds to queries."

"Try searching for something.
Turing. Information. Consciousness.
See what lights up."

[ Try a search ]  ← button that populates the search bar
                    with "Alan Turing" and fires it
```

When the search fires, the Orrery responds — relevant entities glow, trade routes illuminate, the semantic search highlights the knowledge structure in real time. The user sees the search-to-visualization connection.

If the user types their own search instead of clicking the button, that's better — let them. The mascot responds:

```
[After any search completes]

"There. The graph knows what
you were looking for."

"Every result traces back to
where that knowledge lives."

[  Continue  ]
```

---

### Step 3 — Entities (The Detail Layer)

*Spotlight: entity list panel / an entity card*

**Mascot pose:** Reading scroll

The search results are showing. Spotlight one entity — ideally one of the pre-known "good" entities like "Claude Shannon" or "Noosphere."

```
"This is an entity."

"My system extracted it from
the source documents.
It knows where Claude Shannon
appears, what he co-occurs with,
which documents mention him."

"Click it."
```

User clicks the entity. The entity detail panel opens showing source chunks, co-occurring entities, document sources.

```
"Source material. Every entity
traces to the text it came from."

"This is what a knowledge graph
actually is — not a tag,
not a category. A node in a
network of meaning."

[  Continue  ]
```

---

### Step 4 — Pipeline (The Engine Behind It)

*Navigate to Pipeline tab. Spotlight: the completed job list.*

**Mascot pose:** Thinking (equations thought bubble)

This is the first time we show backend infrastructure. The user now cares because they've seen what it produces.

```
"This is what built what you
just explored."

"Every document I added was
classified, extracted, and
refined. The jobs are here."

"Notice the Simmer jobs —
those ran for thirty minutes each,
iteratively improving the
extraction spec until it
understood my corpus."

"You won't need to think about
this much. It runs itself."

[  Continue  ]
```

Keep this step SHORT. The user doesn't need to understand the pipeline deeply right now. They need to know it exists and is automatic. One screen, one idea: "this is the engine, it's smart, it runs itself."

---

### Step 5 — The Unlock

*Full-screen moment. Scrim drops. Mascot takes center stage.*

**Mascot pose:** Explaining (arm outstretched, presenting) — largest size in the tutorial

```
[Full screen, dark background, star field]

[MASCOT: large, centered]

"Now you've seen what a Noosphere
can become."

"Mine took fifteen years of
reading and thirty minutes of
simmering to build."

"Yours starts now."


        [ Name Your Noosphere ]


    (You can always return here.)
```

The "Name Your Noosphere" button transitions to the naming screen.

---

### Naming Screen (Earned, Not Gatekeeping)

Same design as v1 but the framing is completely different. This is a reward, not a form.

```
[MASCOT: explaining pose, smaller than Step 5]

"What are you going to
map into existence?"

┌─────────────────────────────────┐
│  Michael's Noosphere           │
└─────────────────────────────────┘

[ Begin  ]
```

Pre-fill as before (`{First Name}'s Noosphere`). Fully editable. One word of context from the mascot, one input, one button. The question "what are you going to map?" is doing work — it frames the noosphere as a creative act, not a setup step.

On confirm: create the workspace (already provisioned in background), switch to it, show the empty Orrery with a small mascot corner panel:

```
[MASCOT: small, bottom-left, holding galaxy device — dimmed]

"Upload something you want
to understand better."

[  Upload a document  ]
```

---

## Empty State Designs

### Empty Orrery (New User Workspace)

The canvas shows only a faint star field. The mascot is centered, dimmed, galaxy device in hand but not glowing.

```
[MASCOT: holding galaxy orrery, subdued]

"The Orrery is waiting."

"Upload documents to begin.
The more you add, the richer
this becomes."

[  Upload your first document  ]
```

### After First Document Ingested (Partial State)

One domain, a handful of entities. The mascot reacts:

```
[MASCOT: excited — pointing pose]

"There."

"[Document title] has been
classified and extracted.
[N] entities found across
[M] domains."

"Keep going."
```

Small corner panel only — don't interrupt the user from exploring what just appeared.

### Empty Pipeline

```
[MASCOT: thinking pose]

"Nothing running yet."
"Jobs appear after ingestion."
```

### Empty Entities

```
[MASCOT: reading scroll]

"No entities extracted yet."
"They appear after your first
document is processed."
```

---

## Magos Noosphere in the Switcher

The Magos Noosphere always appears in the Noosphere switcher for all users, with a special visual treatment:

```
[ Noosphere: "Michael's Research" ▾ ]

  ✦ Magos Noo's Noosphere          (demo)
  ─────────────────────────────────
  Michael's Research          ✓
  Client Notes
  ─────────────────────────────────
  + New Noosphere
```

The `✦` marker and `(demo)` label distinguish it. Clicking it takes any user back to the Magos Noosphere at any time — no tutorial overlay, just the live product. It's a permanent reference and sandbox.

**When a user visits the Magos Noosphere outside of tutorial:**
- No mascot overlay
- The tab bar shows Orrery and Entities but not Upload or Pipeline
- A small badge in the corner: "This is a shared, read-only Noosphere · Your data is in your own workspaces"

---

## Invited User Variant

Invited users skip the naming step but get the full Magos tutorial. The mascot's opening line changes:

*Step 1 opener for invited users:*
```
"You've been invited to [Org Name]."

"Before you dive in, let me show
you what this is and how it works."

"This is my Noosphere. Yours
is [Org Name]'s."

[  Show me  ]
```

After Step 5, instead of naming, they land directly in the org's workspace.

---

## Progressive Tutorial (Post-Onboarding)

Following the MTG Arena Color Challenges model — deeper features unlock progressively after the initial tutorial, triggered contextually.

| Trigger | Mini-tutorial |
|---|---|
| First simmer job completes | Mascot appears: "The spec has been refined. Your extraction quality just improved." |
| 10+ entities in workspace | Mascot: "Enough entities for normalization. Want me to find duplicates?" |
| First search with results | "Notice how the Orrery responded. The graph understands your query." |
| User visits Entities tab for first time | Brief tooltip on the filter/type controls |
| Empty normalization queue | Mascot: "All entities verified. The graph is clean." |

These are corner-panel appearances only — never full overlays after the initial tutorial. The mascot becomes a contextual assistant, not a constant presence.

---

## Component Updates

### New Components

| Component | Notes |
|---|---|
| `<MagosNoosphere />` | Wrapper that sets workspace to MAGOS_WORKSPACE_ID, hides write UI |
| `<TutorialOverlay />` | Step manager — tracks step, renders mascot panel, handles advancement |
| `<MascotPanel />` | The floating panel — takes pose, lines[], onNext, step, total |
| `<NamingScreen />` | Post-tutorial naming moment |
| `<ProgressiveTip />` | Small corner mascot appearances post-onboarding |

### Modified Components

- `layout.tsx` — detect `isDemo` workspace, hide Upload/Pipeline tabs
- `<NoosphereSwitcher />` — special entry for Magos Noosphere with `✦` marker
- `auth-context.tsx` — track `tutorialComplete` in localStorage, control routing

---

## Tutorial State

```javascript
// localStorage
{
  tutorialComplete: boolean,
  tutorialStep: number,       // 1-5, for resuming
  seenMagosNoosphere: boolean,
  lastWorkspaceId: string,
}
```

If user closes browser mid-tutorial (steps 1-4), resume from current step on next visit. If they close on Step 5 (naming screen), treat as complete — they've seen everything, the naming step is optional.

"Skip tutorial" is available throughout Steps 1-4. Skipping immediately routes to the naming screen (they still need a workspace). The Magos Noosphere remains accessible in the switcher.

---

## Design Notes for the Mascot Dialogue

The mascot's voice is:
- **Dry, not cheerful.** "There." not "Amazing! You did it!"
- **Scholarly, not instructional.** Shares observations, doesn't give directives
- **Slightly proud.** This is their knowledge graph. They care about it.
- **Economical.** Short lines. No paragraph walls.
- **Occasionally wry.** "Fifteen years. Thirty minutes. You'll do better."

The mascot doesn't explain features. The mascot narrates the experience. There's a difference. "Click the search bar to search" is a feature explanation. "The Orrery responds to queries" followed by showing a search is narration.

---

## The "Hello Noosphere" Document

The original spec suggested a single pre-loaded tutorial doc. In this design, the Magos Noosphere replaces that need — users explore real content from the start.

For the user's own first upload, there's no scaffolded document. The empty state CTA ("Upload something you want to understand better") is intentional — it invites them to bring something real. Their first noosphere starts with their actual content, not a tutorial doc.

If we want to offer a "try it without uploading first" path, the answer is: **go back to the Magos Noosphere.** That IS the sandbox. It lives in the switcher permanently.

---

## Why This Is Better Than v1

| v1 (Pipeline-First) | v2 (Orrery-First) |
|---|---|
| User sees upload form first | User sees the galaxy immediately |
| Naming happens before engagement | Naming is earned after exploration |
| Mascot explains features | Mascot narrates an experience |
| Tutorial doc as scaffold | Real curated noosphere as sandbox |
| "Here's how to use the tool" | "Here's what this becomes — now build yours" |
| Teaches mechanics before showing payoff | Shows payoff, then reveals mechanics |

The fundamental shift: v1 is a product tour. v2 is a story with a reveal.
