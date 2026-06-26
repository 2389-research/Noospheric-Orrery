#!/usr/bin/env python3
# ABOUTME: Config-matrix harness — sweeps N×K (JUDGE_COUNT × JUDGE_SAMPLES) and fixed-vs-auto
# ABOUTME: panel over fixed inputs (golden + chunk dir) and reports F1 trajectory / relay calls / wall-clock.
#
# Usage:
#   worker/.venv/bin/python scripts/judge_matrix.py \
#       --golden path/to/golden.md \
#       --chunks path/to/chunks/ \
#       --iterations 3 \
#       --cells "1x1,1x3,2x1" \
#       [--panel auto|fixed]
#
# Output: JSON array, one object per cell:
#   { cell, n, k, panel, judge_mode, elapsed_s, relay_calls, composite_trajectory, final_spec_score }
#
# IMPORTANT: must be run with worker/.venv/bin/python so simmer_sdk and orrery_relay are importable.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

# ── sys.path: add worker/ so `from src.*` imports resolve ────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKER_DIR = _REPO_ROOT / "worker"
if str(_WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(_WORKER_DIR))

# ── Pure functions (no heavy deps — importable without simmer_sdk) ────────────

def parse_cells(cells_str: str) -> list[tuple[int, int]]:
    """Parse a comma-separated cell spec like '1x1,1x3,2x1' into (n, k) tuples.

    Case-insensitive on the 'x' separator. Whitespace is stripped.
    """
    result = []
    for part in cells_str.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)[xX](\d+)$", part)
        if not m:
            raise ValueError(f"Invalid cell spec '{part}' — expected NxK (e.g. '2x3')")
        result.append((int(m.group(1)), int(m.group(2))))
    return result


def load_chunks(chunks_dir: str) -> list[tuple[str, str, str]]:
    """Load *.txt chunk files from a directory.

    Returns a list of (id, text, title) tuples where:
      - id    = filename stem (e.g. 'abc123')
      - text  = full file contents (including any [Source: ...] header)
      - title = parsed from '[Source: ...]' header if present, else the filename stem

    The [Source: ...] format matches how run_simmer_general writes chunk files:
      '[Source: {document.title}]\\n\\n{chunk.text}'
    The text field is the whole file (so the extractor sees the same content as
    during a real simmer run).
    """
    chunks_path = Path(chunks_dir)
    result = []
    for p in sorted(chunks_path.glob("*.txt")):
        raw = p.read_text(encoding="utf-8")
        stem = p.stem
        # Try to parse "[Source: Title]" header — first non-empty line
        title = stem
        m = re.match(r"^\[Source:\s*(.+?)\]\s*$", raw.split("\n")[0])
        if m:
            title = m.group(1).strip()
        result.append((stem, raw, title))
    return result


# ── Relay-call counter ────────────────────────────────────────────────────────

class _CountingRelay:
    """Thin wrapper around a real Relay that increments a counter per complete/complete_structured call."""

    def __init__(self, relay, counter: list[int]):
        self._relay = relay
        self._counter = counter

    async def complete(self, *args, **kwargs):
        self._counter[0] += 1
        return await self._relay.complete(*args, **kwargs)

    async def complete_structured(self, *args, **kwargs):
        self._counter[0] += 1
        return await self._relay.complete_structured(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._relay, name)


# ── Per-cell async runner ─────────────────────────────────────────────────────

