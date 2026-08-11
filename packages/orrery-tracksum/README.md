# orrery-tracksum

Summarize `tracker` agent code-gen **runs** into neutral, multi-granularity documents —
the featurizer for tracker-run ingestion, and the sibling of
[`orrery-codesum`](../orrery-codesum) (which does the same job for git repos).

A run is ingested *as a repo*: everything downstream of these summaries (entity
extraction, co-occurrence, normalization, the graph snapshot, the viz constellation) is
the shared path. This package produces only the documents.

## What it emits

Four altitudes per run, so a consumer picks its own and drills as needed:

| Piece | Level | Model call? |
|---|---|---|
| `rollup` — one-line run overview | repo | no — composed from facts |
| `spec` — the problem statement, verbatim + fingerprint | file | no |
| `dip` — design patterns recognized against the catalog | file | yes |
| `nodes[]` — one summary per node that ran | file | yes, one each |

Plus `coherency`, a self-check over the batch, and per-node `grounding`.

## Two design decisions worth knowing before you change anything

**1. The dip prompt carries a closed catalog.** A small model does not reliably *invent*
good design-pattern names, but it does reliably *recognize* against a fixed list. So
`catalog.py` ships the vocabulary and the prompt says to match strictly against it and to
report notable **absence** ("no repair tier") as informative. Do not retype a condensed
copy into a caller — that was tried, the condensed version dropped the "strongest
discriminators" paragraph, and the model began reporting `model-tiering` as ABSENT on
dips that used it. Import `DIP_CATALOG`.

**2. Summaries are node-local and neutral.** A node summary sees one node's own trace and
is told not to judge overall run success or reference other nodes. This is not modesty:
a tracker run does not know whether it succeeded — that is observed externally, from a
user moving on or not — so inviting a verdict would manufacture a judgement the corpus
does not contain. Evaluating a run or a trajectory is a *downstream* job for an agent
reading the graph, and summaries pre-shaped toward "what went wrong" would contaminate
it. Nothing here asks that question.

## The trace-reader seam

`tracker`'s `activity.jsonl` format and its distiller belong to tracker and will drift on
their own schedule, so this package does **not** parse raw traces. It declares the narrow
shape it needs and takes an implementation — the same way it takes an already-constructed
relay instead of importing an SDK:

```python
find_runs(root)    -> [run_dir, ...]
load_run(run_dir)  -> RunTrace(run_id, nodes=[NodeTrace(id, text, kind, model, outcome)], ...)
```

`distill_reader(distill)` adapts tracker's own module, confining its wider surface to one
adapter that a schema change breaks in exactly one place. Tests use a hand-built fake, so
they need neither tracker nor a model.

## Usage

```python
from orrery_relay import Relay
from orrery_tracksum import distill_reader, make_summarize_fn, summarize_runs, build_index

relay = Relay.from_settings(settings)
bundles = summarize_runs(
    corpus_dir,
    make_summarize_fn(relay, settings.extraction_model),
    distill_reader(distill),
)
index = build_index(bundles)
```

That is what `worker/src/jobs/ingest_tracker_runs.py` does, mirroring how `ingest_repo`
calls `summarize_repo`.

## The eyeball loop

Kept as a first-class entry point on purpose: the catalog and the node prompt were tuned
by running one artifact, reading the output, and adjusting. That loop is how the
compressed-catalog regression was caught. A prompt asset with no fast manual loop rots.

```bash
# one artifact at a time — prints the summary (+ grounding check for a node)
python -m orrery_tracksum.cli dip  path/to/workflow.dip
python -m orrery_tracksum.cli node path/to/node_trace.txt

# a whole corpus -> per-run JSONs + index.json (the ingest bundle)
python -m orrery_tracksum.cli runs <corpus_dir> --out out/ --distill-path <dir-with-distill.py>
```

Defaults to the `ollama` backend and `gemma4:26b` — this is a local-first pipeline, and
`EXTRACTION_MODEL` / `ANTHROPIC_BACKEND` override it. Deterministic (temperature 0), so
re-running a corpus reproduces its summaries.

`num_ctx` is raised to 8192 via the relay's `ollama_options`. Without it Ollama silently
truncates long prompts from the left and the model summarizes a decapitated node trace
with no error anywhere.

## Tests

```bash
cd packages/orrery-tracksum && PYTHONPATH=src python -m pytest tests/ -q
```

No model, no network, no tracker install.
