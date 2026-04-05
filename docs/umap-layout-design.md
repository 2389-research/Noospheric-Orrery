# UMAP Domain Layout — Design Notes

## How It Works

Each domain gets a 2D position on the galaxy map via UMAP dimensionality reduction.

### Embedding Input
For each domain, we concatenate:
```
"{domain_path (slashes → spaces)}. {top 6 doc titles}. {top 12 entity names}"
```
Embedded with all-MiniLM-L6-v2 (384-dim).

### UMAP Parameters
```python
umap.UMAP(
    n_components=2,
    n_neighbors=min(15, n_domains - 1),
    min_dist=0.15,
    spread=2.5,
    metric="cosine",
    random_state=42,  # deterministic
)
```

### Lifecycle
1. **First load** — no positions stored → `full_fit()` runs UMAP on all domains
2. **Subsequent loads** — positions read from storage (instant)
3. **New domain** — `transform()` places it using saved model (fast, ~1s)
4. **Domain count doubles** — `full_fit()` re-runs (resets all positions)

### Storage
- **SQLite**: `domain_layout` table (domain_path, x, y, embedding) + `layout_model` table (pickled UMAP reducer)
- **Firestore**: `workspaces/{id}/domainLayout/{path}` + `workspaces/{id}/layoutModel/umap`

### Known Issue: First-Mover Bias
UMAP projection is biased toward the first domains added to a workspace. Later, very different domains (e.g., adding warhammer to a business corpus) get squashed into remaining projection space.

**Planned fix**: Pre-seed UMAP with a diverse set of domain names across many fields to create a "universal" 2D projection. Ship as default model. Real domains use `transform()` against this balanced base.

### Minimum Separation
After UMAP, a repulsion pass enforces minimum 400wu separation between domains (200 iterations). This prevents overlap without destroying UMAP topology.

### Entity Positions
Entities derive their positions from cubed domain weights:
```javascript
// For each domain the entity belongs to:
cw = weight^3  // cubed for symmetry breaking
position = weighted_average(domain_positions, cubed_weights)
```
Multi-domain entities sit between their domains. Single-domain entities cluster near their domain's center.
