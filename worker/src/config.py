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
    judge_sweep_interval_seconds: int = 900  # periodic advisory-judge sweep cadence (~15 min)
    db_path: str = "/data/orrery.db"
    documents_dir: str = "/data/documents"
    specs_dir: str = "/data/specs"
    judge_count: int = 1
    judge_samples: int = 1
    judge_panel: str = "auto"
    judge_deliberate: bool = True
    # Tracker-run summarization. tracker's `distill` module reads its own
    # activity.jsonl format — that schema belongs to tracker and drifts on its own
    # schedule, so orrery-tracksum takes an INJECTED trace reader rather than
    # vendoring the parser. Point this at the directory containing distill.py to let
    # the worker summarize RAW runs in-process; leave it empty and only pre-made
    # summary bundles can be ingested (which need no model calls at all).
    tracker_distill_path: str = ""


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
    "judge_sweep_interval_seconds": "JUDGE_SWEEP_INTERVAL_SECONDS",
    "db_path": "DB_PATH",
    "documents_dir": "DOCUMENTS_DIR",
    "specs_dir": "SPECS_DIR",
    "judge_count": "JUDGE_COUNT",
    "judge_samples": "JUDGE_SAMPLES",
    "judge_panel": "JUDGE_PANEL",
    "judge_deliberate": "JUDGE_DELIBERATE",
    "tracker_distill_path": "TRACKER_DISTILL_PATH",
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
            if f.type is bool:
                kwargs[f.name] = str(val).strip().lower() in ("1", "true", "yes", "on")
            elif f.type in (int, float):
                kwargs[f.name] = f.type(val)
            else:
                kwargs[f.name] = val
        else:
            kwargs[f.name] = default

    return Settings(**kwargs)
