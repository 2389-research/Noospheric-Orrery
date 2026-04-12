# ABOUTME: Application settings loaded from environment variables.
# ABOUTME: Supports both gateway and bedrock backends via ANTHROPIC_BACKEND env var.

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    anthropic_backend: str = "gateway"
    gateway_url: str = ""
    gateway_api_key: str = ""
    aws_access_key: str = ""
    aws_secret_key: str = ""
    aws_region: str = "us-east-1"
    classification_model: str = "claude-sonnet-4-6"
    extraction_model: str = "claude-haiku-4-5"
    general_spec_threshold: int = 10
    domain_spec_threshold: int = 20
    simmer_iterations: int = 3
    chunk_size: int = 2000
    ollama_url: str = "http://localhost:11434"
    worker_poll_interval: int = 5
    db_path: str = "/data/orrery.db"
    documents_dir: str = "/data/documents"
    specs_dir: str = "/data/specs"


def _xdg_data_dir() -> str:
    """Base data directory following XDG Base Directory spec."""
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return str(Path(xdg) / "orrery")


def get_settings() -> Settings:
    _base = _xdg_data_dir()
    return Settings(
        anthropic_backend=os.environ.get("ANTHROPIC_BACKEND", "gateway"),
        gateway_url=os.environ.get("GATEWAY_URL", ""),
        gateway_api_key=os.environ.get("GATEWAY_API_KEY", ""),
        aws_access_key=os.environ.get("AWS_ACCESS_KEY", ""),
        aws_secret_key=os.environ.get("AWS_SECRET_KEY", ""),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        classification_model=os.environ.get("CLASSIFICATION_MODEL", "claude-sonnet-4-6"),
        extraction_model=os.environ.get("EXTRACTION_MODEL", "claude-haiku-4-5"),
        general_spec_threshold=int(os.environ.get("GENERAL_SPEC_THRESHOLD", "10")),
        domain_spec_threshold=int(os.environ.get("DOMAIN_SPEC_THRESHOLD", "20")),
        simmer_iterations=int(os.environ.get("SIMMER_ITERATIONS", "5")),
        chunk_size=int(os.environ.get("CHUNK_SIZE", "2000")),
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        worker_poll_interval=int(os.environ.get("WORKER_POLL_INTERVAL", "5")),
        db_path=os.environ.get("DB_PATH", f"{_base}/orrery.db"),
        documents_dir=os.environ.get("DOCUMENTS_DIR", f"{_base}/documents"),
        specs_dir=os.environ.get("SPECS_DIR", f"{_base}/specs"),
    )
