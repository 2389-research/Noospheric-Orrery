# Research Paper Spec — Method Section

**Failure mode this guards against:** This is the densest section for the `model` vs `method`
boundary (see `shared.md`'s Type Decision Tree #1) — training procedures, losses, and
architectural components are introduced together, and a weaker model tends to promote
sub-techniques to `model` status just because they're capitalized/acronymed.

**Extra scrutiny for this section:**

- Before extracting anything as `model`, check: does the paper evaluate THIS THING END-TO-END
  with its own results, or is it a component/procedure used to train or run the paper's actual
  model? If the latter, it's `method`, full stop — re-apply the Type Decision Tree #1 test
  explicitly per entity in this section, don't extract-then-sort.
- Named datasets introduced as training inputs belong here too (`dataset` type) — this section
  is where data composition is usually described in detail.
