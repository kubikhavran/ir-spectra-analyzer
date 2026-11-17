"""Train the functional-group model shipped in ``storage/data/fg_model.v1.npz``.

Usage::

    pip install scikit-learn
    python tools/train_fg_model.py INDEX.json SPECTRA_DIR OUT.npz [--split dev|all]

``INDEX.json`` lists spectra with known structures: objects with ``file``
(a JCAMP-DX or SPA file inside ``SPECTRA_DIR``), ``smiles`` and ``phase``
(``condensed``, ``solution``, ``mull`` or ``gas``).

How the shipped model was made
------------------------------
* Spectra: the condensed-phase (KBr, film, neat liquid, split mull),
  solution and mull IR spectra of the NIST Chemistry WebBook (Coblentz Society
  collection). Gas-phase spectra were left out: they made the model worse on
  condensed samples. Mineral-oil mulls only teach the C-H bands of the oil and
  are used for training, never for judging.
* Structures: the compound names converted with OPSIN and kept only when the
  molecular formula of the structure equals the formula in the file.
* Labels: ``chemistry.functional_group_smarts`` — the same definitions the
  structure check uses.
* Model: three one-hidden-layer networks (256 units, ReLU, L2 1e-2) on the
  ``processing.fg_features`` vector, trained on the spectra plus two
  augmented copies (±1 bin shift, ±15 % scale, small noise); probabilities
  averaged.
* Thresholds: per group, the one with the best F1 on out-of-fold predictions
  for condensed-phase spectra (4-fold, grouped by compound). Groups with fewer
  than 8 condensed examples, or an out-of-fold F1 below 0.3, get no threshold
  and stay with the band-window rules.

``--split dev`` trains on the dev half only (see ``tools/fg_benchmark.py``) so
the test half can measure the result honestly; ``--split all`` makes the model
that ships.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

from fg_benchmark import compound_key, load_spectrum, split_of  # noqa: E402

from chemistry.functional_group_smarts import groups_in_smiles  # noqa: E402
from processing.fg_features import (  # noqa: E402
    BIN_WIDTH,
    GRID_MAX,
    GRID_MIN,
    N_FEATURES,
    spectrum_features,  # noqa: E402
)
from storage.functional_group_repository import FunctionalGroupRepository  # noqa: E402

TRAIN_PHASES = ("condensed", "solution", "mull")
HIDDEN = (256,)
MEMBERS = 3
ALPHA = 1e-2
AUGMENTED_COPIES = 2
MIN_POSITIVES = 8
MIN_CV_F1 = 0.3


def featurize(entries: list[dict], spectra_dir: Path) -> tuple[np.ndarray, list[dict]]:
    rows: list[np.ndarray] = []
    kept: list[dict] = []
    for entry in entries:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                features = spectrum_features(load_spectrum(spectra_dir / entry["file"]))
        except Exception:  # noqa: BLE001 - unreadable files are skipped
            continue
        if features is not None:
            rows.append(features.astype(np.float32))
            kept.append(entry)
    return np.stack(rows), kept


def labels(entries: list[dict], groups: list[str]) -> tuple[np.ndarray, np.ndarray]:
    y = np.zeros((len(entries), len(groups)), dtype=np.int8)
    known = np.ones_like(y, dtype=bool)
    for i, entry in enumerate(entries):
        truth = groups_in_smiles(entry["smiles"])
        for j, group in enumerate(groups):
            if truth is None or not truth.is_known(group):
                known[i, j] = False
            elif truth.has(group):
                y[i, j] = 1
    return y, known


def _augment(x: np.ndarray, y: np.ndarray, rng: np.random.Generator):
    xs, ys = [x], [y]
    for _ in range(AUGMENTED_COPIES):
        shifts = rng.integers(-1, 2, size=len(x))
        shifted = np.stack([np.roll(row, s) for row, s in zip(x, shifts, strict=True)])
        scaled = shifted * rng.uniform(0.85, 1.15, size=(len(x), 1))
        xs.append(np.clip(scaled + rng.normal(0.0, 0.02, shifted.shape), 0.0, 1.2))
        ys.append(y)
    return np.concatenate(xs), np.concatenate(ys)


def _fit(x: np.ndarray, y: np.ndarray, rng: np.random.Generator) -> list:
    from sklearn.neural_network import MLPClassifier

    nets = []
    for seed in range(MEMBERS):
        xa, ya = _augment(x, y, rng)
        net = MLPClassifier(hidden_layer_sizes=HIDDEN, alpha=ALPHA, max_iter=400, random_state=seed)
        nets.append(net.fit(xa, ya))
    return nets


def _predict(nets: list, x: np.ndarray) -> np.ndarray:
    return np.mean([net.predict_proba(x) for net in nets], axis=0)


def main(argv: list[str] | None = None) -> int:
    from sklearn.model_selection import GroupKFold

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("index", type=Path)
    parser.add_argument("spectra_dir", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--split", choices=("dev", "all"), default="all")
    args = parser.parse_args(argv)
    warnings.filterwarnings("ignore")

    entries = [
        e
        for e in json.loads(args.index.read_text(encoding="utf-8"))
        if e.get("phase") in TRAIN_PHASES and (args.split == "all" or split_of(e["file"]) == "dev")
    ]
    x, entries = featurize(entries, args.spectra_dir)
    groups = [g.id for g in FunctionalGroupRepository().load().groups]
    y, known = labels(entries, groups)
    phase = np.array([e["phase"] for e in entries])
    compounds = np.array([compound_key(e["file"]) for e in entries])
    rng = np.random.default_rng(0)

    oof = np.zeros(y.shape)
    for train, held in GroupKFold(4).split(x, y, compounds):
        oof[held] = _predict(_fit(x[train], y[train], rng), x[held])
    condensed = phase == "condensed"
    thresholds: list[float | None] = []
    cv_f1: list[float] = []
    positives: list[int] = []
    for j in range(len(groups)):
        mask = condensed & known[:, j]
        truth = y[mask, j] == 1
        positives.append(int(truth.sum()))
        best_f1, best_t = 0.0, None
        for t in np.linspace(0.05, 0.95, 37):
            predicted = oof[mask, j] >= t
            tp = int((predicted & truth).sum())
            fp = int((predicted & ~truth).sum())
            fn = int((~predicted & truth).sum())
            f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
            if f1 > best_f1:
                best_f1, best_t = f1, float(t)
        cv_f1.append(best_f1)
        usable = best_t is not None and positives[-1] >= MIN_POSITIVES and best_f1 >= MIN_CV_F1
        thresholds.append(best_t if usable else None)

    nets = _fit(x, y, rng)
    arrays: dict[str, np.ndarray] = {}
    for k, net in enumerate(nets):
        arrays[f"w1_{k}"] = net.coefs_[0].astype(np.float32)
        arrays[f"b1_{k}"] = net.intercepts_[0].astype(np.float32)
        arrays[f"w2_{k}"] = net.coefs_[1].astype(np.float32)
        arrays[f"b2_{k}"] = net.intercepts_[1].astype(np.float32)
    info = {
        "version": 1,
        "groups": groups,
        "thresholds": thresholds,
        "cv_f1": cv_f1,
        "positives": positives,
        "n_members": MEMBERS,
        "features": {
            "n": N_FEATURES,
            "grid_min": GRID_MIN,
            "grid_max": GRID_MAX,
            "bin_width": BIN_WIDTH,
        },
        "training": {
            "spectra": len(entries),
            "phases": list(TRAIN_PHASES),
            "split": args.split,
            "source": "NIST Chemistry WebBook condensed-phase/solution IR spectra "
            "(Coblentz Society collection); structures from names via OPSIN, "
            "checked against the molecular formula",
            "created": datetime.date.today().isoformat(),
        },
    }
    np.savez_compressed(args.out, info=np.array(json.dumps(info)), **arrays)
    modelled = sum(t is not None for t in thresholds)
    print(f"saved {args.out}: {len(entries)} spectra, {modelled} groups modelled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
