"""Learned functional-group model: which groups a spectrum's shape points to.

The rule scoring alone looks into fixed windows and asks "is there a band
here". On real spectra of complex molecules almost every window holds
something, so it reported twice as many groups as a molecule has and was right
about one in seven (see ``tools/fg_benchmark.py``). This model was trained on
public condensed-phase reference spectra with known structures and reads the
whole spectrum at once, which is what an experienced spectroscopist does.

The model is a small ensemble of one-hidden-layer networks stored as plain
arrays in ``storage/data/fg_model.v1.npz`` and evaluated with numpy, so the
application needs no machine-learning library. Each group has its own decision
threshold, chosen on held-out spectra; groups with too few examples to learn
from have none, and for them the rule scoring stays in charge.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from core.spectrum import Spectrum
from processing.fg_features import N_FEATURES, spectrum_features

_DATA_RELATIVE = Path("storage") / "data" / "fg_model.v1.npz"


def _default_model_path() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass is not None:
        candidate = Path(meipass) / _DATA_RELATIVE
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[1] / _DATA_RELATIVE


@dataclass(frozen=True)
class GroupModel:
    """Loaded network ensemble plus the per-group thresholds."""

    groups: tuple[str, ...]
    thresholds: dict[str, float]
    layers: tuple[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], ...]
    info: dict

    def predict(self, features: np.ndarray) -> dict[str, float]:
        """Probability per group for one feature vector."""
        x = np.asarray(features, dtype=np.float32).reshape(1, -1)
        total = np.zeros(len(self.groups), dtype=np.float64)
        for w1, b1, w2, b2 in self.layers:
            hidden = np.maximum(x @ w1 + b1, 0.0)
            logits = (hidden @ w2 + b2).astype(np.float64).ravel()
            total += 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
        probabilities = total / max(len(self.layers), 1)
        return dict(zip(self.groups, (float(p) for p in probabilities), strict=True))

    def is_modelled(self, group_id: str) -> bool:
        return group_id in self.thresholds


@dataclass(frozen=True)
class GroupPrediction:
    probability: float
    threshold: float

    @property
    def score(self) -> float:
        """Probability on the panel's 0-100 scale, with the group's own
        threshold landing on 55 % — the level the panel calls "found"."""
        p, t = self.probability, self.threshold
        if p < t:
            value = 55.0 * p / max(t, 1e-6)
        else:
            value = 55.0 + 45.0 * (p - t) / max(1.0 - t, 1e-6)
        return round(float(np.clip(value, 0.0, 100.0)), 1)


@lru_cache(maxsize=2)
def load_model(path: Path | None = None) -> GroupModel | None:
    """The shipped model, or ``None`` when the file is missing or unreadable."""
    model_path = path or _default_model_path()
    try:
        with np.load(model_path, allow_pickle=False) as data:
            info = json.loads(str(data["info"]))
            members = int(info.get("n_members", 0))
            layers = tuple(
                (
                    data[f"w1_{k}"].astype(np.float32),
                    data[f"b1_{k}"].astype(np.float32),
                    data[f"w2_{k}"].astype(np.float32),
                    data[f"b2_{k}"].astype(np.float32),
                )
                for k in range(members)
            )
    except (OSError, KeyError, ValueError):
        return None
    if not layers or int(info.get("features", {}).get("n", -1)) != N_FEATURES:
        return None
    groups = tuple(info["groups"])
    thresholds = {
        group: float(threshold)
        for group, threshold in zip(groups, info["thresholds"], strict=True)
        if threshold is not None
    }
    return GroupModel(groups=groups, thresholds=thresholds, layers=layers, info=info)


def predict_groups(
    spectrum: Spectrum, model: GroupModel | None = None
) -> dict[str, GroupPrediction] | None:
    """Model verdict for every group it covers, or ``None`` when it cannot run."""
    model = model or load_model()
    if model is None:
        return None
    features = spectrum_features(spectrum)
    if features is None:
        return None
    probabilities = model.predict(features)
    return {
        group: GroupPrediction(probability=probabilities[group], threshold=threshold)
        for group, threshold in model.thresholds.items()
    }
