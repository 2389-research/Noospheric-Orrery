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
    assert result.asi  # non-empty: fell back to a panelist ASI targeting the weakest criterion (coverage)
