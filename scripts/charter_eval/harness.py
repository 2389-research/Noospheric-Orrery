# ABOUTME: Collects dry-run results for one variant. dry_run=true writes nothing to the
# ABOUTME: graph, so this runs the production path safely; transport is injected so the
# ABOUTME: tests never make a live LLM call.
import json
import time
from dataclasses import dataclass
from collections.abc import Callable, Sequence

from .models import DocResult

Transport = Callable[[str], tuple[dict, float]]


@dataclass(frozen=True)
class CorpusEntry:
    doc_id: str
    path: str
    instrument: str
    executed: bool


@dataclass(frozen=True)
class Manifest:
    entries: tuple[CorpusEntry, ...]

    @classmethod
    def load(cls, path: str) -> "Manifest":
        with open(path) as f:
            raw = json.load(f)
        return cls(entries=tuple(
            CorpusEntry(doc_id=d["doc_id"], path=d["path"],
                        instrument=d["instrument"], executed=bool(d["executed"]))
            for d in raw["documents"]))


class HttpTransport:
    """The real transport. `full_names=true` is required — see Task 1."""

    def __init__(self, base_url: str, timeout: float = 900.0):
        self.url = f"{base_url.rstrip('/')}/ingest?dry_run=true&full_names=true"
        self.timeout = timeout

    def __call__(self, file_path: str) -> tuple[dict, float]:
        import httpx
        started = time.monotonic()
        with open(file_path, "rb") as f:
            r = httpx.post(self.url, files={"file": (file_path.split("/")[-1], f)},
                           timeout=self.timeout)
        elapsed = time.monotonic() - started
        r.raise_for_status()
        return r.json(), elapsed


def collect_with_errors(manifest: Manifest, variant: str, repeats: int,
                        transport: Transport) -> tuple[list[DocResult], list[dict]]:
    docs: list[DocResult] = []
    errors: list[dict] = []
    for repeat in range(repeats):
        for entry in manifest.entries:
            try:
                payload, latency = transport(entry.path)
            except Exception as e:            # one bad document must not lose the run
                errors.append({"doc_id": entry.doc_id, "repeat": repeat, "error": str(e)})
                continue
            docs.append(DocResult.from_response(
                entry.doc_id, entry.instrument, entry.executed,
                variant, repeat, latency, payload))
    return docs, errors


def collect(manifest: Manifest, variant: str, repeats: int,
            transport: Transport) -> list[DocResult]:
    docs, _ = collect_with_errors(manifest, variant, repeats, transport)
    return docs


def save(docs: Sequence[DocResult], path: str) -> None:
    with open(path, "w") as f:
        for d in docs:
            f.write(json.dumps(d.to_dict()) + "\n")


def load(path: str) -> list[DocResult]:
    with open(path) as f:
        return [DocResult.from_dict(json.loads(line)) for line in f if line.strip()]
