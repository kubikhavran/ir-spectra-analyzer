"""Measure the functional-group analysis on spectra whose structure is known.

Usage::

    python tools/fg_benchmark.py INDEX.json SPECTRA_DIR [--limit N] [--seed S]
                                 [--split dev|test|all] [--json OUT]

``INDEX.json`` is a list of objects with at least ``file`` (a JCAMP or SPA
file inside ``SPECTRA_DIR``) and ``smiles``. The ground truth for every
knowledge-base group comes from the structure (``chemistry.functional_group_smarts``);
the prediction is what the Functional Groups panel shows as found
(score >= ``--threshold``, 55 % by default, the panel's "confirmed" level).

The spectra themselves are not part of this repository: the tool was written
for a public set of condensed-phase NIST spectra (KBr, mull, film, neat liquid)
whose names were turned into structures with OPSIN and checked against the
molecular formula in each file. Any folder of spectra with structures works.

Reported, so that a change can be judged on real spectra and not on the
synthetic patterns that once misled the tuning:

* per spectrum: how many groups are reported, how many of them are right
  (precision) and how many of the structure's groups are found (recall);
* per group: precision, recall and F1 over the whole set;
* micro and macro averages.

The set is split deterministically by file name into a *dev* half used while
tuning and a *test* half to confirm a change did not just fit the dev half.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chemistry.functional_group_smarts import groups_in_smiles  # noqa: E402
from core.spectrum import Spectrum  # noqa: E402
from processing.functional_group_scoring import score_functional_groups  # noqa: E402


@dataclass
class GroupTally:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class BenchmarkResult:
    spectra: int = 0
    skipped: int = 0
    reported_per_spectrum: float = 0.0
    true_per_spectrum: float = 0.0
    spectrum_precision: float = 0.0
    spectrum_recall: float = 0.0
    top3_precision: float = 0.0
    groups: dict[str, GroupTally] = field(default_factory=dict)

    @property
    def micro(self) -> GroupTally:
        total = GroupTally()
        for tally in self.groups.values():
            total.tp += tally.tp
            total.fp += tally.fp
            total.fn += tally.fn
        return total

    @property
    def macro_f1(self) -> float:
        scored = [t.f1 for t in self.groups.values() if t.tp + t.fn > 0]
        return sum(scored) / len(scored) if scored else 0.0


def compound_key(name: str) -> str:
    """One key per compound: NIST stores several spectra of a compound as
    ``C62760_IR_0.jdx``, ``C62760_IR_2.jdx`` and they must share a split."""
    stem = Path(name).stem
    return stem.split("_IR_")[0] if "_IR_" in stem else stem


def split_of(name: str) -> str:
    """Deterministic dev/test half by compound."""
    digest = hashlib.sha1(compound_key(name).encode("utf-8")).digest()[0]
    return "dev" if digest % 2 == 0 else "test"


def load_spectrum(path: Path) -> Spectrum:
    suffix = path.suffix.lower()
    if suffix in (".jdx", ".dx", ".jcamp"):
        from file_io.jcamp_reader import JCAMPReader

        return JCAMPReader().read(path)
    from file_io.spa_reader import SPAReader

    return SPAReader().read(path)


def run(
    entries: list[dict],
    spectra_dir: Path,
    *,
    threshold: float = 55.0,
    scorer=score_functional_groups,
) -> BenchmarkResult:
    result = BenchmarkResult()
    groups: dict[str, GroupTally] = defaultdict(GroupTally)
    reported_total = true_total = 0
    precisions: list[float] = []
    recalls: list[float] = []
    top3: list[float] = []
    for entry in entries:
        truth = groups_in_smiles(entry.get("smiles", ""))
        if truth is None:
            result.skipped += 1
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                spectrum = load_spectrum(spectra_dir / entry["file"])
                analysis = scorer(spectrum)
        except Exception:  # noqa: BLE001 - a broken file is skipped, not fatal
            result.skipped += 1
            continue
        result.spectra += 1
        decided = [r for r in analysis.results if truth.is_known(r.group_id)]
        reported = {r.group_id for r in decided if r.score >= threshold}
        actual = {r.group_id for r in decided if truth.has(r.group_id)}
        for result_row in decided:
            gid = result_row.group_id
            is_true = gid in actual
            is_reported = gid in reported
            tally = groups[gid]
            if is_true and is_reported:
                tally.tp += 1
            elif is_reported:
                tally.fp += 1
            elif is_true:
                tally.fn += 1
        reported_total += len(reported)
        true_total += len(actual)
        if reported:
            precisions.append(len(reported & actual) / len(reported))
        if actual:
            recalls.append(len(reported & actual) / len(actual))
        ranked = [r.group_id for r in sorted(decided, key=lambda r: r.score, reverse=True)][:3]
        if ranked:
            top3.append(sum(1 for gid in ranked if gid in actual) / len(ranked))
    n = max(result.spectra, 1)
    result.reported_per_spectrum = reported_total / n
    result.true_per_spectrum = true_total / n
    result.spectrum_precision = sum(precisions) / len(precisions) if precisions else 0.0
    result.spectrum_recall = sum(recalls) / len(recalls) if recalls else 0.0
    result.top3_precision = sum(top3) / len(top3) if top3 else 0.0
    result.groups = dict(groups)
    return result


def format_report(result: BenchmarkResult, *, per_group: bool = True) -> str:
    micro = result.micro
    lines = [
        f"spectra {result.spectra} (skipped {result.skipped})",
        f"groups reported per spectrum {result.reported_per_spectrum:.2f}, "
        f"actually present {result.true_per_spectrum:.2f}",
        f"per-spectrum precision {result.spectrum_precision:.3f}  "
        f"recall {result.spectrum_recall:.3f}  top-3 precision {result.top3_precision:.3f}",
        f"micro P {micro.precision:.3f} R {micro.recall:.3f} F1 {micro.f1:.3f}   "
        f"macro F1 {result.macro_f1:.3f}",
    ]
    if per_group:
        lines.append(f"{'group':34s} {'n':>5s} {'TP':>5s} {'FP':>5s} {'FN':>5s}   P     R     F1")
        for gid, t in sorted(result.groups.items(), key=lambda kv: -(kv[1].tp + kv[1].fn)):
            lines.append(
                f"{gid:34s} {t.tp + t.fn:5d} {t.tp:5d} {t.fp:5d} {t.fn:5d}  "
                f"{t.precision:.2f}  {t.recall:.2f}  {t.f1:.2f}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("index", type=Path)
    parser.add_argument("spectra_dir", type=Path)
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--threshold", type=float, default=55.0)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--summary", action="store_true", help="omit the per-group table")
    args = parser.parse_args(argv)

    entries = json.loads(args.index.read_text(encoding="utf-8"))
    if args.split != "all":
        entries = [e for e in entries if split_of(e["file"]) == args.split]
    entries.sort(key=lambda e: e["file"])
    if args.limit:
        entries = entries[: args.limit]
    result = run(entries, args.spectra_dir, threshold=args.threshold)
    print(format_report(result, per_group=not args.summary))
    if args.json is not None:
        payload = {
            "spectra": result.spectra,
            "micro_f1": result.micro.f1,
            "macro_f1": result.macro_f1,
            "spectrum_precision": result.spectrum_precision,
            "spectrum_recall": result.spectrum_recall,
            "groups": {
                gid: {"tp": t.tp, "fp": t.fp, "fn": t.fn} for gid, t in result.groups.items()
            },
        }
        args.json.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
