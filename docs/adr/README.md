# Architecture Decision Records

Short documents capturing a single architectural decision: its context, the
decision, and its consequences ([Nygard format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)).

How ADRs relate to the rest of the repo:
- **`experiments/`** holds *evidence* (dated, append-only results).
- **`docs/superpowers/{specs,plans}`** holds *design + implementation plans* (forward-looking).
- **`docs/adr/`** holds *decisions* — an ADR's Context **cites the experiments** that
  justified it. Once accepted, an ADR is immutable: supersede it, never rewrite it.

## Index

| # | Decision | Status |
|---|---|---|
| [0001](./0001-decomposed-simmer-over-agentic-refine.md) | Use the decomposed simmer loop, not agentic `refine()` | Accepted |
