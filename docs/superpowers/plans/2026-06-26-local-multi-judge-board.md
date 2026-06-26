# Local Multi-Judge Board Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional multi-judge board (and single-judge self-consistency) to the local, non-agentic simmer loop, parameterized by judge count N and sample count K, with N=1/K=1 reproducing today's single-judge path exactly.

**Architecture:** Reuse simmer-sdk's *pure* prompt-builders / parser / median-consensus, drive them with bounded `relay.complete` calls (never the SDK's agentic dispatch). Integrate by injecting a `judge_fn` into `simmer_loop` (one-line change); the caller builds either today's `relay_judge` (floor) or a board judge closure. The board returns the same `JudgeOutput`, so the loop/reflect/recorder are otherwise untouched.

**Tech Stack:** Python 3.11+, `orrery_relay.Relay`, vendored `simmer_sdk`, `pytest` + `pytest-asyncio`, SQLite.

**Spec:** `docs/superpowers/specs/2026-06-26-local-multi-judge-board-design.md`

**Resolved open questions (from spec §9):**
- **O1 ASI synthesis:** synth-call via `build_synthesis_prompt`, with a deterministic *pick-one* fallback (highest-headroom judge's ASI) when the synthesized ASI parses empty.
- **O2 Lens library:** a small orrery-owned, net-new library; lenses are generic (criteria-driven), composer picks the relevant ones per phase.
- **O3 Composer cadence:** resolve the panel **once per simmer run** (cheaper on serial Ollama), pass it into the loop.
- **O4 Per-panelist persistence:** log-only for v1; consensus recorded in the existing tables.
- **O5 Deliberation:** built in v1 behind `JUDGE_DELIBERATE` (default true); structural tests cover on/off.

---

## File Structure

| File | Create/Modify | Responsibility |
|------|---------------|----------------|
| `worker/src/config.py` | Modify | Add `judge_count`, `judge_samples`, `judge_panel`, `judge_deliberate` settings + bool env parsing. |
| `worker/src/jobs/simmer_core.py` | Modify | `simmer_loop` accepts `judge_fn` (default `relay_judge`) + `judge_mode` (default `"relay-judge"`); call `judge_fn` instead of the hardcoded judge; pass `judge_mode` to the recorder. No other change. |
| `worker/src/jobs/judge_board.py` | **Create** | The board: lens library, `resolve_panel` (+ constrained composer), `relay_panelist`, `combine_outputs`, `relay_deliberate`, `make_board_judge`. All bounded relay calls. |
| `worker/src/jobs/simmer_general.py` | Modify | `_resolve_judge_fn(settings, criteria, seed, problem_class)` helper; both `_build_golden_set_judged` and `_refine_spec_rules` resolve a judge_fn once and pass it (+ judge_mode) to `simmer_loop`. |
| `worker/tests/test_judge_board.py` | **Create** | Structural tests (mocked relay) for the board building blocks + invariants. |
| `worker/tests/test_simmer_core.py` | Modify | Add: loop uses injected `judge_fn`; default is `relay_judge`; `judge_mode` recorded. |
| `scripts/judge_matrix.py` | **Create** | Config-matrix harness: sweep N×K (+ fixed/auto panel) over fixed inputs, emit F1 / score-variance / call-count / wall-clock per cell. |

**The judge_fn contract** (every judge, single or board, matches `relay_judge`'s signature):
```python
async def judge_fn(candidate: str, evidence: str, criteria: dict, settings, *,
                   iteration: int = 0, evaluator_output: str | None = None,
                   seed_candidate: str | None = None, seed_scores: dict | None = None,
                   problem_class: str = "text/creative") -> JudgeOutput
```

---

### Task 1: Config knobs (N, K, panel, deliberate)

**Files:**
- Modify: `worker/src/config.py`
- Test: `worker/tests/test_config_judge.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
# worker/tests/test_config_judge.py
import importlib
from src import config as config_mod

def _get(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return config_mod.get_settings()

def test_judge_defaults_reproduce_today(monkeypatch):
    for k in ("JUDGE_COUNT", "JUDGE_SAMPLES", "JUDGE_PANEL", "JUDGE_DELIBERATE"):
        monkeypatch.delenv(k, raising=False)
    s = config_mod.get_settings()
    assert s.judge_count == 1 and s.judge_samples == 1
    assert s.judge_panel == "auto" and s.judge_deliberate is True

def test_judge_env_overrides(monkeypatch):
    s = _get(monkeypatch, JUDGE_COUNT="2", JUDGE_SAMPLES="3",
             JUDGE_PANEL="coverage_hawk,precision_hawk", JUDGE_DELIBERATE="false")
    assert s.judge_count == 2 and s.judge_samples == 3
    assert s.judge_panel == "coverage_hawk,precision_hawk"
    assert s.judge_deliberate is False   # MUST parse the string, not be truthy "false"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd worker && python -m pytest tests/test_config_judge.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'judge_count'`.

- [ ] **Step 3: Add the fields + env mapping + bool parsing**

In `worker/src/config.py`, add to the `Settings` dataclass (after `specs_dir`):
```python
    judge_count: int = 1
    judge_samples: int = 1
    judge_panel: str = "auto"
    judge_deliberate: bool = True
```
Add to `_ENV_MAP`:
```python
    "judge_count": "JUDGE_COUNT",
    "judge_samples": "JUDGE_SAMPLES",
    "judge_panel": "JUDGE_PANEL",
    "judge_deliberate": "JUDGE_DELIBERATE",
```
In `get_settings()`, the conversion line currently is:
```python
            kwargs[f.name] = f.type(val) if f.type in (int, float) else val
```
Replace with bool-aware parsing (bool("false") is True — a trap):
```python
            if f.type is bool:
                kwargs[f.name] = str(val).strip().lower() in ("1", "true", "yes", "on")
            elif f.type in (int, float):
                kwargs[f.name] = f.type(val)
            else:
                kwargs[f.name] = val
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd worker && python -m pytest tests/test_config_judge.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add worker/src/config.py worker/tests/test_config_judge.py
git commit -m "feat(simmer): add judge board config knobs (N/K/panel/deliberate) with bool parsing"
```

---

### Task 2: Inject `judge_fn` into `simmer_loop` (no-regression floor)

**Files:**
- Modify: `worker/src/jobs/simmer_core.py` (`simmer_loop`, ~line 119-162)
- Modify: `worker/tests/test_simmer_core.py`

- [ ] **Step 1: Write the failing tests**

Add to `worker/tests/test_simmer_core.py`:
```python
@pytest.mark.asyncio
async def test_loop_uses_injected_judge_fn_and_records_its_mode(test_db):
    _job(test_db)
    async def generate_fn(candidate, asi): return "next"
    fake = AsyncMock(side_effect=[JudgeOutput(scores={"coverage": 7}, asi="a", reasoning={}) for _ in range(2)])
    await simmer_loop(
        phase="golden_set", job_id="j1", db_path=test_db, settings=_settings(),
        criteria={"coverage": "..."}, iterations=1, seed_candidate="seed",
        generate_fn=generate_fn, evidence="ev",
        judge_fn=fake, judge_mode="relay-board")
    assert fake.await_count == 2                 # the injected fn was used, not relay_judge
    rows = _iters(test_db)
    assert all(jm == "relay-board" for *_, jm, _ in rows)   # mode recorded

@pytest.mark.asyncio
async def test_loop_defaults_to_relay_judge(test_db):
    _job(test_db)
    async def generate_fn(candidate, asi): return "next"
    with patch.object(simmer_core, "relay_judge",
                      new=AsyncMock(side_effect=[JudgeOutput(scores={"c": 6}, asi="a", reasoning={}) for _ in range(2)])) as rj:
        await simmer_loop(
            phase="golden_set", job_id="j1", db_path=test_db, settings=_settings(),
            criteria={"c": "..."}, iterations=1, seed_candidate="seed",
            generate_fn=generate_fn, evidence="ev")     # no judge_fn → default
    assert rj.await_count == 2                           # default path unchanged
    rows = _iters(test_db)
    assert all(jm == "relay-judge" for *_, jm, _ in rows)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd worker && python -m pytest tests/test_simmer_core.py -k "injected or defaults_to_relay" -v`
Expected: FAIL — `simmer_loop() got an unexpected keyword argument 'judge_fn'`.

- [ ] **Step 3: Add the params (minimal change)**

In `simmer_core.py`, `simmer_loop` signature — add two kwargs:
```python
async def simmer_loop(*, phase, job_id, db_path, settings, criteria, iterations,
                      seed_candidate, generate_fn, evidence, evaluator_fn=None,
                      problem_class="text/creative",
                      judge_fn=None, judge_mode="relay-judge"):
```
At the top of the function body (before the loop):
```python
    judge = judge_fn or relay_judge
```
Replace the `judgment = await relay_judge(...)` call with `judge(...)`:
```python
        judgment = await judge(
            candidate, evidence, criteria, settings,
            iteration=i, evaluator_output=evaluator_output,
            seed_candidate=seed_artifact, seed_scores=seed_scores,
            problem_class=problem_class)
```
Pass `judge_mode` through to the recorder. In `_record_judged_iteration`, replace the hardcoded `"relay-judge"` literal with a `judge_mode` parameter; add `judge_mode` to its signature and to the `simmer_loop` call site:
```python
def _record_judged_iteration(db_path, job_id, phase, iteration, judgment, seed_scores,
                             regressed, key_change, candidate_preview, judge_mode="relay-judge"):
    ...
    # in the INSERT, use judge_mode instead of the literal "relay-judge"
```
And at the call site inside `simmer_loop`:
```python
        _record_judged_iteration(
            db_path, job_id, phase, i, judgment, seed_scores, regressed,
            key_change=("seed" if i == 0 else "regenerated from ASI"),
            candidate_preview=candidate[:500], judge_mode=judge_mode)
```

- [ ] **Step 4: Run to verify pass — AND the full existing suite (no regression)**

Run: `cd worker && python -m pytest tests/test_simmer_core.py -v`
Expected: PASS — new tests pass and **all pre-existing tests still pass** (the floor is unchanged).

- [ ] **Step 5: Commit**

```bash
git add worker/src/jobs/simmer_core.py worker/tests/test_simmer_core.py
git commit -m "feat(simmer): inject judge_fn + judge_mode into simmer_loop (default = relay_judge)"
```

---

### Task 3: Lens library + `combine_outputs` (median + synthesized ASI)

**Files:**
- Create: `worker/src/jobs/judge_board.py`
- Test: `worker/tests/test_judge_board.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
# worker/tests/test_judge_board.py
import types
import pytest
from unittest.mock import AsyncMock, patch
from simmer_sdk import JudgeOutput
from src.jobs import judge_board

def _settings():
    return types.SimpleNamespace(classification_model="m", extraction_model="e",
                                 judge_count=2, judge_samples=1, judge_panel="auto",
                                 judge_deliberate=True)

def test_lens_library_nonempty_and_named():
    assert isinstance(judge_board.LENS_LIBRARY, dict) and judge_board.LENS_LIBRARY
    for name, lens in judge_board.LENS_LIBRARY.items():
        assert name == name.lower() and isinstance(lens, str) and lens

@pytest.mark.asyncio
async def test_combine_uses_median_scores_and_synthesized_asi():
    outs = [
        ("Judge A", "raw a", JudgeOutput(scores={"coverage": 6, "precision": 9}, asi="asi-a", reasoning={})),
        ("Judge B", "raw b", JudgeOutput(scores={"coverage": 8, "precision": 5}, asi="asi-b", reasoning={})),
        ("Judge C", "raw c", JudgeOutput(scores={"coverage": 7, "precision": 7}, asi="asi-c", reasoning={})),
    ]
    synth_text = "COMPOSITE: 7.0/10\n\nASI (highest-leverage direction):\nThe synthesized direction."
    relay = types.SimpleNamespace(complete=AsyncMock(return_value=types.SimpleNamespace(text=synth_text)))
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        result = await judge_board.combine_outputs(
            outs, criteria={"coverage": "...", "precision": "..."}, settings=_settings(),
            artifact_type="text", deliberations=[])
    assert result.scores == {"coverage": 7, "precision": 7}   # medians
    assert result.asi == "The synthesized direction."

@pytest.mark.asyncio
async def test_combine_falls_back_to_pick_one_when_synth_asi_empty():
    # synth returns no usable ASI → pick the ASI from the highest-headroom (lowest consensus) criterion's judge
    outs = [
        ("Judge A", "raw a", JudgeOutput(scores={"coverage": 3, "precision": 9}, asi="fix-coverage", reasoning={})),
        ("Judge B", "raw b", JudgeOutput(scores={"coverage": 4, "precision": 8}, asi="fix-precision", reasoning={})),
    ]
    relay = types.SimpleNamespace(complete=AsyncMock(return_value=types.SimpleNamespace(text="(no asi here)")))
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        result = await judge_board.combine_outputs(
            outs, criteria={"coverage": "...", "precision": "..."}, settings=_settings(),
            artifact_type="text", deliberations=[])
    assert result.asi  # non-empty: fell back to a panelist ASI targeting the weakest criterion (coverage)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_judge_board.py -k "lens_library or combine" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.jobs.judge_board'`.

- [ ] **Step 3: Create `judge_board.py` with the library + combine**

```python
# worker/src/jobs/judge_board.py
# ABOUTME: Local multi-judge board — bounded relay calls reusing simmer-sdk's pure prompt
# ABOUTME: builders, median consensus, and parser. NEVER calls the SDK's agentic dispatch.
#
# CHESTERTON'S FENCE: see CLAUDE.md "Simmer pipeline" + the design doc
# docs/superpowers/specs/2026-06-26-local-multi-judge-board-design.md. This is the SAME pattern as
# relay_judge: everything pre-loaded inline, no tools, think:false via orrery-relay. Do NOT import
# or call simmer_sdk.judge_board's _dispatch_single_panelist (it is agentic and stalls gemma4).

import re
from orrery_relay import Relay
from simmer_sdk import JudgeOutput
from simmer_sdk.types import JudgeDefinition
from simmer_sdk.judge import parse_judge_output
from simmer_sdk.judge_board import compute_consensus_scores
from simmer_sdk.prompts import (
    build_board_panelist_prompt, build_deliberation_prompt, build_synthesis_prompt,
)
from simmer_sdk.primitives import get_primitives_for_judge

from .simmer_core import relay_judge, NON_AGENTIC_JUDGE_PREAMBLE

# Curated, orrery-owned lens menu (A). The composer (B) picks from THESE names only.
# Generic + criteria-driven so the same menu serves golden and spec phases.
LENS_LIBRARY: dict[str, str] = {
    "coverage_hawk": "Score from a recall lens: hunt for entities present in the source/golden that the candidate misses. Reward completeness; punish coverage gaps.",
    "precision_hawk": "Score from a precision lens: hunt for entities the candidate includes that are not real or are metadata (bare dates, ids, urls). Reward tight precision; punish noise.",
    "generalizability_skeptic": "Score from a generalization lens: does the artifact rely on general rules/type-definitions rather than hardcoded entity names? Reward what would work on unseen documents.",
    "taxonomy_purist": "Score from a taxonomy lens: are entity types meaningful, consistent, correctly assigned, and (for a domain) granular rather than generic?",
}

DEFAULT_PANEL = ["coverage_hawk", "precision_hawk"]   # fallback when composition fails


def _extract_asi(text: str, criteria: dict) -> str:
    out = parse_judge_output(text, criteria)
    asi = (out.asi or "").strip()
    if asi:
        asi = re.sub(r"^\s*ASI\b[^\n:]*:\s*", "", asi, flags=re.IGNORECASE).strip()
    return asi


async def combine_outputs(outputs, criteria, settings, *, artifact_type, deliberations=None):
    """Count-agnostic COMBINE: median scores (SDK) + ONE synthesized ASI (synth-call).

    `outputs`: list of (name, raw_text, JudgeOutput). `deliberations`: list of (name, text) or None.
    Median handles scores deterministically. The ASI is synthesized by a single bounded relay call
    (build_synthesis_prompt). If that yields no usable ASI, fall back to the ASI of the judge whose
    weakest (lowest-consensus) criterion has the most headroom — deterministic, zero extra call.
    """
    scores = compute_consensus_scores([o[2].scores for o in outputs])
    relay = Relay.from_settings(settings)
    prompt = build_synthesis_prompt(
        criteria=criteria,
        all_judge_outputs=[(name, raw) for name, raw, _ in outputs],
        deliberation_results=deliberations or [],
        artifact_type=artifact_type)
    resp = await relay.complete(model=settings.classification_model, max_tokens=2048,
                                messages=[{"role": "user", "content": prompt}])
    asi = _extract_asi(resp.text, criteria)
    if not asi:
        # pick-one fallback: target the weakest criterion, take that judge's ASI
        weakest = min(scores, key=scores.get) if scores else None
        best = None
        for _, _, jo in outputs:
            if weakest is not None and weakest in jo.scores:
                if best is None or jo.scores[weakest] <= best[0]:
                    best = (jo.scores[weakest], jo.asi)
        asi = (best[1] if best else (outputs[0][2].asi if outputs else "")) or ""
    reasoning = {}
    for _, _, jo in outputs:
        for k, v in (jo.reasoning or {}).items():
            reasoning.setdefault(k, v)
    return JudgeOutput(scores=scores, asi=asi, reasoning=reasoning)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd worker && python -m pytest tests/test_judge_board.py -k "lens_library or combine" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add worker/src/jobs/judge_board.py worker/tests/test_judge_board.py
git commit -m "feat(simmer): lens library + combine_outputs (median scores + synthesized ASI)"
```

---

### Task 4: `relay_panelist` (one lensed, non-agentic scoring call)

**Files:**
- Modify: `worker/src/jobs/judge_board.py`
- Modify: `worker/tests/test_judge_board.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_relay_panelist_returns_named_output_with_lens():
    from simmer_sdk.types import JudgeDefinition
    text = ("ITERATION 0 SCORES:\n  coverage: 7/10 — ok — add\nCOMPOSITE: 7.0/10\n\n"
            "ASI (highest-leverage direction):\nDo the thing.")
    relay = types.SimpleNamespace(complete=AsyncMock(return_value=types.SimpleNamespace(text=text)))
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        name, raw, out = await judge_board.relay_panelist(
            JudgeDefinition(name="coverage_hawk", lens=judge_board.LENS_LIBRARY["coverage_hawk"]),
            candidate="cand", evidence="EVIDENCE_SENTINEL", criteria={"coverage": "..."},
            settings=_settings(), iteration=0, evaluator_output=None,
            seed_candidate=None, seed_scores=None, problem_class="text/creative")
    assert name == "coverage_hawk"
    assert out.scores == {"coverage": 7} and out.asi == "Do the thing."
    # evidence is pre-loaded inline (non-agentic) — assert it reached the prompt
    sent = relay.complete.await_args.kwargs["messages"][0]["content"]
    assert "EVIDENCE_SENTINEL" in sent
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd worker && python -m pytest tests/test_judge_board.py -k relay_panelist -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'relay_panelist'`.

- [ ] **Step 3: Implement `relay_panelist`**

Add to `judge_board.py`:
```python
async def relay_panelist(judge_def, candidate, evidence, criteria, settings, *,
                         iteration=0, evaluator_output=None, seed_candidate=None,
                         seed_scores=None, problem_class="text/creative"):
    """One panelist = ONE bounded relay.complete with a lens, everything pre-loaded inline, no tools.
    Mirror of relay_judge but built with build_board_panelist_prompt so it carries the lens +
    judge skill + board primitives. Returns (name, raw_text, JudgeOutput)."""
    relay = Relay.from_settings(settings)
    primitives = get_primitives_for_judge(
        has_evaluator=evaluator_output is not None, has_search_space=False)
    prompt = build_board_panelist_prompt(
        judge_def=judge_def, iteration=iteration, artifact_type="text",
        problem_class=problem_class, criteria=criteria, candidate=candidate,
        primitives=primitives, seed_candidate=seed_candidate, seed_scores=seed_scores,
        evaluator_output=evaluator_output, judge_preamble=NON_AGENTIC_JUDGE_PREAMBLE)
    prompt += ("\n\nSOURCE MATERIAL — judge the candidate strictly against THIS "
               "(provided inline; do not use tools):\n" + evidence)
    resp = await relay.complete(model=settings.classification_model, max_tokens=3072,
                                messages=[{"role": "user", "content": prompt}])
    out = parse_judge_output(resp.text, criteria)
    if out.asi:
        out.asi = re.sub(r"^\s*ASI\b[^\n:]*:\s*", "", out.asi, flags=re.IGNORECASE).strip()
    return judge_def.name, resp.text, out
```

- [ ] **Step 4: Run to verify pass**

Run: `cd worker && python -m pytest tests/test_judge_board.py -k relay_panelist -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add worker/src/jobs/judge_board.py worker/tests/test_judge_board.py
git commit -m "feat(simmer): relay_panelist — non-agentic lensed scoring call (evidence pre-loaded)"
```

---

### Task 5: `resolve_panel` — config-list and constrained composer

**Files:**
- Modify: `worker/src/jobs/judge_board.py`
- Modify: `worker/tests/test_judge_board.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_resolve_panel_from_explicit_config_list_skips_composer():
    s = _settings(); s.judge_panel = "coverage_hawk, precision_hawk, NOT_A_LENS"; s.judge_count = 3
    relay = types.SimpleNamespace(complete=AsyncMock())   # must NOT be called
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        panel = await judge_board.resolve_panel(s, criteria={"coverage": "..."},
                                                candidate="c", problem_class="text/creative")
    assert [j.name for j in panel] == ["coverage_hawk", "precision_hawk"]   # unknown dropped
    relay.complete.assert_not_called()

@pytest.mark.asyncio
async def test_resolve_panel_auto_uses_composer_and_picks_from_menu():
    s = _settings(); s.judge_panel = "auto"; s.judge_count = 2
    relay = types.SimpleNamespace(complete=AsyncMock(
        return_value=types.SimpleNamespace(text="precision_hawk\ntaxonomy_purist\nbogus")))
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        panel = await judge_board.resolve_panel(s, criteria={"precision": "..."},
                                                candidate="c", problem_class="text/creative")
    assert [j.name for j in panel] == ["precision_hawk", "taxonomy_purist"]  # only menu names, ≤N

@pytest.mark.asyncio
async def test_resolve_panel_falls_back_to_default_on_composer_garbage():
    s = _settings(); s.judge_panel = "auto"; s.judge_count = 2
    relay = types.SimpleNamespace(complete=AsyncMock(
        return_value=types.SimpleNamespace(text="no valid names here")))
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        panel = await judge_board.resolve_panel(s, criteria={"x": "..."},
                                                candidate="c", problem_class="text/creative")
    assert [j.name for j in panel] == judge_board.DEFAULT_PANEL[:2]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd worker && python -m pytest tests/test_judge_board.py -k resolve_panel -v`
Expected: FAIL — no `resolve_panel`.

- [ ] **Step 3: Implement `resolve_panel` + composer**

Add to `judge_board.py`:
```python
COMPOSER_PROMPT = """You are composing a small panel of evaluation judges. Choose the {n} MOST useful
lenses for evaluating a candidate against these criteria. Pick ONLY from the menu — do not invent.

CRITERIA:
{criteria}

MENU (choose by exact name):
{menu}

Return ONLY the chosen lens names, one per line, at most {n}. No commentary."""


def _judges_from_names(names):
    seen, out = set(), []
    for n in names:
        n = n.strip().lower()
        if n in LENS_LIBRARY and n not in seen:
            seen.add(n)
            out.append(JudgeDefinition(name=n, lens=LENS_LIBRARY[n]))
    return out


async def resolve_panel(settings, criteria, candidate, *, problem_class):
    """Resolve the panel ONCE per run (O3). Explicit JUDGE_PANEL list bypasses the composer;
    'auto' runs one bounded composer call that picks ≤N names FROM the menu. Falls back to
    DEFAULT_PANEL on empty/garbage. Always truncated to judge_count."""
    n = max(1, int(settings.judge_count))
    if settings.judge_panel and settings.judge_panel.strip().lower() != "auto":
        panel = _judges_from_names(settings.judge_panel.split(","))
        return (panel or _judges_from_names(DEFAULT_PANEL))[:n]
    menu = "\n".join(f"- {name}: {lens}" for name, lens in LENS_LIBRARY.items())
    crit = "\n".join(f"- {k}: {v}" for k, v in criteria.items())
    relay = Relay.from_settings(settings)
    try:
        resp = await relay.complete(
            model=settings.classification_model, max_tokens=256,
            messages=[{"role": "user", "content": COMPOSER_PROMPT.format(n=n, criteria=crit, menu=menu)}])
        panel = _judges_from_names(resp.text.splitlines())[:n]
    except Exception as e:
        print(f"  [judge_board] composer failed: {e}", flush=True)
        panel = []
    return panel or _judges_from_names(DEFAULT_PANEL)[:n]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd worker && python -m pytest tests/test_judge_board.py -k resolve_panel -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add worker/src/jobs/judge_board.py worker/tests/test_judge_board.py
git commit -m "feat(simmer): resolve_panel — explicit list or constrained menu composer + fallback"
```

---

### Task 6: `make_board_judge` — orchestrate score×K → deliberate → combine

**Files:**
- Modify: `worker/src/jobs/judge_board.py`
- Modify: `worker/tests/test_judge_board.py`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_board_judge_scores_each_lens_times_K_then_combines(monkeypatch):
    from simmer_sdk.types import JudgeDefinition
    panel = [JudgeDefinition(name="coverage_hawk", lens="..."),
             JudgeDefinition(name="precision_hawk", lens="...")]
    panelist_calls = []
    async def fake_panelist(jd, *a, **k):
        panelist_calls.append((jd.name, k.get("iteration")))
        return jd.name, "raw", JudgeOutput(scores={"coverage": 6}, asi=f"asi-{jd.name}", reasoning={})
    async def fake_combine(outputs, criteria, settings, *, artifact_type, deliberations=None):
        return JudgeOutput(scores={"coverage": 7}, asi="SYNTH", reasoning={})
    monkeypatch.setattr(judge_board, "relay_panelist", fake_panelist)
    monkeypatch.setattr(judge_board, "combine_outputs", fake_combine)
    monkeypatch.setattr(judge_board, "relay_deliberate",
                        AsyncMock(return_value=("coverage_hawk", "delib")))
    s = _settings(); s.judge_samples = 2; s.judge_deliberate = False
    judge = judge_board.make_board_judge(panel, s, judge_mode_unused=None)
    out = await judge("cand", "ev", {"coverage": "..."}, s, iteration=1)
    # 2 lenses × K=2 samples = 4 panelist calls; combine returns the consensus
    assert len(panelist_calls) == 4 and out.asi == "SYNTH"

@pytest.mark.asyncio
async def test_board_judge_deliberation_only_when_panel_ge_2(monkeypatch):
    from simmer_sdk.types import JudgeDefinition
    async def fake_panelist(jd, *a, **k):
        return jd.name, "raw", JudgeOutput(scores={"c": 5}, asi="x", reasoning={})
    async def fake_combine(outputs, *a, **k): return JudgeOutput(scores={"c": 5}, asi="y", reasoning={})
    delib = AsyncMock(return_value=("n", "d"))
    monkeypatch.setattr(judge_board, "relay_panelist", fake_panelist)
    monkeypatch.setattr(judge_board, "combine_outputs", fake_combine)
    monkeypatch.setattr(judge_board, "relay_deliberate", delib)
    # single lens, deliberate=True → deliberation must NOT run (nothing to deliberate against)
    s = _settings(); s.judge_samples = 1; s.judge_deliberate = True
    judge = judge_board.make_board_judge([JudgeDefinition(name="coverage_hawk", lens="...")], s)
    await judge("c", "ev", {"c": "..."}, s, iteration=0)
    delib.assert_not_called()

@pytest.mark.asyncio
async def test_self_consistency_uses_relay_judge_K_times(monkeypatch):
    # empty panel + K>1 → self-consistency over the existing relay_judge
    rj = AsyncMock(side_effect=[JudgeOutput(scores={"c": c}, asi=f"a{c}", reasoning={}) for c in (5, 7, 6)])
    async def fake_combine(outputs, *a, **k):
        return JudgeOutput(scores=judge_board.compute_consensus_scores([o[2].scores for o in outputs]),
                           asi="SYNTH", reasoning={})
    monkeypatch.setattr(judge_board, "relay_judge", rj)
    monkeypatch.setattr(judge_board, "combine_outputs", fake_combine)
    s = _settings(); s.judge_samples = 3
    judge = judge_board.make_board_judge([], s)    # empty panel = self-consistency
    out = await judge("c", "ev", {"c": "..."}, s, iteration=0)
    assert rj.await_count == 3 and out.scores == {"c": 6}   # median of 5,7,6
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd worker && python -m pytest tests/test_judge_board.py -k "board_judge or self_consistency" -v`
Expected: FAIL — no `make_board_judge` / `relay_deliberate`.

- [ ] **Step 3: Implement `relay_deliberate` + `make_board_judge`**

Add to `judge_board.py`:
```python
async def relay_deliberate(name, own_output, other_outputs, settings):
    """One deliberation round for one judge — bounded relay call. Returns (name, text)."""
    relay = Relay.from_settings(settings)
    prompt = (NON_AGENTIC_JUDGE_PREAMBLE + "\n\n"
              + build_deliberation_prompt(judge_name=name, own_output=own_output,
                                          other_outputs=other_outputs))
    resp = await relay.complete(model=settings.classification_model, max_tokens=2048,
                                messages=[{"role": "user", "content": prompt}])
    return name, resp.text


def make_board_judge(panel, settings, *, judge_mode_unused=None):
    """Return a judge_fn (relay_judge-compatible signature) that runs the board.

    panel == []  → SELF-CONSISTENCY: run relay_judge K times (no lens), combine.
    panel != []  → BOARD: each lens × K samples via relay_panelist; optional one deliberation
                   round when len(panel) >= 2 and settings.judge_deliberate; then combine.
    Always returns a JudgeOutput (drop-in for the loop). Context discipline: the synthesized ASI
    is the only thing combine surfaces forward; per-panelist scores never leave this function.
    """
    K = max(1, int(settings.judge_samples))

    async def judge_fn(candidate, evidence, criteria, _settings, *, iteration=0,
                       evaluator_output=None, seed_candidate=None, seed_scores=None,
                       problem_class="text/creative"):
        outputs = []  # list[(name, raw, JudgeOutput)]
        if not panel:
            for k in range(K):
                jo = await relay_judge(candidate, evidence, criteria, settings,
                                       iteration=iteration, evaluator_output=evaluator_output,
                                       seed_candidate=seed_candidate, seed_scores=seed_scores,
                                       problem_class=problem_class)
                outputs.append((f"sample-{k+1}", jo.raw_text or "", jo))
        else:
            for jd in panel:
                for _k in range(K):
                    outputs.append(await relay_panelist(
                        jd, candidate, evidence, criteria, settings, iteration=iteration,
                        evaluator_output=evaluator_output, seed_candidate=seed_candidate,
                        seed_scores=seed_scores, problem_class=problem_class))

        deliberations = []
        if len(panel) >= 2 and getattr(settings, "judge_deliberate", True):
            # one round: each judge sees the others' raw scores (not ASI)
            by_name = {}
            for name, raw, _ in outputs:
                by_name.setdefault(name, raw)   # first sample's text per lens
            for name, own in by_name.items():
                others = [(n, t) for n, t in by_name.items() if n != name]
                deliberations.append(await relay_deliberate(name, own, others, settings))

        return await combine_outputs(outputs, criteria, settings,
                                     artifact_type="text", deliberations=deliberations)

    return judge_fn
```

Note: `relay_judge` populates `JudgeOutput.raw_text`? If not, self-consistency synthesis loses the raw text. Verify `parse_judge_output` sets `raw_text`; if it doesn't, set it in `relay_judge`/`relay_panelist` (`out.raw_text = resp.text`) — add that one line where needed.

- [ ] **Step 4: Run to verify pass + full board file**

Run: `cd worker && python -m pytest tests/test_judge_board.py -v`
Expected: PASS (all board tests).

- [ ] **Step 5: Commit**

```bash
git add worker/src/jobs/judge_board.py worker/tests/test_judge_board.py
git commit -m "feat(simmer): make_board_judge — score×K, gated deliberation, self-consistency, combine"
```

---

### Task 7: Wire the board into `simmer_general` (resolve once, inject)

**Files:**
- Modify: `worker/src/jobs/simmer_general.py`
- Modify: `worker/tests/test_judge_board.py` (add wiring tests) or a new `worker/tests/test_simmer_wiring.py`

- [ ] **Step 1: Write the failing tests** (new file `worker/tests/test_simmer_wiring.py`)

```python
import types, pytest
from unittest.mock import AsyncMock, patch
from src.jobs import simmer_general

def _s(**kw):
    base = dict(classification_model="m", extraction_model="e",
               judge_count=1, judge_samples=1, judge_panel="auto", judge_deliberate=True)
    base.update(kw); return types.SimpleNamespace(**base)

@pytest.mark.asyncio
async def test_resolve_judge_fn_floor_is_none(monkeypatch):
    # N=1, K=1 → None (loop uses default relay_judge) + mode relay-judge
    fn, mode = await simmer_general._resolve_judge_fn(_s(), {"c": "..."}, "seed", "text/creative")
    assert fn is None and mode == "relay-judge"

@pytest.mark.asyncio
async def test_resolve_judge_fn_board_when_n_ge_2(monkeypatch):
    called = {}
    async def fake_resolve(settings, criteria, candidate, *, problem_class):
        called["resolved"] = True; return [object(), object()]
    monkeypatch.setattr(simmer_general.judge_board, "resolve_panel", fake_resolve)
    monkeypatch.setattr(simmer_general.judge_board, "make_board_judge", lambda panel, s: "BOARD_FN")
    fn, mode = await simmer_general._resolve_judge_fn(_s(judge_count=2), {"c": "..."}, "seed", "text/creative")
    assert fn == "BOARD_FN" and mode == "relay-board" and called["resolved"]

@pytest.mark.asyncio
async def test_resolve_judge_fn_self_consistency_when_k_gt_1(monkeypatch):
    # N=1, K=3 → board judge with EMPTY panel (self-consistency), no composer call
    monkeypatch.setattr(simmer_general.judge_board, "make_board_judge", lambda panel, s: ("FN", panel))
    resolve = AsyncMock()
    monkeypatch.setattr(simmer_general.judge_board, "resolve_panel", resolve)
    fn, mode = await simmer_general._resolve_judge_fn(_s(judge_samples=3), {"c": "..."}, "seed", "text/creative")
    assert fn[1] == [] and mode == "relay-board"   # empty panel
    resolve.assert_not_awaited()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd worker && python -m pytest tests/test_simmer_wiring.py -v`
Expected: FAIL — no `_resolve_judge_fn` / `judge_board` not imported in simmer_general.

- [ ] **Step 3: Implement `_resolve_judge_fn` and pass it into both loops**

In `simmer_general.py`, add import near the top:
```python
from . import judge_board
```
Add the helper:
```python
async def _resolve_judge_fn(settings, criteria, seed_candidate, problem_class):
    """Decide the judge for this run (O3 — resolve once). Returns (judge_fn, judge_mode).
    Floor (N=1, K=1) → (None, 'relay-judge') so the loop uses the unchanged relay_judge.
    K>1 with N=1   → self-consistency: board judge over an EMPTY panel (no composer call).
    N>=2           → resolve the lens panel once, then a board judge."""
    n = max(1, int(getattr(settings, "judge_count", 1)))
    k = max(1, int(getattr(settings, "judge_samples", 1)))
    if n == 1 and k == 1:
        return None, "relay-judge"
    if n == 1:   # self-consistency only
        return judge_board.make_board_judge([], settings), "relay-board"
    panel = await judge_board.resolve_panel(settings, criteria, seed_candidate,
                                            problem_class=problem_class)
    return judge_board.make_board_judge(panel, settings), "relay-board"
```
In `_build_golden_set_judged`, after building `seed` and `criteria`, before calling `simmer_loop`:
```python
    judge_fn, judge_mode = await _resolve_judge_fn(settings, criteria, seed, "text/creative")
    best_golden, _ = await simmer_loop(
        phase="golden_set", job_id=job_id, db_path=db_path, settings=settings,
        criteria=criteria, iterations=iterations, seed_candidate=seed,
        generate_fn=generate_fn, evidence=evidence, evaluator_fn=None,
        judge_fn=judge_fn, judge_mode=judge_mode)
```
In `_refine_spec_rules`, similarly, before the `return await simmer_loop(...)`:
```python
    judge_fn, judge_mode = await _resolve_judge_fn(settings, criteria, seed, "pipeline/engineering")
    return await simmer_loop(
        phase="extraction_spec", job_id=job_id, db_path=db_path, settings=settings,
        criteria=criteria, iterations=iterations, seed_candidate=seed,
        generate_fn=generate_fn, evidence=golden_md[:12000], evaluator_fn=evaluator_fn,
        problem_class="pipeline/engineering", judge_fn=judge_fn, judge_mode=judge_mode)
```

- [ ] **Step 4: Run to verify pass + the whole worker suite**

Run: `cd worker && python -m pytest tests/ -v`
Expected: PASS — wiring tests pass; **all pre-existing simmer tests still pass** (floor unchanged because N=1/K=1 → judge_fn None).

- [ ] **Step 5: Commit**

```bash
git add worker/src/jobs/simmer_general.py worker/tests/test_simmer_wiring.py
git commit -m "feat(simmer): resolve judge_fn once per run and inject into golden + spec loops"
```

---

### Task 8: Matrix harness script (manual, real-model)

**Files:**
- Create: `scripts/judge_matrix.py`

This is operator tooling, not a unit test. It runs a real simmer phase over fixed inputs across a
config matrix and prints a comparison table. Keep it dependency-light and runnable from the repo root.

- [ ] **Step 1: Write the script**

```python
# scripts/judge_matrix.py
# ABOUTME: Sweep the simmer judge across (N, K, panel) on FIXED inputs and report
# ABOUTME: F1 trajectory / score variance / call-count / wall-clock per config cell.
#
# Layer-2a harness from the design doc. Forks the SAME seed into each cell so behavior is
# comparable. Reads sample chunks from a fixed dir; runs the spec phase (which has the free,
# non-circular F1 signal). Usage:
#   python scripts/judge_matrix.py --chunks <dir> --iterations 3 --cells "1x1,1x3,2x1"
import argparse, asyncio, json, time, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent / "worker"))

