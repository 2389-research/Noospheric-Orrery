# Image Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add image support to the Orrery pipeline — images become first-class documents that are classified, tagged via simmered visual specs, embedded, and searchable alongside text.

**Architecture:** Images follow the same ingest → classify → extract → embed → search flow as text. A VLLM reads the image directly at each stage (no text reduction). Two specialist embedding indexes: text index (sentence-transformers) for text docs, image index (SigLIP) for image pixel + description embeddings. Text search queries both indexes in parallel.

**Tech Stack:** Anthropic vision API (Sonnet/Haiku with image content blocks), SigLIP for local image embeddings, Pillow for image preprocessing, existing FAISS infrastructure.

**Spec:** `docs/active/image_pipeline_from_architect.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `orchestrator/src/db.py` | Modify | Add `content_type`, `image_path`, `thumbnail_path` to documents; `media_type` to specs |
| `orchestrator/src/pipeline/image_prep.py` | Create | Image preprocessing — resize, thumbnail, base64 encoding |
| `orchestrator/src/pipeline/classifier.py` | Modify | Accept image content blocks alongside text |
| `orchestrator/src/pipeline/extractor.py` | Modify | Accept image content blocks for visual extraction |
| `orchestrator/src/routes/ingest.py` | Modify | Detect image uploads, skip chunking, route to vision pipeline |
| `orchestrator/src/routes/search.py` | Modify | Query image index in parallel with text index |
| `orchestrator/src/pipeline/image_embedding.py` | Create | SigLIP/Vertex multimodal embedding for images |
| `worker/src/jobs/simmer_general.py` | Modify | Branch on `media_type` for image spec lineage |
| `worker/src/jobs/evaluate_spec.py` | Modify | Pass images to VLLM for image spec evaluation |
| `frontend/src/components/file-upload.tsx` | Modify | Accept image file extensions |
| `orchestrator/src/repositories/sqlite_store.py` | Modify | Handle new columns in document/spec queries |

---

### Task 1: Schema — Add image columns to database

**Files:**
- Modify: `orchestrator/src/db.py`
- Modify: `orchestrator/src/repositories/sqlite_store.py`
- Test: `orchestrator/tests/test_db.py`

- [ ] **Step 1: Write failing test for content_type column**

```python
def test_document_has_content_type(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO documents (id, title, content, status, content_type) VALUES ('d1', 'test', 'hello', 'pending', 'image')")
    row = conn.execute("SELECT content_type FROM documents WHERE id = 'd1'").fetchone()
    assert row[0] == "image"
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && uv run pytest tests/test_db.py::test_document_has_content_type -v`
Expected: FAIL — no column `content_type`

- [ ] **Step 3: Add columns to schema**

In `orchestrator/src/db.py`, add to the documents CREATE TABLE:
```sql
content_type TEXT DEFAULT 'text',
image_path TEXT,
thumbnail_path TEXT
```

Add to specs CREATE TABLE:
```sql
media_type TEXT DEFAULT 'text'
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd orchestrator && uv run pytest tests/test_db.py::test_document_has_content_type -v`
Expected: PASS

- [ ] **Step 5: Update SQLite store document creation**

In `orchestrator/src/repositories/sqlite_store.py`, update `SQLiteDocumentRepository.create()` to accept and store `content_type`, `image_path`, `thumbnail_path` params. Default `content_type` to `'text'`.

- [ ] **Step 6: Run all existing tests to verify no regressions**

Run: `cd orchestrator && uv run pytest tests/ -v`
Expected: All existing tests pass (new columns have defaults, no breakage)

- [ ] **Step 7: Commit**

```bash
git add orchestrator/src/db.py orchestrator/src/repositories/sqlite_store.py orchestrator/tests/test_db.py
git commit -m "feat: add content_type, image_path, thumbnail_path to documents schema"
```

---

### Task 2: Image preprocessing — resize, thumbnail, base64

**Files:**
- Create: `orchestrator/src/pipeline/image_prep.py`
- Test: `orchestrator/tests/test_image_prep.py`

- [ ] **Step 1: Write failing tests**

```python
import base64
from pathlib import Path
from src.pipeline.image_prep import resize_image, make_thumbnail, image_to_base64, is_image_file

def test_is_image_file():
    assert is_image_file("photo.jpg") == True
    assert is_image_file("photo.PNG") == True
    assert is_image_file("photo.webp") == True
    assert is_image_file("notes.md") == False

def test_resize_preserves_aspect(tmp_path):
    # Create a 2000x1000 test image
    from PIL import Image
    img = Image.new("RGB", (2000, 1000), color="red")
    src = tmp_path / "big.jpg"
    img.save(src)
    resized = resize_image(src, max_edge=1024)
    assert resized.size[0] == 1024
    assert resized.size[1] == 512

def test_make_thumbnail(tmp_path):
    from PIL import Image
    img = Image.new("RGB", (2000, 1000), color="red")
    src = tmp_path / "big.jpg"
    img.save(src)
    thumb_path = make_thumbnail(src, tmp_path / "thumb.jpg")
    thumb = Image.open(thumb_path)
    assert max(thumb.size) <= 256

def test_image_to_base64(tmp_path):
    from PIL import Image
    img = Image.new("RGB", (100, 100), color="blue")
    src = tmp_path / "small.jpg"
    img.save(src)
    b64, media_type = image_to_base64(src, max_edge=1024)
    assert isinstance(b64, str)
    assert media_type == "image/jpeg"
    decoded = base64.b64decode(b64)
    assert len(decoded) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && uv run pytest tests/test_image_prep.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement image_prep.py**

```python
"""Image preprocessing — resize, thumbnail, base64 encoding for VLLM input."""
import base64
from io import BytesIO
from pathlib import Path
from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

def is_image_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS

def resize_image(path: Path, max_edge: int = 1024) -> Image.Image:
    img = Image.open(path)
    if max(img.size) <= max_edge:
        return img
    ratio = max_edge / max(img.size)
    new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
    return img.resize(new_size, Image.LANCZOS)

def make_thumbnail(path: Path, output_path: Path, max_edge: int = 256) -> Path:
    img = Image.open(path)
    img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    img.save(output_path, quality=80)
    return output_path

def image_to_base64(path: Path, max_edge: int = 1024) -> tuple[str, str]:
    img = resize_image(path, max_edge)
    buf = BytesIO()
    fmt = "JPEG"
    media_type = "image/jpeg"
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        fmt = "PNG"
        media_type = "image/png"
    elif suffix == ".webp":
        fmt = "WEBP"
        media_type = "image/webp"
    img.save(buf, format=fmt, quality=85)
    return base64.b64encode(buf.getvalue()).decode(), media_type
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && uv run pytest tests/test_image_prep.py -v`
Expected: All 4 PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/image_prep.py orchestrator/tests/test_image_prep.py
git commit -m "feat: image preprocessing — resize, thumbnail, base64 encoding"
```

---

### Task 3: Image classification — VLLM classifies images into domains

**Files:**
- Modify: `orchestrator/src/pipeline/classifier.py`
- Test: `orchestrator/tests/test_classifier.py`

- [ ] **Step 1: Write failing test for image classification**

```python
@pytest.mark.asyncio
async def test_classify_image():
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={
        "primary_domain": "hobbies/miniature-painting",
        "secondary_domains": ["hobbies/crafts"],
        "confidence": 0.85,
    })

    result = await classify_image(
        relay=mock_relay,
        image_base64="base64data...",
        media_type="image/jpeg",
        existing_taxonomy=["hobbies/miniature-painting", "business/strategy"],
        model="claude-sonnet-4-6",
        caption=None,
    )
    assert result["primary_domain"] == "hobbies/miniature-painting"

    # Verify the message included an image content block
    call_args = mock_relay.complete_structured.call_args
    messages = call_args.kwargs["messages"]
    content = messages[0]["content"]
    assert any(block.get("type") == "image" for block in content)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && uv run pytest tests/test_classifier.py::test_classify_image -v`
Expected: FAIL — `classify_image` not defined

- [ ] **Step 3: Add classify_image to classifier.py**

Add a new function that builds a message with an image content block:

```python
IMAGE_CLASSIFICATION_PROMPT = """Look at this image and classify it into one or more domain paths.

Existing taxonomy:
{taxonomy}

Assign the most specific matching domain(s). If no existing domain fits well, propose a new path.
Consider: subject matter, setting, activity, objects visible, any text in the image."""

