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
