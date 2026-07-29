# Research Paper Spec — Abstract Section

**Failure mode this guards against:** abstracts are extremely dense summaries — nearly every
noun phrase is a candidate entity, and a weak model can over-extract by treating the abstract
like normal prose instead of a compressed index of what the rest of the paper will elaborate.

**Extra scrutiny for this section:**

- Extract the paper's hero `model` and its 1-2 headline named `task`s/`method`s from the
  abstract — these are almost always genuinely introduced here.
- Do NOT extract every quantitative claim as a full `metric` string from the abstract alone if
  the same number reappears with more precision in Experiments — prefer the more precise later
  occurrence; a rough abstract-level restatement ("nearly halves the failure rate") is fine to
  extract once, just don't treat every subsequent partial restatement across sections as a new
  metric.