async def classify_image(
    relay: Relay,
    image_base64: str,
    media_type: str,
    existing_taxonomy: list[str],
    model: str,
    caption: str | None = None,
) -> dict:
    taxonomy_str = "\n".join(f"- {d}" for d in existing_taxonomy) if existing_taxonomy else "(none yet)"
    text_prompt = IMAGE_CLASSIFICATION_PROMPT.format(taxonomy=taxonomy_str)
    if caption:
        text_prompt += f"\n\nUser-provided caption: {caption}"

    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_base64}},
        {"type": "text", "text": text_prompt},
    ]

    return await relay.complete_structured(
        model=model, max_tokens=1024,
        messages=[{"role": "user", "content": content}],
        schema=CLASSIFICATION_SCHEMA,
        tool_name="classify_document",
        tool_description="Classify an image into domain paths for the knowledge graph",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd orchestrator && uv run pytest tests/test_classifier.py::test_classify_image -v`
Expected: PASS

- [ ] **Step 5: Run all classifier tests**

Run: `cd orchestrator && uv run pytest tests/test_classifier.py -v`
Expected: All pass — existing text classification unchanged

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/pipeline/classifier.py orchestrator/tests/test_classifier.py
git commit -m "feat: image classification — VLLM assigns domains from image content"
```

---

### Task 4: Image entity extraction — VLLM extracts structured metadata from images

**Files:**
- Modify: `orchestrator/src/pipeline/extractor.py`
- Test: `orchestrator/tests/test_extractor.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_extract_entities_from_image():
    mock_relay = AsyncMock()
    mock_relay.complete_structured = AsyncMock(return_value={
        "entities": [
            {"name": "golden retriever", "type": "Subject"},
            {"name": "park", "type": "Setting"},
        ],
        "description": "A golden retriever playing fetch in a park",
        "tags": ["dog", "outdoor", "pet"],
    })

    result = await extract_entities_from_image(
        relay=mock_relay,
        image_base64="base64data...",
        media_type="image/jpeg",
        spec="For each image extract: subject, objects, setting...",
        model="claude-haiku-4-5",
    )
    assert len(result["entities"]) == 2
    assert result["description"] != ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && uv run pytest tests/test_extractor.py::test_extract_entities_from_image -v`
Expected: FAIL — function not defined

- [ ] **Step 3: Add extract_entities_from_image to extractor.py**

```python
IMAGE_EXTRACTION_PROMPT = """You are a visual entity extraction system. Follow the extraction spec below exactly.

EXTRACTION SPEC:
{spec}

Look at this image and extract all entities, metadata, and descriptions according to the spec.
Only extract what is actually visible — do not hallucinate or infer things not shown."""

IMAGE_ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entity name, lowercase"},
                    "type": {"type": "string", "description": "Entity type from the spec"},
                },
                "required": ["name", "type"],
            },
        },
        "description": {"type": "string", "description": "2-3 sentence description of the image"},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "Searchable tags"},
    },
    "required": ["entities", "description", "tags"],
}

async def extract_entities_from_image(
    relay: Relay,
    image_base64: str,
    media_type: str,
    spec: str,
    model: str,
) -> dict:
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_base64}},
        {"type": "text", "text": IMAGE_EXTRACTION_PROMPT.format(spec=spec)},
    ]
    return await relay.complete_structured(
        model=model, max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        schema=IMAGE_ENTITY_SCHEMA,
        tool_name="extract_image_entities",
        tool_description="Extract entities and metadata from an image",
    )
```

- [ ] **Step 4: Run tests**

Run: `cd orchestrator && uv run pytest tests/test_extractor.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/pipeline/extractor.py orchestrator/tests/test_extractor.py
git commit -m "feat: image entity extraction — VLLM reads images with visual spec"
```

---

### Task 5: Image ingest route — wire upload → preprocess → classify → extract

**Files:**
- Modify: `orchestrator/src/routes/ingest.py`
- Modify: `frontend/src/components/file-upload.tsx`
- Test: `orchestrator/tests/test_ingest.py`

- [ ] **Step 1: Write failing test for image ingest**

```python
@pytest.mark.asyncio
async def test_ingest_image(client, tmp_path):
    # Create a small test image
    from PIL import Image
    img = Image.new("RGB", (100, 100), color="red")
    img_path = tmp_path / "test.jpg"
    img.save(img_path)

    with open(img_path, "rb") as f:
        response = client.post("/ingest", files={"file": ("test.jpg", f, "image/jpeg")})
    assert response.status_code == 200
    data = response.json()
    assert data["document_id"]
    assert data["content_type"] == "image"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && uv run pytest tests/test_ingest.py::test_ingest_image -v`
Expected: FAIL

- [ ] **Step 3: Add image detection to ingest.py**

In `_ingest_document()`, after receiving the file content, check `is_image_file(filename)`:

```python
from .pipeline.image_prep import is_image_file, image_to_base64, make_thumbnail

# Early in _ingest_document, after file read:
if is_image_file(file.filename):
    return await _ingest_image(file, file_bytes, store, relay, settings)
```

Implement `_ingest_image()`:
- Save image to documents dir
- Generate thumbnail
- Create document with `content_type='image'`, store description as `content` (filled after extraction)
- Create single chunk (image path reference)
- Call `classify_image()` with base64
- Call `extract_entities_from_image()` with base64 + general image spec (if exists)
- Store extracted description as document content (for text search)
- Normalize entities, compute cooccurrences — same as text path

- [ ] **Step 4: Update frontend file-upload.tsx**

Add image extensions to the filter:
```typescript
const SUPPORTED_EXTENSIONS = [".txt", ".md", ".json", ".csv", ".jpg", ".jpeg", ".png", ".webp", ".gif"];
```

Update the `accept` attribute:
```html
accept=".txt,.md,.json,.csv,.jpg,.jpeg,.png,.webp,.gif"
```

Update the help text:
```
.txt .md .json .csv .jpg .png .webp — multiple files supported.
```

- [ ] **Step 5: Run tests**

Run: `cd orchestrator && uv run pytest tests/test_ingest.py -v`
Expected: All pass

- [ ] **Step 6: Manual smoke test**

Start the local stack, upload an image via the UI. Verify:
- Image appears in documents list
- Domains assigned
- Entities extracted
- Description visible

- [ ] **Step 7: Commit**

```bash
git add orchestrator/src/routes/ingest.py orchestrator/tests/test_ingest.py frontend/src/components/file-upload.tsx
git commit -m "feat: image ingest — upload, classify, extract via VLLM"
```

---

### Task 6: Image spec simmering — separate lineage for visual specs

**Files:**
- Modify: `worker/src/jobs/simmer_general.py`
- Modify: `worker/src/jobs/evaluate_spec.py`
- Test: `worker/tests/test_simmer_general.py`

- [ ] **Step 1: Add image seed spec**

In `simmer_general.py`, add `SEED_IMAGE_GOLDEN_SET`:

```python
SEED_IMAGE_GOLDEN_SET = """# Image Golden Set

## Visual Entity Types
- Subject — primary subject of the image (person, object, animal, scene)
- Object — identifiable items, products, tools, brands visible
- Person — anyone identifiable
- Text — any text visible (signs, labels, screens, documents)
- Setting — indoor/outdoor, location type, context
- Style — photograph, screenshot, diagram, illustration

## Reference Entities

Look at every sample image and list ALL visual entities you observe.
Format as a JSON array:
```json
[
  {"name": "entity name", "type": "EntityType"},
  ...
]
```
"""
```

- [ ] **Step 2: Add image simmer trigger**

In `simmer_general.py`, add `run_simmer_general_image()` that mirrors `run_simmer_general()` but:
- Queries documents with `content_type='image'`
- Copies image files to sample dir (not text content)
- Uses `SEED_IMAGE_GOLDEN_SET`
- Passes images as base64 content blocks in background

- [ ] **Step 3: Update evaluate_spec.py for images**

Add `--media-type` argument. When `image`:
- Load sample images instead of text files
- Call `extract_entities_from_image()` instead of `extract_chunk()`
- Same diff logic against golden set

- [ ] **Step 4: Update worker job dispatch**

In `worker/src/main.py`, add `simmer_general_image` job type routing.

- [ ] **Step 5: Test**

Run: `cd worker && uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add worker/src/jobs/simmer_general.py worker/src/jobs/evaluate_spec.py worker/src/main.py
git commit -m "feat: image spec simmering — separate visual spec lineage"
```

---

### Task 7: Image embedding — SigLIP for local, Vertex multimodal for cloud

**Files:**
- Create: `orchestrator/src/pipeline/image_embedding.py`
- Test: `orchestrator/tests/test_image_embedding.py`

- [ ] **Step 1: Write failing test**

```python
def test_embed_image_local(tmp_path):
    from PIL import Image
    img = Image.new("RGB", (224, 224), color="red")
    path = tmp_path / "test.jpg"
    img.save(path)

    from src.pipeline.image_embedding import embed_image
    embedding = embed_image(path)
    assert embedding is not None
    assert len(embedding) > 0  # SigLIP produces 768 or 1152-dim vectors
```

- [ ] **Step 2: Implement image_embedding.py**

```python
"""Image embedding via SigLIP (local) or Vertex AI multimodal (cloud)."""
from pathlib import Path
import numpy as np

def embed_image(path: Path) -> np.ndarray | None:
    """Embed an image using SigLIP. Returns None if not available."""
    try:
        from transformers import AutoProcessor, AutoModel
        from PIL import Image
        import torch

        model = AutoModel.from_pretrained("google/siglip-base-patch16-224")
        processor = AutoProcessor.from_pretrained("google/siglip-base-patch16-224")
        image = Image.open(path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            outputs = model.get_image_features(**inputs)
        embedding = outputs[0].numpy()
        return embedding / np.linalg.norm(embedding)
    except ImportError:
        return None

def embed_image_text(text: str) -> np.ndarray | None:
    """Embed text using SigLIP text encoder — same space as image embeddings."""
    try:
        from transformers import AutoProcessor, AutoModel
        import torch

        model = AutoModel.from_pretrained("google/siglip-base-patch16-224")
        processor = AutoProcessor.from_pretrained("google/siglip-base-patch16-224")
        inputs = processor(text=[text], return_tensors="pt", padding=True)
        with torch.no_grad():
            outputs = model.get_text_features(**inputs)
        embedding = outputs[0].numpy()
        return embedding / np.linalg.norm(embedding)
    except ImportError:
        return None
```

- [ ] **Step 3: Run test**

Run: `cd orchestrator && uv run pytest tests/test_image_embedding.py -v`
Expected: PASS (if transformers installed) or SKIP

- [ ] **Step 4: Commit**

```bash
git add orchestrator/src/pipeline/image_embedding.py orchestrator/tests/test_image_embedding.py
git commit -m "feat: image embedding via SigLIP — local multimodal search"
```

---

### Task 8: Search — query image index in parallel with text index

**Files:**
- Modify: `orchestrator/src/routes/search.py`
- Modify: `orchestrator/src/search/retrieval.py`
- Test: `orchestrator/tests/test_search.py`

- [ ] **Step 1: Add image FAISS index builder**

In `retrieval.py`, add `build_image_index(conn)` that builds a FAISS index from image embeddings stored in the chunks table (where `content_type='image'`).

- [ ] **Step 2: Add image search function**

```python
def search_images(query: str, index, image_ids: list, top_k: int = 10) -> list:
    """Embed query via SigLIP text path, search image FAISS index."""
    from .image_embedding import embed_image_text
    query_embedding = embed_image_text(query)
    if query_embedding is None:
        return []
    scores, indices = index.search(query_embedding.reshape(1, -1), top_k)
    return [{"id": image_ids[i], "score": float(scores[0][j])} for j, i in enumerate(indices[0]) if i >= 0]
```

- [ ] **Step 3: Wire into search route**

In `search.py`, after the existing text search, query the image index in parallel. Return image results as a separate section of the response.

- [ ] **Step 4: Test**

Run: `cd orchestrator && uv run pytest tests/test_search.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add orchestrator/src/routes/search.py orchestrator/src/search/retrieval.py orchestrator/tests/test_search.py
git commit -m "feat: parallel text + image search — SigLIP cross-modal retrieval"
```

---

### Task 9: Orrery viz integration — images in the galaxy map

**Files:**
- Modify: `orchestrator/src/routes/graph.py` — include `content_type` on document nodes
- Modify: `frontend/public/cosmic-viz.html` — render image document nodes with thumbnail
- Modify: `frontend/src/app/n/[noosphereId]/viz/page.tsx` — image document panel (thumbnail + description + entities)
- Modify: `frontend/src/components/entity-detail.tsx` or equivalent — show images alongside text docs when clicking an entity

**What needs to work:**
- Shared domains: images and text coexist in the same domain nebulae (already works — same entities table)
- Entity detail: clicking an entity shows docs AND images that reference it. `entity_sources` already links both content types — the UI just needs to render images with thumbnails instead of text previews.
- Star/solar system view: image documents orbit the entity star alongside text documents. Image nodes show a small thumbnail. Clicking opens an image viewer with the full image + extracted description + entity tags.
- Document node rendering: the graph API serves `content_type` per document. cosmic-viz.html checks this and renders image nodes differently (icon or thumbnail vs text preview).
- Galaxy level: no change needed. Domain nebulae glow based on entity count — image entities contribute the same as text entities.

- [ ] **Step 1: Add content_type to graph API response**

In `graph.py`, ensure document nodes include `content_type` and `thumbnail_path` fields.

- [ ] **Step 2: cosmic-viz.html — render image document nodes**

Check `content_type` on document nodes. If `'image'`, render with a camera icon or thumbnail indicator instead of text preview.

- [ ] **Step 3: Entity detail panel — show images**

When user clicks an entity, fetch its source documents. For image documents, show thumbnail + description. For text documents, show text snippet (existing behavior).

- [ ] **Step 4: Image viewer**

Clicking an image document opens a viewer showing: full-size image, extracted description, entity tags, domain assignment. Can be a modal or a new panel.

- [ ] **Step 5: Test end-to-end**

Upload images + text docs. Verify:
- Galaxy shows domains with both text and image entities
- Clicking a shared entity (e.g., "warhammer 40k") shows both text docs and images
- Star view shows image nodes with thumbnails orbiting the entity
- Image viewer opens correctly

- [ ] **Step 6: Commit**

```bash
git add orchestrator/src/routes/graph.py frontend/public/cosmic-viz.html frontend/src/
git commit -m "feat: orrery viz — image documents in galaxy map, entity detail, star view"
```

---

## Build & Test Order

Each task produces working, testable code independently:

1. **Schema** — database supports images (pure schema, no pipeline changes) ✅
2. **Image prep** — resize, thumbnail, base64 (pure functions, no API calls) ✅
3. **Classification** — VLLM classifies images (mock relay in tests) ✅
4. **Extraction** — VLLM extracts entities from images (mock relay in tests) ✅
5. **Ingest route** — wires 1-4 together into the upload flow (integration test)
6. **Simmering** — image-specific spec refinement (builds on 4)
7. **Embedding** — SigLIP image embeddings (can be tested standalone)
8. **Search** — parallel text + image search (builds on 7)
9. **Orrery viz** — image documents in galaxy map, entity detail, star view (builds on 5)

Tasks 1-4 are done and tested with real images via Bedrock. Task 5 is the next critical path — once images are in the real pipeline, Tasks 6-9 add capabilities on top.
