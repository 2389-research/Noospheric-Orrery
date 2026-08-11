# A noosphere, and how to open one

You have an exported knowledge graph. This file is written to be read by a person **or
handed to a coding agent** — everything needed is here, including the three things that
go wrong.

## What's in the box

| file | what it is |
|---|---|
| `orrery.db` | the entire graph — documents, entities, edges, embeddings |
| `manifest.json` | counts, the commit it came from, and the `source_path` prefixes |
| `import_noosphere.py` | installs it into a checkout |
| `NOOSPHERE.md` | this file |

A noosphere is only ever two things: **that SQLite file** and **one row in
`data/workspaces/registry.json`**. There is no other state. Document text lives in the
database, so none of the uploaded originals are needed.

## Install

```bash
git clone https://github.com/2389-research/Noospheric-Orrery.git
cd Noospheric-Orrery
git checkout <exported_from_commit>       # from manifest.json, or anything NEWER

cp .env.example .env                      # add LLM credentials, or use Ollama (below)
docker-compose build                      # first build takes a while

# services DOWN for this step — see "Order matters" below
python3 /path/to/archive/import_noosphere.py --data ./data

docker-compose up -d
```

Then open `http://localhost:3100`, pick the workspace from the selector, and go to
**Orrery**.

## The three things that go wrong

**1. Order matters: code first, services down, then the file.**
The orchestrator's background snapshot loop opens *every* registered workspace within
~20 seconds. If it reaches this database while your checkout is on older code, it creates
empty collection tables beside the populated legacy ones — and the migration then
correctly **refuses** the database, because both names exist and no safe automatic merge
is possible. `import_noosphere.py` checks for a running orchestrator and stops, which is
why you should use it rather than `cp`.

**2. The first `/graph` is a build, not a hang.**
The graph payload is materialised once and cached. On a large corpus the first request can
take **several minutes** (measured: ~8.5 min for 96k entities / 917k relationships);
every later request is seconds. If the galaxy seems stuck on first load, it is building.

**3. `source_path` will not resolve here.**
Those are absolute paths from the machine that ingested the corpus (`/data/...` inside its
container). The graph itself is entirely unaffected — domains, entities, edges, and search
all work. The only thing that breaks is drilling from a node to the *real source file*. If
you want that, stage the same directories under your `./data/` using the prefixes listed
in `manifest.json`.

## Version compatibility, in one rule

**Any noosphere opens on newer code. Never on older.**

Migrations are forward-only and shape-detecting — `init_db` asks "does this column
exist?" rather than reading a version number — so a corpus from any earlier build adapts
on first open. There is no downgrade path. `manifest.json` records the commit it was
exported from: use that or later.

Extra columns are harmless; missing ones are fatal. That asymmetry is the whole reason the
rule points one way.

## Running fully locally (no cloud credentials)

The graph is already built, so nothing here needs a model unless you ingest more. To
browse it you need no credentials at all. If you do want to ingest:

```bash
ollama pull gemma4:26b && ollama pull gemma4:e4b
# in .env:
ANTHROPIC_BACKEND=ollama
OLLAMA_URL=http://host.docker.internal:11434
CLASSIFICATION_MODEL=gemma4:26b
EXTRACTION_MODEL=gemma4:e4b
```

## Verifying the import

```bash
sqlite3 data/workspaces/<id>/orrery.db \
  "SELECT (SELECT COUNT(*) FROM documents), (SELECT COUNT(*) FROM entities),
          (SELECT COUNT(*) FROM collections);"
```

Compare against `manifest.json`. If `collections` is **0** but the archive listed some,
the migration did not run — you are on code older than the export. Check out the commit
from the manifest and restart; the migration is idempotent, so re-opening is safe.

## What was deliberately left out

- **`layout_model`** — a pickled UMAP reducer. Not on the read path (positions live in
  `domain_layout`), and it only unpickles under compatible library versions, so it is
  dropped and re-fitted rather than shipped as a landmine.
- **`graph_snapshot` payload** — a cache keyed to one contract version. Emptied and marked
  dirty so your build produces its own instead of serving a stale one.
- **Uploaded originals** — the text is in the database.
