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
    outs = [
        ("Judge A", "raw a", JudgeOutput(scores={"coverage": 3, "precision": 9}, asi="fix-coverage", reasoning={})),
        ("Judge B", "raw b", JudgeOutput(scores={"coverage": 4, "precision": 8}, asi="fix-precision", reasoning={})),
    ]
    relay = types.SimpleNamespace(complete=AsyncMock(return_value=types.SimpleNamespace(text="(no asi here)")))
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        result = await judge_board.combine_outputs(
            outs, criteria={"coverage": "...", "precision": "..."}, settings=_settings(),
            artifact_type="text", deliberations=[])
    assert result.asi == "fix-coverage"  # fell back to the panelist ASI targeting the weakest criterion (coverage)

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
async def test_resolve_panel_auto_tolerates_messy_model_formatting():
    s = _settings(); s.judge_panel = "auto"; s.judge_count = 2
    relay = types.SimpleNamespace(complete=AsyncMock(
        return_value=types.SimpleNamespace(text="- precision_hawk\ntaxonomy_purist: for taxonomy\n3. bogus")))
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        panel = await judge_board.resolve_panel(s, criteria={"precision": "..."},
                                                candidate="c", problem_class="text/creative")
    assert [j.name for j in panel] == ["precision_hawk", "taxonomy_purist"]

@pytest.mark.asyncio
async def test_resolve_panel_falls_back_to_default_on_composer_garbage():
    s = _settings(); s.judge_panel = "auto"; s.judge_count = 2
    relay = types.SimpleNamespace(complete=AsyncMock(
        return_value=types.SimpleNamespace(text="no valid names here")))
    with patch.object(judge_board.Relay, "from_settings", return_value=relay):
        panel = await judge_board.resolve_panel(s, criteria={"x": "..."},
                                                candidate="c", problem_class="text/creative")
    assert [j.name for j in panel] == judge_board.DEFAULT_PANEL[:2]

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
    judge = judge_board.make_board_judge(panel, s)
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