async def run_cell(
    n: int,
    k: int,
    panel: str,
    golden_path: str,
    chunks_dir: str,
    iterations: int,
    out_dir: str | None = None,
) -> dict:
    """Run one matrix cell and return the result dict.

    Heavy imports are deferred here so parse_cells / load_chunks are import-safe
    at module top (no simmer_sdk required for the pure functions).
    """
    # ── Lazy heavy imports ──────────────────────────────────────────────────
    from src.config import get_settings
    from src.db import init_db, get_connection
    from src.jobs.simmer_general import _refine_spec_rules

    import tempfile

    # ── Set env vars so get_settings() picks them up ───────────────────────
    os.environ["JUDGE_COUNT"] = str(n)
    os.environ["JUDGE_SAMPLES"] = str(k)
    os.environ["JUDGE_PANEL"] = panel

    settings = get_settings()

    cell_label = f"{n}x{k}/{panel}"

    # ── Fresh temp DB per cell ──────────────────────────────────────────────
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name
    init_db(db_path)

    # Insert a job row
    job_id = str(uuid.uuid4())
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO jobs (id, type, target, status) VALUES (?, 'simmer_general', 'general', 'running')",
        (job_id,),
    )
    conn.commit()
    conn.close()

    # ── Load inputs ─────────────────────────────────────────────────────────
    golden_md = Path(golden_path).read_text(encoding="utf-8")
    sample_chunks = load_chunks(chunks_dir)
    if not sample_chunks:
        raise ValueError(f"No chunk .txt files found in {chunks_dir!r}")

    # ── Wrap Relay.from_settings to count every complete/complete_structured call ──
    relay_calls_counter = [0]
    _relay_patched = False

    try:
        from orrery_relay import Relay as _Relay
        _orig_classmethod = _Relay.from_settings.__func__

        def patched_from_settings(cls, s):
            real = _orig_classmethod(cls, s)
            return _CountingRelay(real, relay_calls_counter)

        _Relay.from_settings = classmethod(patched_from_settings)
        _relay_patched = True
    except Exception:
        pass  # if orrery_relay is unavailable the counter stays 0

    # ── Time the run ─────────────────────────────────────────────────────────
    t0 = time.monotonic()
    try:
        spec_content, spec_score = await _refine_spec_rules(
            golden_md, sample_chunks, settings, job_id, db_path, iterations
        )

        # ── Read back trajectory ──────────────────────────────────────────────
        conn = get_connection(db_path)
        rows = conn.execute(
            "SELECT iteration, composite, judge_mode, asi, scores FROM simmer_iterations "
            "WHERE job_id = ? AND phase = 'extraction_spec' ORDER BY iteration",
            (job_id,),
        ).fetchall()
        conn.close()
    finally:
        elapsed = time.monotonic() - t0
        # Restore relay to its original classmethod
        if _relay_patched:
            try:
                _Relay.from_settings = classmethod(_orig_classmethod)
            except Exception:
                pass
        # Always clean up the temp DB (even on failure) so cells don't leak files
        if db_path and os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except Exception:
                pass

    composite_trajectory = [
        {"iteration": r[0], "composite": r[1], "judge_mode": r[2],
         "scores": json.loads(r[4]) if r[4] else {}, "asi": r[3]}
        for r in rows
    ]
    # Best recorded judge_mode (last non-null)
    judge_mode_values = [r[2] for r in rows if r[2]]
    judge_mode = judge_mode_values[-1] if judge_mode_values else "unknown"

    # ── Persist artifacts for qualitative inspection (final spec + per-round ASIs) ──
    if out_dir:
        safe = cell_label.replace("/", "__").replace(",", "_")
        od = Path(out_dir)
        od.mkdir(parents=True, exist_ok=True)
        (od / f"{safe}.spec.md").write_text(spec_content or "", encoding="utf-8")
        (od / f"{safe}.iters.json").write_text(
            json.dumps(composite_trajectory, indent=2), encoding="utf-8")

    return {
        "cell": cell_label,
        "n": n,
        "k": k,
        "panel": panel,
        "judge_mode": judge_mode,
        "elapsed_s": round(elapsed, 2),
        "relay_calls": relay_calls_counter[0],
        "composite_trajectory": composite_trajectory,
        "final_spec_score": spec_score,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sweep judge config (N×K) over fixed inputs and report F1/calls/wall-clock."
    )
    parser.add_argument("--golden", required=True, help="Path to the golden markdown file.")
    parser.add_argument("--chunks", required=True, help="Directory of chunk .txt files.")
    parser.add_argument(
        "--iterations", type=int, default=3, help="Simmer iterations per cell (default: 3)."
    )
    parser.add_argument(
        "--cells",
        default="1x1",
        help="Comma-separated NxK cells to run, e.g. '1x1,1x3,2x1' (default: '1x1').",
    )
    parser.add_argument(
        "--panel",
        default="auto",
        help="Judge panel: 'auto' (model picks lenses) or a fixed comma-list of lens names (default: auto).",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="If set, write each cell's final spec (<cell>.spec.md) and per-round ASIs/scores "
             "(<cell>.iters.json) here for qualitative inspection.",
    )
    args = parser.parse_args()

    cells = parse_cells(args.cells)
    results = []
    for n, k in cells:
        print(f"\n=== Cell {n}x{k} (panel={args.panel}) ===", flush=True)
        try:
            result = asyncio.run(
                run_cell(
                    n=n,
                    k=k,
                    panel=args.panel,
                    golden_path=args.golden,
                    chunks_dir=args.chunks,
                    iterations=args.iterations,
                    out_dir=args.out_dir,
                )
            )
        except Exception as exc:
            # Isolate per-cell failures: record the error and keep sweeping so a single
            # bad cell can't discard every completed cell's result on a costly live run.
            print(f"[judge_matrix] cell {n}x{k} failed: {exc}", file=sys.stderr, flush=True)
            results.append({
                "cell": f"{n}x{k}/{args.panel}", "n": n, "k": k, "panel": args.panel,
                "judge_mode": "error", "error": str(exc), "elapsed_s": None,
                "relay_calls": None, "composite_trajectory": [], "final_spec_score": None,
            })
            continue
        results.append(result)
        print(
            f"  elapsed={result['elapsed_s']}s  relay_calls={result['relay_calls']}  "
            f"final_score={result['final_spec_score']}  judge_mode={result['judge_mode']}",
            flush=True,
        )

    print("\n" + json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
