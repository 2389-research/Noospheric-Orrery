# ABOUTME: Structural tests for the simmer framework — lock in the generator/judge/ASI/reflect
# ABOUTME: building blocks so a future change can't silently drop a role (as #27 did to the judge).
#
# These enforce the invariants listed in CLAUDE.md "Simmer pipeline — READ THE THEORY BEFORE
# TOUCHING IT". If you're changing the pipeline shape and one of these goes red, that is the
# point — read the rationale (CLAUDE.md + simmer-sdk/docs/spec.md) before "fixing" the test.

import json
import types
import pytest
from unittest.mock import AsyncMock, patch

from simmer_sdk import JudgeOutput

from src.db import init_db, get_connection
from src.jobs import simmer_core
from src.jobs.simmer_core import relay_judge, simmer_loop, _record_judged_iteration


def _job(db_path, job_id="j1"):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO jobs (id, type, target, status) VALUES (?, 'simmer_domain', 't', 'running')", (job_id,))
    conn.commit()
    conn.close()


def _iters(db_path, job_id="j1", phase="golden_set"):
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT iteration, scores, composite, asi, judge_mode, regressed FROM simmer_iterations "
        "WHERE job_id=? AND phase=? ORDER BY iteration", (job_id, phase)).fetchall()
    conn.close()
    return rows


def _settings():
    return types.SimpleNamespace(classification_model="m", extraction_model="e")


# ── The framework must expose its building blocks ──────────────────────────

def test_building_blocks_exist():
    # Generator is caller-supplied; the framework owns judge + loop + recorder.
    assert callable(simmer_core.relay_judge)        # judge
    assert callable(simmer_core.simmer_loop)        # generate→evaluate→judge→reflect loop
    assert callable(simmer_core._record_judged_iteration)  # artifact recording


# ── Judge: produces scores + ASI, in the simmer-sdk format ─────────────────

@pytest.mark.asyncio
async def test_relay_judge_returns_scores_and_asi():
    text = (
        "ITERATION 0 SCORES:\n"
        "  coverage: 7/10 — solid — add more\n"
        "  precision: 8/10 — good — tighten\n"
        "COMPOSITE: 7.5/10\n\n"
        "ASI (highest-leverage direction):\nAdd an EXCLUDE rule for vague descriptors."
    )
    relay = types.SimpleNamespace(complete=AsyncMock(return_value=types.SimpleNamespace(text=text)))
    with patch.object(simmer_core.Relay, "from_settings", return_value=relay):
        out = await relay_judge("cand", "evidence", {"coverage": "...", "precision": "..."}, _settings())
    assert out.scores == {"coverage": 7, "precision": 8}
    assert out.asi and "EXCLUDE rule" in out.asi


@pytest.mark.asyncio
async def test_relay_judge_strips_leaked_asi_header():
    # Underscore variant defeats the parser's precise pattern → fallback grabs the header line.
    text = (
        "COMPOSITE: 7.0/10\n"
        "ASI (highest-leverage_direction):\nDo the specific thing."
    )
    relay = types.SimpleNamespace(complete=AsyncMock(return_value=types.SimpleNamespace(text=text)))
    with patch.object(simmer_core.Relay, "from_settings", return_value=relay):
        out = await relay_judge("cand", "evidence", {"coverage": "..."}, _settings())
    assert not out.asi.lower().startswith("asi")
    assert out.asi == "Do the specific thing."


# ── Loop: generate → judge → reflect, and records every iteration ──────────

@pytest.mark.asyncio
async def test_loop_runs_generate_judge_reflect_and_records(test_db):
    _job(test_db)
    gen_calls = []

    async def generate_fn(candidate, asi):
        gen_calls.append((candidate, asi))
        return f"candidate-after-{len(gen_calls)}"

    judgments = [
        JudgeOutput(scores={"coverage": 6}, asi="asi-0", reasoning={"coverage": "r0"}),
        JudgeOutput(scores={"coverage": 8}, asi="asi-1", reasoning={"coverage": "r1"}),
        JudgeOutput(scores={"coverage": 7}, asi="asi-2", reasoning={"coverage": "r2"}),
    ]
    with patch.object(simmer_core, "relay_judge", new=AsyncMock(side_effect=judgments)) as mock_judge:
        best, comp = await simmer_loop(
            phase="golden_set", job_id="j1", db_path=test_db, settings=_settings(),
            criteria={"coverage": "..."}, iterations=2, seed_candidate="seed",
            generate_fn=generate_fn, evidence="ev")

    # judge every iteration (0,1,2); generate only BETWEEN iterations (after 0 and 1, not after last)
    assert mock_judge.await_count == 3
    assert len(gen_calls) == 2
    # all three iterations recorded with real scores + asi + composite (a judge ran)
    rows = _iters(test_db)
    assert len(rows) == 3
    for it, scores, composite, asi, judge_mode, _ in rows:
        assert json.loads(scores) != {}
        assert composite is not None
        assert asi.startswith("asi-")
        assert judge_mode == "relay-judge"
    # criterion_details recorded per iteration
    conn = get_connection(test_db)
    n_details = conn.execute("SELECT COUNT(*) FROM simmer_criterion_details").fetchone()[0]
    conn.close()
    assert n_details == 3


