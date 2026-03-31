"""Domain-specific spec simmering — same as general but scoped to one domain.

TODO: Implement. For now, raises NotImplementedError.
The pattern is identical to simmer_general.py but:
- Reads docs only from the target domain
- Uses the general spec as the base artifact (not SEED_ONTOLOGY)
- Stores with domain_path set
"""
from google.cloud import firestore


async def run_simmer_domain(db: firestore.Client, workspace_id: str, job_id: str, job: dict):
    raise NotImplementedError("Domain-specific simmering not yet implemented for cloud worker")
