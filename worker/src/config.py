# ABOUTME: Application settings loaded from environment variables.
# ABOUTME: Supports both gateway and bedrock backends via ANTHROPIC_BACKEND env var.

import os
from dataclasses import dataclass, fields
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


# Env var name mapping — keys are Settings field names, values are env var names.
# If a field isn't listed, it uses UPPER_SNAKE_CASE of the field name.
_ENV_MAP = {
    "anthropic_backend": "ANTHROPIC_BACKEND",
    "gateway_url": "GATEWAY_URL",
    "gateway_api_key": "GATEWAY_API_KEY",
    "aws_access_key": "AWS_ACCESS_KEY",
    "aws_secret_key": "AWS_SECRET_KEY",
    "aws_region": "AWS_REGION",
    "classification_model": "CLASSIFICATION_MODEL",
    "extraction_model": "EXTRACTION_MODEL",
    "general_spec_threshold": "GENERAL_SPEC_THRESHOLD",
    "domain_spec_threshold": "DOMAIN_SPEC_THRESHOLD",
    "simmer_iterations": "SIMMER_ITERATIONS",
    "chunk_size": "CHUNK_SIZE",
    "ollama_url": "OLLAMA_URL",
    "worker_poll_interval": "WORKER_POLL_INTERVAL",
    "db_path": "DB_PATH",
    "documents_dir": "DOCUMENTS_DIR",
    "specs_dir": "SPECS_DIR",
}


def _xdg_data_dir() -> str:
    """Base data directory following XDG Base Directory spec."""
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return str(Path(xdg) / "orrery")


def get_settings() -> Settings:
    """Build Settings from env vars, falling back to dataclass defaults.

    Default paths use /data/ to match Docker layout. When /data/ doesn't
    exist (native dev without Docker), fall back to XDG paths.
    """
    defaults = Settings()

    # Use /data/ (Docker default) if it exists, otherwise XDG for native dev
    if os.path.isdir("/data"):
        _base = "/data"
    else:
        _base = _xdg_data_dir()

    path_defaults = {
        "db_path": f"{_base}/orrery.db",
        "documents_dir": f"{_base}/documents",
        "specs_dir": f"{_base}/specs",
    }

    kwargs = {}
    for f in fields(Settings):
        env_var = _ENV_MAP.get(f.name, f.name.upper())
        default = path_defaults.get(f.name, getattr(defaults, f.name))
        val = os.environ.get(env_var)
        if val is not None:
            kwargs[f.name] = f.type(val) if f.type in (int, float) else val
        else:
            kwargs[f.name] = default

    return Settings(**kwargs)
