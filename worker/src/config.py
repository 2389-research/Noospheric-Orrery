import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    classification_model: str = "claude-sonnet-4-20250514"
    extraction_model: str = "claude-haiku-4-20250514"
    general_spec_threshold: int = 10
    domain_spec_threshold: int = 20
    simmer_iterations: int = 5
    chunk_size: int = 2000
    worker_poll_interval: int = 5
    db_path: str = "/data/orrery.db"
    documents_dir: str = "/data/documents"
    specs_dir: str = "/data/specs"

def get_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        classification_model=os.environ.get("CLASSIFICATION_MODEL", "claude-sonnet-4-20250514"),
        extraction_model=os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-20250514"),
        general_spec_threshold=int(os.environ.get("GENERAL_SPEC_THRESHOLD", "10")),
        domain_spec_threshold=int(os.environ.get("DOMAIN_SPEC_THRESHOLD", "20")),
        simmer_iterations=int(os.environ.get("SIMMER_ITERATIONS", "5")),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "2000")),
        worker_poll_interval=int(os.environ.get("WORKER_POLL_INTERVAL", "5")),
        db_path=os.environ.get("DB_PATH", "/data/orrery.db"),
        documents_dir=os.environ.get("DOCUMENTS_DIR", "/data/documents"),
        specs_dir=os.environ.get("SPECS_DIR", "/data/specs"),
    )
