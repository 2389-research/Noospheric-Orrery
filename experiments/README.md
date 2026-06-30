# Experiments — lab notebook

Lightweight, durable records of experiments run against this codebase: what we
asked, how we ran it, the exact code state, the results, and the conclusion.

## How this is organized (the lab-notebook split)

- **The record lives here, in git.** One dir per experiment, `YYYY-MM-DD-slug/`,
  each with a `README.md` written from the template below. Markdown only — these
  are tiny and belong in version history forever.
- **Bulky, regenerable artifacts live OUTSIDE this repo:** raw outputs, cost
  dumps, per-run goldens/specs, throwaway runner scripts, and any resurrected
  experiment code go in the [`DS-scratch`](https://github.com/2389-research/DS-scratch)
  repo (a flat hodgepodge of experiments). Each record links to its DS-scratch dir.
- **The exact code state is pinned by commit SHA / tag**, not by keeping dead
  experiment code in the tree. Record the SHA; tag it if you'll want to check it
  out later.

Rule of thumb: if it's knowledge, it goes in git here. If it's a regenerable
artifact (or would bloat history), it goes to DS-scratch and is referenced by path.

## Index

| Date | Experiment | Status | Verdict |
|---|---|---|---|
| 2026-06-29 | [Agentic vs decomposed simmer — cost/time/quality](./2026-06-29-agentic-vs-decomposed-simmer/) | Complete, n=1 | Decomposed ~27× cheaper, ~3.8× faster, **comparable-to-better** quality. The agentic flow's cost correlated with overfitting, not quality. |
| 2026-06-26 | [Multi-judge board — gemma4 validation](./2026-06-26-multi-judge-board-validation/) | Directional, n=2/arm | Board produces a richer, better-typed golden (structural taxonomy ASIs) at ~2.3× compute. Ship **opt-in** for taxonomy-sensitive domains; don't flip the default. |

## Record template

```markdown
# <experiment name>
Date · Status (n=, significance) · Author

## Question / hypothesis
## Setup
- Base commit: <SHA>           # shared code state for all arms
- Arms: <how each arm differs, restored-from SHAs>
- Params: domain, N chunks, iterations, models, backend
- Artifacts: DS-scratch/<dir>/  (not in this repo)
## How to run
<exact command(s)>
## Results
<table: cost / time / quality>
## Conclusion + caveats
```
