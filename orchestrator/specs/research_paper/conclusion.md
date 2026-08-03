# Research Paper Spec — Conclusion Section

**Failure mode this guards against:** conclusions mostly restate entities already extracted from
earlier sections in summary form. The risk is duplicate near-identical extraction attempts
(harmless after dedup, but wasted extraction-call effort) and, more importantly, a weak model
inventing a NEW vague self-referential entity ("our approach," "this system") that isn't a real
addition to the graph.

**Extra scrutiny for this section:**

- Apply `shared.md`'s self-reference rule (What NOT to Extract #4) strictly — if the conclusion
  just re-describes the paper's own model/method without introducing a genuinely new named
  entity, extract nothing new from that sentence.
- Future-work mentions of *unbuilt* things ("we leave X to future work") are NOT entities unless
  X is itself a specific named technique/task that already appears elsewhere in the paper.