@pytest.mark.asyncio
async def test_loop_context_discipline_generator_gets_asi_not_scores_or_eval(test_db):
    _job(test_db)
    gen_calls = []

    async def generate_fn(candidate, asi):
        gen_calls.append((candidate, asi))
        return "next"

    async def evaluator_fn(candidate):
        return "EVAL_SENTINEL_must_not_reach_generator"

    judgments = [JudgeOutput(scores={"coverage": 5}, asi="THE_ASI", reasoning={}) for _ in range(2)]
    with patch.object(simmer_core, "relay_judge", new=AsyncMock(side_effect=judgments)):
        await simmer_loop(
            phase="extraction_spec", job_id="j1", db_path=test_db, settings=_settings(),
            criteria={"coverage": "..."}, iterations=1, seed_candidate="seed",
            generate_fn=generate_fn, evidence="ev", evaluator_fn=evaluator_fn,
            problem_class="pipeline/engineering")

    assert len(gen_calls) == 1
    cand_arg, asi_arg = gen_calls[0]
    assert asi_arg == "THE_ASI"                       # generator IS steered by the ASI
    # generator must NOT receive scores or evaluator output
    assert "EVAL_SENTINEL" not in cand_arg and "EVAL_SENTINEL" not in asi_arg
    assert "coverage" not in asi_arg


@pytest.mark.asyncio
async def test_loop_evaluator_feeds_the_judge(test_db):
    _job(test_db)

    async def generate_fn(candidate, asi):
        return "next"

    async def evaluator_fn(candidate):
        return "EVAL_SENTINEL"

    mock_judge = AsyncMock(side_effect=[JudgeOutput(scores={"coverage": 5}, asi="a", reasoning={}) for _ in range(2)])
    with patch.object(simmer_core, "relay_judge", new=mock_judge):
        await simmer_loop(
            phase="extraction_spec", job_id="j1", db_path=test_db, settings=_settings(),
            criteria={"coverage": "..."}, iterations=1, seed_candidate="seed",
            generate_fn=generate_fn, evidence="ev", evaluator_fn=evaluator_fn,
            problem_class="pipeline/engineering")
    # the evaluator output is handed to the judge (not the generator)
    assert mock_judge.await_args_list[0].kwargs["evaluator_output"] == "EVAL_SENTINEL"


@pytest.mark.asyncio
async def test_loop_calibration_passes_seed_for_later_iterations(test_db):
    _job(test_db)

    async def generate_fn(candidate, asi):
        return "next"

    judgments = [JudgeOutput(scores={"coverage": c}, asi="a", reasoning={}) for c in (6, 8, 7)]
    mock_judge = AsyncMock(side_effect=judgments)
    with patch.object(simmer_core, "relay_judge", new=mock_judge):
        await simmer_loop(
            phase="golden_set", job_id="j1", db_path=test_db, settings=_settings(),
            criteria={"coverage": "..."}, iterations=2, seed_candidate="SEED",
            generate_fn=generate_fn, evidence="ev")
    calls = mock_judge.await_args_list
    # iteration 0: no calibration anchor yet
    assert calls[0].kwargs["seed_scores"] is None
    # iteration 1+: seed candidate + iteration-0 scores are the calibration reference
    assert calls[1].kwargs["seed_candidate"] == "SEED"
    assert calls[1].kwargs["seed_scores"] == {"coverage": 6}
    assert calls[2].kwargs["seed_scores"] == {"coverage": 6}


@pytest.mark.asyncio
async def test_loop_keeps_best_and_flags_regression(test_db):
    _job(test_db)

    async def generate_fn(candidate, asi):
        return f"c{len(asi)}"  # distinct candidate each round

    # composites 8 → 5 → 7: best is iteration 0; iteration 1 regressed
    judgments = [JudgeOutput(scores={"coverage": c}, asi="x" * (i + 1), reasoning={})
                 for i, c in enumerate((8, 5, 7))]
    with patch.object(simmer_core, "relay_judge", new=AsyncMock(side_effect=judgments)):
        best, comp = await simmer_loop(
            phase="golden_set", job_id="j1", db_path=test_db, settings=_settings(),
            criteria={"coverage": "..."}, iterations=2, seed_candidate="seed",
            generate_fn=generate_fn, evidence="ev")
    assert comp == 8.0
    assert best == "seed"   # iteration-0 candidate had the best composite
    rows = {it: bool(regressed) for it, _, _, _, _, regressed in _iters(test_db)}
    assert rows == {0: False, 1: True, 2: False}
