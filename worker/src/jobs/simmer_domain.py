import json
from ..db import get_connection

async def run_simmer_domain(job: dict, db_path: str) -> None:
    """Domain-specific spec simmering — not yet implemented."""
    conn = get_connection(db_path)
    conn.execute("UPDATE jobs SET status = 'failed', result = ? WHERE id = ?",
        (json.dumps({"error": "Domain-specific simmering not yet implemented."}), job["id"]))
    conn.commit()
    conn.close()
