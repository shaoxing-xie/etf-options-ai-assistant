import os

from plugins.analysis.predictors import kronos_enhancer


def test_load_kronos_signal_disabled_is_not_degraded(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_KRONOS_SIX_INDEX", "0")

    out = kronos_enhancer.load_kronos_signal("000688.SH", {})

    assert out["kronos_available"] is False
    assert out["degraded_reason"] is None
    assert out["model_family"] == "rule_v1"


def test_load_kronos_signal_runtime_failure_degrades(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_KRONOS_SIX_INDEX", "1")

    def _boom(index_code: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(kronos_enhancer, "_ensure_artifact", _boom)
    out = kronos_enhancer.load_kronos_signal("000852.SH", {})

    assert out["kronos_available"] is False
    assert "kronos_runtime_failed" in str(out["degraded_reason"])


def test_load_kronos_signal_success(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_KRONOS_SIX_INDEX", "1")

    class _Dataset:
        feature_names = ("ret1",)
        sample_count = 100
        X = None
        y = None
        latest_features = {"ret1": 0.1}

    class _Model:
        def __init__(self, artifact):
            self.artifact = artifact

        def score(self, features):
            return {"probability_up": 0.61, "kronos_score": 0.22, "logit": 0.44}

    class _Artifact:
        version = "kronos_local_logit_v1"
        sample_count = 123
        train_accuracy = 0.58

    monkeypatch.setattr(kronos_enhancer, "_ensure_artifact", lambda index_code: (_Artifact(), "/tmp/a.json", False))
    monkeypatch.setattr(kronos_enhancer, "build_kronos_dataset", lambda symbol: _Dataset())
    monkeypatch.setattr(kronos_enhancer, "KronosModel", _Model)

    out = kronos_enhancer.load_kronos_signal("000688.SH", {})

    assert out["kronos_available"] is True
    assert out["kronos_score"] == 0.22
    assert out["degraded_reason"] is None
