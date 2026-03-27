# Tutorial RAG Pipeline

A standalone FastAPI service that answers hobby questions by retrieving from enriched tutorial transcripts and synthesizing structured responses with citations.

## Pipeline

```
User: "how do I paint NMM gold?"
    │
    ▼
1. EXPAND (gpt-5.4-mini, ~1s)
   → 5-7 sub-queries covering abbreviations, paint names,
     theory concepts, color terms, generalized query
    │
    ▼
2. RETRIEVE (SearchEngine × 5-7 in parallel, ~0.3s)
   → Top 25 chunks by score from hybrid search
    │
    ▼
3. SYNTHESIZE (gpt-5.4-mini, markdown output, ~3-5s)
   → Structured tutorial in markdown
    │
    ▼
4. JUDGE (gpt-5.4-mini, two-step)
   → Step 1: Extract best evidence from chunks
   → Step 2: Evaluate answer against extracted evidence
    │
    ▼
5. VERIFY-FIX (up to 2 iterations)
   → Verifier checks if ASI was applied
   → Synthesizer fixes gaps
    │
    ▼
6. REFINE (gpt-5.4-mini, if judge score < 7)
   → Re-synthesize with judge's ASI + evidence
```

Total: ~10-30s per query, ~$0.006/query.

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service status + index count |
| `/query` | POST | Full RAG pipeline. Input: `{"question": "..."}`. Returns: `{content, graph, timing, ...}` |
| `/search` | GET | Entity/chunk lookup. Params: `q`, `types`, `limit`. Returns: entities + chunks + videos |

The `/query` response includes a `graph` field with the subgraph used to build the answer — nodes (entities + videos) and edges — for rendering in the Learn tab.

## Key Design Decisions

- **All gpt-5.4-mini.** Nano was tested for expansion/judge but too unreliable. Mini is consistent and cheap enough.
- **No LLM reranker.** Was non-deterministic and dropped good chunks. Score-based ranking from embedding search is deterministic.
- **No title search.** Was matching irrelevant videos ("Golden Demon" for "gold" queries). Judge can request more context if needed.
- **Markdown output, not JSON.** Models write better natural text than structured JSON fields. Frontend renders with react-markdown.
- **Query expansion is mandatory.** Single queries fail on domain abbreviations. "Painting NMM steel" → 0 results without expansion, 4 perfect chunks with expansion.
- **Answer only what was asked.** If user asks about technique A, don't include technique B even as an alternative.

## Synthesis Prompt Design

The synthesis prompt enforces:
- Only write about the technique asked about
- Use exact product names from transcripts (not paraphrased)
- Short focused answer over long padded one
- Under 2000 characters
- No hedging or meta-commentary

The judge extracts evidence in a separate step, then evaluates whether the answer used it. The verify-fix loop catches cases where the refiner acknowledged feedback but paraphrased instead of using specifics.

## Debugging

`debug_pipeline.py` runs each step independently and saves all intermediate results:

```bash
QUESTION="how do I paint NMM gold" python3 debug_pipeline.py
# Outputs to debug_runs/{timestamp}_{slug}/
#   01_expansion.json
#   02_retrieval_per_query.json
#   02_merged_chunks.json
#   04_context_chunks_text.md
#   05_synthesis.md
#   06a_judge_evidence.md
#   06b_judge_evaluation.json
#   07_refined.md
#   07b_verification.json
```

## Evaluation

`evaluate.py` runs test queries and checks for specific video references, paint names, technique focus:

```bash
python3 evaluate.py
# Runs NMM gold + airbrush queries
# Checks: must_reference videos, must_mention paints, focus technique
# Returns composite score
```

## Location

- **Code:** `/Users/michaelsugimura/Documents/GitHub/tutorial-rag/`
- **Deployed:** spark:7870 (tmux session `tutorial-rag`)
- **Data:** `tutorial-rag/data/` (search_db.sqlite, search_indexes/, graph.gml)
- **Logs:** `tutorial-rag/query_logs/` on spark
- **Noospheric proxy:** `backend/main.py` proxies `/api/tutorial/query` and `/api/tutorial/search`
- **Design spec:** `noospheric/docs/superpowers/specs/2026-03-17-tutorial-rag-design.md`