async def run_cell(n, k, panel, chunks, iterations):
    import os
    os.environ["JUDGE_COUNT"] = str(n); os.environ["JUDGE_SAMPLES"] = str(k)
    os.environ["JUDGE_PANEL"] = panel
    from src.config import get_settings
    from src.jobs.simmer_general import _refine_spec_rules
    # ... build a fixed golden + sample_chunks from `chunks`, call _refine_spec_rules,
    # capturing per-iteration F1 from the recorded simmer_iterations rows + wall-clock + call count.
    # (Implementer: reuse the same chunk-loading the job handlers use; write rows to a temp DB.)
    raise NotImplementedError  # fill during execution against the real chunk-loading path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", required=True)
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--cells", default="1x1,1x3,2x1")
    ap.add_argument("--panel", default="auto")
    args = ap.parse_args()
    rows = []
    for cell in args.cells.split(","):
        n, k = (int(x) for x in cell.lower().split("x"))
        t0 = time.time()
        result = asyncio.run(run_cell(n, k, args.panel, args.chunks, args.iterations))
        rows.append({"cell": cell, "elapsed_s": round(time.time() - t0, 1), **(result or {})})
    print(json.dumps(rows, indent=2))

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Wire `run_cell` to the real chunk-loading path**

During execution, fill `run_cell` using the same chunk-loading the job handlers use (see
`run_simmer_general` reading `chunks`), write iterations to a temp SQLite via `init_db`, and read
back `composite` / `scores` per iteration plus the printed F1 lines. Add a call-count tap (wrap
`Relay.complete`) so the table reports calls per cell.

