import importlib
import os

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


# --- the judge's own settings ------------------------------------------------

def test_judge_settings_default_to_advise_not_apply(monkeypatch):
    """`advise` by default: the judge writes verdicts, a human still resolves.

    Defaulting to `apply` would let a model auto-resolve entries in a graph the moment
    this ships, with no one having opted in.
    """
    for k in list(os.environ):
        if k.startswith("NORMALIZATION_JUDGE"):
            monkeypatch.delenv(k, raising=False)
    s = config_mod.get_settings()
    assert s.normalization_judge_mode == "advise"
    assert s.normalization_judge_prefer_local is True
    assert s.normalization_judge_model == ""          # empty -> extraction_model
    assert s.normalization_judge_max_attempts == 3


def test_the_judge_temperature_is_not_zero(monkeypatch):
    """Greedy decoding loops on a bad generation and never terminates.

    Pinned as a test because 0.0 is the obvious-looking value for a deterministic task,
    and the failure it causes (a hung sweep) looks nothing like a temperature problem.
    """
    monkeypatch.delenv("NORMALIZATION_JUDGE_TEMPERATURE", raising=False)
    assert config_mod.get_settings().normalization_judge_temperature > 0


def test_judge_settings_are_env_overridable(monkeypatch):
    monkeypatch.setenv("NORMALIZATION_JUDGE_MODE", "off")
    monkeypatch.setenv("NORMALIZATION_JUDGE_BATCH", "3")
    monkeypatch.setenv("NORMALIZATION_JUDGE_MIN_CONFIDENCE", "0.9")
    monkeypatch.setenv("NORMALIZATION_JUDGE_PREFER_LOCAL", "false")
    s = config_mod.get_settings()
    assert s.normalization_judge_mode == "off"
    assert s.normalization_judge_batch == 3
    assert s.normalization_judge_min_confidence == 0.9
    assert s.normalization_judge_prefer_local is False
