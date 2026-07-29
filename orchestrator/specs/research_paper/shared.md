# Noospheric Orrery: Research Paper Extraction Spec (domain: research_paper)

**Purpose:** Domain-specific spec for academic/technical papers (ML, robotics, systems, etc). Runs
**additively** after the general spec (`general_text.md`) — do NOT re-extract `topic`, `concept`,
`technology`, `metric`, `date_ref`, `person`, `organization`. This spec exists only to catch the
paper-specific structure the general pass misses (`model`/`method`/`task`/`apparatus`/`dataset`/
`platform` below).

**`person`/`organization` scoping lives in `general_text.md`, not here.** The general pass and this
domain pass are two independent extraction calls — this file's content is never visible during the
general pass, so `person`/`organization` rules placed here have **no effect** on what gets
extracted. The actual scoping (skip reference-list/citation names; extract only the first-listed
author from a 3+ name byline) is a general-spec rule (`general_text.md`, "What NOT to Extract" #6-7)
because it's a universal need for any multi-author document, not specific to this domain. If
`person`/`organization` output is still too noisy after that rule is in place, the fix belongs in
`general_text.md`, not by adding scoping text to this file.

**Design principle:** A research paper describes a system (`model`), built from techniques
(`method`), evaluated on tasks (`task`) against equipment (`apparatus`), using data (`dataset`) and
hardware (`platform`), reporting results. Only these five are new entity types — results with
numbers already qualify as `metric` under the general spec.

---

## Entity Types (additive — do not re-extract general-spec types)

| Type | What to extract | Examples |
|------|----------------|---------|
| `model` | A named model, architecture, or system introduced or compared against — including reused external backbones, not just the paper's own hero model | "π0", "π0.5", "π*0.6", "OpenVLA", "Octo", "ACT", "Diffusion Policy", "BAGEL" (external backbone reused as a component) |
| `method` | A named technique, algorithm, training procedure, or loss that isn't itself a full model | "flow matching", "RECAP", "AWR", "PPO", "co-training", "offline RL", "context conditioning" |
| `task` | A concrete evaluated task or skill, not a research topic | "laundry folding", "box assembly", "table bussing", "double shot espresso" |
| `apparatus` | The equipment/appliance a robot manipulates or operates on to perform a task — distinct from the robot itself | "espresso machine", "microwave", "dryer", "drawer" |
| `dataset` | Named training/eval data, or a named data-source category | "OXE", "OXE Magic Soup", "Bridge v2", "DROID", "web data", "teleoperated interventions" |
| `platform` | The robot embodiment/hardware performing the task — named rig or configuration, not the equipment it acts on | "UR5e", "Bimanual UR5e", "Franka", "Bimanual Trossen", "ARX", "AgileX", "mobile manipulator" |

### Type Decision Tree

1. **model vs method:** Does it have its own name and produce end-to-end outputs (policies, predictions) that get evaluated as a whole? → `model`. Is it a sub-technique used *inside* training/inference of a model? → `method`. Test: "We propose X, based on Y" → X is `model`, Y is `method` (unless Y is itself an evaluated end-to-end model). Note: a technique still gets its own comparison bar in a results figure (e.g. AWR, PPO) — that alone does not make it a `model`; what matters is whether it IS a distinct trained system or just an extraction/training procedure applied to a shared base model.

2. **task vs topic:** Is it a specific, concretely-evaluated benchmark/skill with a pass/fail or throughput number attached, or could you point to a video of a robot doing exactly this? → `task`. Is it a broad research area you'd read a survey about ("robot learning", "manipulation")? → `topic` (general spec).

3. **dataset vs method:** Is it a named body of data, or a category of data collection (e.g., "human demonstrations", "autonomous rollout data")? → `dataset`. Is it the *procedure* by which that data is used or produced (e.g. "co-training on X")? → `method`.

4. **platform vs apparatus vs product:** Is it the robot/rig performing the manipulation? → `platform`. Is it the equipment/appliance being acted upon (something the robot opens, operates, or manipulates as the task's object)? → `apparatus`. Is it a commercial off-the-shelf tool unrelated to the task's physical setup (e.g. "PyTorch")? → `technology` (general spec). Test: "the robot uses X to do Y" → X is `platform`. "the robot operates/opens/loads X" → X is `apparatus`.

### Custom Type Constraints

Only create a custom `snake_case` type when none of the 6 domain types above and none of the 11
general types fit, AND the entity appears 3+ times.

---

## Extraction Rules

### What to Extract

1. **Named models compared or introduced — but not every eval-condition suffix.** Extract models
   with an actual architectural or training difference ("π0-small" — no VLM init; "π0.5-FAST+Flow"
   — different training objective). Do NOT extract suffixes that just tag which *prompt or inference
   condition* was used on an already-extracted model ("π0-flat", "π0-human", "π0-HL" are all the
   same π0 checkpoint under different command granularity — extract "π0" once, skip the suffixed
   forms). Test: if the difference could be described as "same weights, different input at test
   time," it's a condition, not a model.

2. **Named methods/techniques the paper attributes a specific role to.** Not every verb phrase —
   only techniques that are named (capitalized, acronymed, or given a bolded/italicized term) or
   reused across multiple sentences as a fixed technique.

3. **Tasks with a stated outcome.** If the text reports success/failure, throughput, or a
   qualitative claim about performance on it ("can fold laundry in real homes"), extract the task.
   Generic task mentions without an outcome claim ("performs tasks") are skipped.

4. **Named datasets and data-source categories described as inputs to training.** Both named
   benchmark datasets ("OXE", "DROID", "Bridge v2") and named modality categories ("web data",
   "teleoperated interventions") qualify. Skip vague references ("various data") without a name.

5. **Distinct robot platforms named or described by configuration.** "single-arm robots, dual-arm
   robots, and mobile manipulators" → extract all three separately; likewise extract specific named
   rigs when given ("UR5e", "Bimanual Trossen").

6. **Named apparatus/equipment the robot acts on, when it recurs as a task-defining object.**
   "espresso machine," "microwave," "dryer" — extract when the text treats the object as central to
   a task (not every appliance mentioned in passing).

### What NOT to Extract

1. **Paper section names / venue metadata.** "Abstract", "Related Work", "Appendix B" — never entities.

2. **Vague capability claims without a named task.** "perform practically relevant tasks" — no
   specific task named, skip.

3. **Metrics — leave those to the general spec.** Don't extract "halves the failure rate" here; that's
   a `metric` under `general_text.md`. This spec's job is the *task* the metric is about, not the metric.

4. **Every instance of a model's own self-reference.** If the paper is about π0.5 and says "π0.5
   achieves...", "our model does...", "the system performs..." — extract "π0.5" once (dedup
   handles repetition), not "our model" or "the system" as separate entities.

5. **Structured metadata/schema field names.** Training-time conditioning fields like "overall
   speed," "overall quality," "mistake label," "control mode" are schema attributes, not real-world
   entities — do not extract them even when capitalized in the source. Extract the *value* only if
   it's independently a named concept (e.g. a control mode value that is itself a named method).

6. **Eval-condition suffixes on an already-extracted model.** See "What to Extract" rule 1 — e.g.
   skip "π0-flat"/"π0-human"/"π0-HL" once "π0" itself is extracted.

(`person`/`organization` scoping — references, bylines — is enforced entirely by `general_text.md`;
this domain spec doesn't repeat it since it has no effect on that pass. See the note at the top of
this file.)

---

## Entity Boundary Guidance

- Version-qualified model names are distinct entities: "π0" ≠ "π0.5" ≠ "π0.6" ≠ "π0*0.6" (the
  starred/finetuned variant) ≠ "π0.7". Do not collapse to a single "pi0" entity — the paper series
  is a lineage the graph should be able to distinguish, and downstream normalization (not this
  spec) decides if they should ever be merged.
- "RL with Experience and Corrections via Advantage-conditioned Policies (RECAP)" → extract the
  acronym form "recap" as the canonical name (per general spec's abbreviation-resolution rule),
  not the full expansion.
- Compound task names stay whole: "clean a kitchen or bedroom" → extract as two tasks, "clean a
  kitchen" and "clean a bedroom" (they are evaluated as distinct scenarios), not one merged entity.

---

## Entity Naming Rules

Same as general spec: lowercase, canonical/most-recognizable form, singular, dedup before output.
Greek-letter model names keep their symbol as written in the source text (e.g. "π0.5" not "pi0.5")
unless the source itself only uses the ASCII spelling.

---

## Worked Examples

**Example 1 — abstract-level (`pi0/p0_5.txt`):**

> We describe π0.5, a new model based on π0 that uses co-training on heterogeneous tasks to enable
> broad generalization. π0.5 uses data from multiple robots, high-level semantic prediction, web
> data, and other sources... Our system uses a combination of co-training and hybrid multi-modal
> examples that combine image observations, language commands, object detections, semantic subtask
> prediction, and low-level actions... we demonstrate for the first time that an end-to-end
> learning-enabled robotic system can perform long-horizon and dexterous manipulation skills, such
> as cleaning a kitchen or bedroom, in entirely new homes.

```json
{
  "entities": [
    {"name": "π0.5", "type": "model"},
    {"name": "π0", "type": "model"},
    {"name": "co-training", "type": "method"},
    {"name": "web data", "type": "dataset"},
    {"name": "semantic subtask prediction", "type": "method"},
    {"name": "clean a kitchen", "type": "task"},
    {"name": "clean a bedroom", "type": "task"}
  ]
}
```

NOT extracted: "multiple robots" (no specific platform named), "our system" (self-reference to
π0.5, already captured), "long-horizon and dexterous manipulation skills" (capability claim, no
single named task — the concrete tasks named right after it ARE extracted).

**Example 2 — full-text density (`pi0/p0_6.txt`, VI-B Comparisons and Ablations):**

> We compare Recap to several baselines: Pre-trained π0.5. Pre-trained π0.6. RL pre-trained π*0.6.
> π*0.6 offline RL + SFT. π*0.6 (ours)... AWR. Starting from the same pre-trained model π0.6... PPO.
> We implement a variant of DPPO/FPO... Our policies make coffee with a commercial espresso machine,
> assemble boxes, and fold laundry on the robotic platform shown in Figure 5.

```json
{
  "entities": [
    {"name": "π0.5", "type": "model"},
    {"name": "π0.6", "type": "model"},
    {"name": "π*0.6", "type": "model"},
    {"name": "recap", "type": "method"},
    {"name": "awr", "type": "method"},
    {"name": "ppo", "type": "method"},
    {"name": "dppo", "type": "method"},
    {"name": "double shot espresso", "type": "task"},
    {"name": "box assembly", "type": "task"},
    {"name": "espresso machine", "type": "apparatus"}
  ]
}
```

NOT extracted: "π*0.6 offline RL + SFT" and "π*0.6 (ours)" (eval/training-stage conditions of the
already-extracted "π*0.6," not distinct models — rule "What to Extract" #1); "SFT" alone (not
independently named as a technique here, just a label for a training stage already covered by the
condition it tags); the robotic platform itself is not named in this excerpt, so nothing is
extracted as `platform` — don't invent a generic "robotic platform" entity.

**Example 3 — byline vs. reference list (`pi0/p0.txt`):**

> Kevin Black, Noah Brown, Danny Driess, ... Physical Intelligence, San Francisco, California, USA.
> ...
> References
> Achiam et al. [2023] Josh Achiam, Steven Adler, ... Gpt-4 technical report. arXiv:2303.08774, 2023.
> Ahn et al. [2022] Michael Ahn, Anthony Brohan, Noah Brown, ... Do as i can, not as i say...

Extract (via `general_text.md`'s rules, not this file): `{"name": "kevin black", "type": "person"}` (first-listed author only — this byline has 20+ names) and `{"name": "physical intelligence", "type": "organization"}`.

NOT extracted: "Noah Brown," "Danny Driess," and every other co-author in the byline (not first-listed); "Josh Achiam," "Steven Adler," "Michael Ahn," "Anthony Brohan" and every other reference-list name — even "Noah Brown" recurring there doesn't change anything, since reference-list occurrence never qualifies regardless of whether the name also appears in the byline.

---

## Output Schema

```json
{
  "entities": [
    {"name": "entity name lowercase", "type": "model | method | task | apparatus | dataset | platform"}
  ]
}
```

No relationships, no properties. Lineage between models (e.g. "π0.5 is based on π0") is left to the
pipeline's co-occurrence computation over shared chunks — not extracted explicitly here.

---

## Execution Notes

- This spec is **additive**: it must run alongside the general spec, not replace it, per the
  domain-cascade design in `ingest.py`. Storing it stand-alone with `domain_path` set (not
  `domain_path IS NULL`) preserves that.
- Err toward precision over recall on `model` and `task` — these are the entities the graph view
  will most rely on to show paper lineage, so a false positive here is worse than a missed generic
  mention.