- [ ] **Step 3: Smoke it (cloud/Sonnet first — cheap)**

Run (example): `ANTHROPIC_BACKEND=gateway python scripts/judge_matrix.py --chunks <fixed_dir> --cells "1x1,2x1" --iterations 2`
Expected: a JSON table with one row per cell, each showing elapsed_s, calls, and an F1 trajectory.

- [ ] **Step 4: Commit**

```bash
git add scripts/judge_matrix.py
git commit -m "feat(simmer): judge_matrix harness — sweep N×K over fixed inputs, report F1/variance/cost"
```

---

### Task 9: Full verification + cloud smoke

- [ ] **Step 1: Full worker suite green**

Run: `cd worker && python -m pytest tests/ -v`
Expected: ALL pass, including the unchanged pre-existing simmer tests (floor regression guard).

- [ ] **Step 2: Cloud/Sonnet end-to-end smoke (real `JudgeOutput` from the board)**

Set `JUDGE_COUNT=2 JUDGE_PANEL=coverage_hawk,precision_hawk` (fixed panel — isolate from composer)
and run one spec-phase iteration through `judge_matrix.py` (or a tiny driver). Confirm the board
returns a valid consensus `JudgeOutput` (non-empty scores + ASI) and the loop records `relay-board`.

- [ ] **Step 3: Behavioral run on gemma4 (Layer 2a — start cheap)**

