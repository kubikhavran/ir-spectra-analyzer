"""The benchmark tool runs end to end on files with known structures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import fg_benchmark  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def test_benchmark_scores_known_spectra() -> None:
    entries = [
        {"file": "atrcor.spa", "smiles": "CO"},  # methanol
        {"file": "absorb.spa", "smiles": "CC(C)c1ccccc1"},  # polystyrene repeat unit
        {"file": "missing.spa", "smiles": "CCO"},  # unreadable: skipped
        {"file": "absorb.spa", "smiles": "not smiles"},  # no structure: skipped
    ]
    result = fg_benchmark.run(entries, FIXTURES)
    assert result.spectra == 2
    assert result.skipped == 2
    assert "alcohol" in result.groups
    assert result.true_per_spectrum > 0
    report = fg_benchmark.format_report(result)
    assert "micro P" in report


def test_split_keeps_every_spectrum_of_a_compound_together() -> None:
    names = [f"C64175_IR_{i}.jdx" for i in range(4)]
    assert len({fg_benchmark.split_of(name) for name in names}) == 1
    assert fg_benchmark.compound_key("C64175_IR_2.jdx") == "C64175"
