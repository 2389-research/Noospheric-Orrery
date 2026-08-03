# Research Paper Spec — Related Work Section

**Failure mode this guards against:** This section is citation-dense. A weaker extraction model
tends to over-extract every cited paper's model/method name as if it were being actively
compared, when most citations here are just background scaffolding.

**Extra scrutiny for this section:**

- Apply `shared.md`'s citation-skip rule (What NOT to Extract, citation-adjacent names) to model
  and method names too, not just `person`/`organization`: if a model or method name appears only
  as "X [12] does Y" or "X (Smith et al., 2023)" with no further discussion beyond that one
  citation sentence, skip it — it's a citation, not a comparison baseline.
- DO extract a cited model/method if the paper discusses it across 2+ sentences (e.g. contrasts
  its approach against the current paper's approach) — that crosses from "citation" to "prior
  work being meaningfully discussed," which is real content for the graph.
