# Noospheric Application

The web application that surfaces the knowledge graph to users. Three tabs: Search (visual kit finding), Studio (concept art generation), Learn (tutorial RAG with knowledge graph).

## Stack

- **Backend:** FastAPI on DGX Spark (spark:7860)
- **Frontend:** Next.js 16 + React 19 + shadcn/ui + Tailwind 4
- **Deployment:** Static export (`output: "export"`) served by FastAPI. No Node on spark.
- **ML Models:** SAM3 (segmentation), SigLIP2 (visual embeddings), Gemini 3.1 Flash (image gen)
- **External APIs:** Gemini (Studio), OpenAI gpt-5.4-mini (Learn/RAG)

## Features

### Search Tab
Upload an image, click to segment a region (SAM3), find similar GW miniature kits (SigLIP2 cosine similarity).

- SAM3 image encoder caching: encode once on upload, decode per click (~0.05s)
- SigLIP2 grid embeddings: 5×5 grid + full image per product, 248K embeddings
- Size tier filtering from wahapedia base size data
- Model warmup at startup

### Studio Tab
Two flows powered by Gemini 3.1 Flash Image:

**Technique Preview:** Upload mini photo → brush mask region → pick technique/light/colour → Gemini generates reference showing that technique applied. Supports NMM, OSL, TMM, zenithal, blending, contrast, gem, glow.

**Concept Blend v2:** Pick faction reference (Combat Patrol box art from GW catalog) + aesthetic references (30 curated + upload) → set roles/weights → Gemini generates 1/2/4 variant concept art. Paintable vs cinematic toggle.

### Learn Tab
Ask a hobby question, get a tutorial with:
- Markdown response (left panel) with cited video references
- Interactive knowledge graph (right panel) showing the subgraph used to build the answer
- Click graph nodes to see transcript snippets via `/search` endpoint

Split layout: markdown left, graph right (50/50). Graph renders with Canvas2D force simulation.

## API Endpoints

### Core (in Noospheric container)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload` | POST | Upload image, run SAM3 encoder, return image_id |
| `/api/segment` | POST | Run SAM3 mask decoder on cached embeddings |
| `/api/search` | POST | SigLIP2 visual similarity search |
| `/api/products` | GET | Product catalog query |
| `/api/render/blend` | POST | Gemini concept blend (supports variants, catalog refs) |
| `/api/render/technique` | POST | Gemini technique preview (supports brush mask) |
| `/api/references/factions` | GET | Combat Patrol box art from catalog |
| `/api/references/aesthetics` | GET | Curated aesthetic reference images |

### Proxied to Tutorial RAG (spark:7870)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/tutorial/query` | POST | Full RAG pipeline → markdown + graph |
| `/api/tutorial/search` | GET | Entity/chunk lookup |

## Data

- `gw_catalog/catalog.db` — 2,031 products, 9,540 images (SQLite)
- `gw_catalog/embeddings/` — 248,040 SigLIP2 grid embeddings
- `gw_catalog/images/` — product images served via StaticFiles
- `gw_catalog/references/` — 30 curated aesthetic reference images
- `render_logs/` — every Gemini generation saved to disk

## Frontend Components

```
frontend/src/
  app/
    search/page.tsx          # Visual search
    studio/page.tsx          # Studio (Technique + Blend tabs)
    learn/page.tsx           # Learn (markdown + graph)
    layout.tsx               # Nav: Search | Studio | Learn
  components/
    image-canvas.tsx         # Upload + click-to-segment
    search-results.tsx       # Results grid + crop viewer
    studio/
      technique-flow.tsx     # Technique preview UI
      blend-flow.tsx         # Concept blend v2 UI
      mask-painter.tsx       # Brush mask canvas tool
      blend/                 # Faction picker, aesthetic picker, slot cards, variant grid
    learn/
      query-input.tsx        # Search bar + example chips
      graph-panel.tsx        # Canvas2D knowledge graph renderer
  lib/
    api.ts                   # Typed fetch wrappers
    types.ts                 # All shared types
```

## Deployment

```bash
# Build frontend
cd frontend && npm run build

# Deploy to spark
rsync -avz backend/ spark:/home/sugi/noospheric/backend/
rsync -avz frontend/out/ spark:/home/sugi/noospheric/frontend/out/

# Restart container
docker rm -f noospheric-api && docker run -d --gpus=all -p 7860:7860 \
  -e HF_TOKEN=... -e GEMINI_API_KEY=... -e TORCH_CUDNN_SDPA_ENABLED=1 \
  -e TUTORIAL_SERVICE_URL=http://172.17.0.1:7870 \
  -v /home/sugi/noospheric/backend:/workspace/backend:ro \
  -v /home/sugi/noospheric/frontend/out:/workspace/frontend/out:ro \
  -v /home/sugi/noospheric/gw_catalog:/workspace/gw_catalog:ro \
  -v /home/sugi/noospheric/render_logs:/workspace/render_logs \
  --workdir /workspace --name noospheric-api \
  noospheric-sam3 \
  bash -c 'pip install -q google-genai httpx && python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 7860'
```

## Location

- **Repo:** `github.com/2389-research/noospheric`
- **Branch:** `feat/graph-viz-and-learn-rag` (Learn + graph work), `main` (Search + Studio)
- **Deployed:** spark:7860
