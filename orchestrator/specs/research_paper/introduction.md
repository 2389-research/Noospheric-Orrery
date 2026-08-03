# Research Paper Spec — Introduction Section

**Failure mode this guards against:** Introductions restate the hero model/task in loose,
promotional prose before the paper's precise terminology is established. A weaker extraction
model tends to over-extract vague capability claims as `task` entities here.

**Extra scrutiny for this section:**

- Apply "What NOT to Extract" #2 from `shared.md` (vague capability claims) more strictly than
  elsewhere: if a capability is described in general terms ("perform long-horizon tasks in new
  environments") without a *specific, nameable* task alongside it in the same sentence or the
  next, skip it — even if it sounds important. Wait for the Experiments section, where the same
  capability will be restated as a concrete evaluated task.
- The paper's own hero model IS worth extracting here (it's usually named for the first time in
  the introduction) — do not suppress `model` extraction, only `task` extraction, per the rule
  above.
- Named baseline/prior-work models mentioned in passing ("unlike prior methods such as X") ARE
  still real `model` entities if named — this section's caution is about vague tasks, not about
  under-extracting models.
