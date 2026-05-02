from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
from scipy.optimize import minimize


MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "kronos"


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


@dataclass(frozen=True)
class KronosArtifact:
    symbol: str
    feature_names: List[str]
    mean: List[float]
    std: List[float]
    weights: List[float]
    bias: float
    sample_count: int
    train_accuracy: float
    version: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "symbol": self.symbol,
            "feature_names": self.feature_names,
            "mean": self.mean,
            "std": self.std,
            "weights": self.weights,
            "bias": self.bias,
            "sample_count": self.sample_count,
            "train_accuracy": self.train_accuracy,
            "version": self.version,
        }


class KronosModel:
    def __init__(self, artifact: KronosArtifact) -> None:
        self.artifact = artifact
        self._mean = np.asarray(artifact.mean, dtype=float)
        self._std = np.asarray(artifact.std, dtype=float)
        self._weights = np.asarray(artifact.weights, dtype=float)
        self._bias = float(artifact.bias)

    def score(self, features: Dict[str, float]) -> Dict[str, float]:
        raw = np.asarray([float(features.get(name, 0.0)) for name in self.artifact.feature_names], dtype=float)
        norm = (raw - self._mean) / np.where(self._std == 0, 1.0, self._std)
        logit = float(np.dot(norm, self._weights) + self._bias)
        prob = float(_sigmoid(np.asarray([logit]))[0])
        score = (prob - 0.5) * 2.0
        return {"probability_up": round(prob, 6), "kronos_score": round(score, 6), "logit": round(logit, 6)}


def fit_logistic_artifact(symbol: str, feature_names: Iterable[str], X: np.ndarray, y: np.ndarray) -> KronosArtifact:
    names = list(feature_names)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std == 0, 1.0, std)
    Xn = (X - mean) / std

    def loss(params: np.ndarray) -> float:
        weights = params[:-1]
        bias = params[-1]
        logits = Xn @ weights + bias
        probs = _sigmoid(logits)
        ce = -(y * np.log(probs + 1e-9) + (1.0 - y) * np.log(1.0 - probs + 1e-9)).mean()
        l2 = 0.01 * np.square(weights).mean()
        return float(ce + l2)

    init = np.zeros(Xn.shape[1] + 1, dtype=float)
    res = minimize(loss, init, method="L-BFGS-B")
    params = res.x if res.success else init
    weights = params[:-1]
    bias = params[-1]
    probs = _sigmoid(Xn @ weights + bias)
    preds = (probs >= 0.5).astype(float)
    acc = float((preds == y).mean()) if len(y) else 0.0
    return KronosArtifact(
        symbol=symbol,
        feature_names=names,
        mean=[round(float(x), 10) for x in mean.tolist()],
        std=[round(float(x), 10) for x in std.tolist()],
        weights=[round(float(x), 10) for x in weights.tolist()],
        bias=round(float(bias), 10),
        sample_count=int(len(y)),
        train_accuracy=round(acc, 6),
        version="kronos_local_logit_v1",
    )


def artifact_path(symbol: str) -> Path:
    safe = symbol.replace(".", "_")
    return MODEL_DIR / f"{safe}.json"


def save_artifact(artifact: KronosArtifact) -> Path:
    path = artifact_path(artifact.symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_artifact(symbol: str) -> KronosArtifact:
    path = artifact_path(symbol)
    data = json.loads(path.read_text(encoding="utf-8"))
    return KronosArtifact(
        symbol=str(data["symbol"]),
        feature_names=list(data["feature_names"]),
        mean=list(data["mean"]),
        std=list(data["std"]),
        weights=list(data["weights"]),
        bias=float(data["bias"]),
        sample_count=int(data["sample_count"]),
        train_accuracy=float(data["train_accuracy"]),
        version=str(data["version"]),
    )