`JUDGE_COUNT=1 JUDGE_SAMPLES=3` vs floor; then `JUDGE_COUNT=2 JUDGE_PANEL=...` (fixed). Watch the
F1 trajectory (spec phase), wall-clock, call count, and whether ASIs look sharper / scores steadier.
Do NOT declare a winner from self-reported scores (see spec §6 caveat) — that's Layer 2b.

- [ ] **Step 4: Final commit / PR prep**

```bash
git add -A && git commit -m "test(simmer): verify board end-to-end; floor unchanged"
```

---

## Done When
- All worker tests pass, including the unchanged pre-existing simmer suite.
- `JUDGE_COUNT=1 JUDGE_SAMPLES=1` provably routes to today's `relay_judge` (judge_fn is None).
- `N≥2` (board) and `N=1/K>1` (self-consistency) both produce a valid consensus `JudgeOutput`, record `relay-board`, and never leak per-panelist scores/evaluator output to the generator.
- `judge_matrix.py` produces a per-cell comparison table on real models.

## Deferred (not in v1, per spec)
- Per-panelist persistence (column/side-table) — log-only for now (O4).
- Trusted frozen reference set + repeated-run variance study + kill-bar (Layer 2b) — only if Layer 2a is promising.
- Board for the image pipeline (`simmer_domain_image.py`) — out of scope.
- Adaptive per-iteration composition — v1 composes once per run (O3).
