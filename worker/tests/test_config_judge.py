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
