from __future__ import annotations

import os
from typing import Any, Dict

from .kronos_dataset import build_kronos_dataset
from .kronos_model import KronosModel, artifact_path, fit_logistic_artifact, load_artifact, save_artifact

SUPPORTED_INDEXES = {"000688.SH", "000852.SH"}


def _enabled() -> bool:
    return str(os.environ.get("ENABLE_KRONOS_SIX_INDEX", "1")).strip().lower() in {"1", "true", "yes", "on"}


def _ensure_artifact(index_code: str):
    path = artifact_path(index_code)
    if path.exists():
        return load_artifact(index_code), path, False
    dataset = build_kronos_dataset(index_code.split(".")[0])
    if dataset.sample_count < 80:
        raise RuntimeError("kronos_training_data_insufficient")
    artifact = fit_logistic_artifact(index_code, dataset.feature_names, dataset.X, dataset.y)
    save_path = save_artifact(artifact)
    return artifact, save_path, True


def load_kronos_signal(index_code: str, feature_payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if index_code not in SUPPORTED_INDEXES:
        return {
            "kronos_available": False,
            "kronos_score": None,
            "model_family": "rule_v1",
            "degraded_reason": None,
            "debug": {"index_code": index_code, "mode": "unsupported"},
        }
    if not _enabled():
        return {
            "kronos_available": False,
            "kronos_score": None,
            "model_family": "rule_v1",
            "degraded_reason": None,
            "debug": {"index_code": index_code, "mode": "disabled"},
        }
    try:
        artifact, path, trained_now = _ensure_artifact(index_code)
        dataset = build_kronos_dataset(index_code.split(".")[0])
        model = KronosModel(artifact)
        pred = model.score(dataset.latest_features)
        return {
            "kronos_available": True,
            "kronos_score": pred["kronos_score"],
            "model_family": artifact.version,
            "degraded_reason": None,
            "debug": {
                "index_code": index_code,
                "artifact_path": str(path),
                "trained_now": trained_now,
                "sample_count": artifact.sample_count,
                "train_accuracy": artifact.train_accuracy,
                "probability_up": pred["probability_up"],
            },
        }
    except Exception as exc:
        reason = f"kronos_runtime_failed:{type(exc).__name__}"
        if "insufficient" in str(exc):
            reason = "kronos_training_data_insufficient"
        return {
            "kronos_available": False,
            "kronos_score": None,
            "model_family": "rule_v1",
            "degraded_reason": reason,
            "debug": {"index_code": index_code, "mode": "runtime_failed", "error": str(exc)},
        }


def train_and_persist_kronos(index_code: str) -> Dict[str, Any]:
    artifact, path, trained_now = _ensure_artifact(index_code)
    return {
        "index_code": index_code,
        "artifact_path": str(path),
        "trained_now": trained_now,
        "sample_count": artifact.sample_count,
        "train_accuracy": artifact.train_accuracy,
        "version": artifact.version,
    }
