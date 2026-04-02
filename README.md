# IR Spectra Analyzer

Professional desktop software for IR spectrum analysis and interpretation.

## Overview

IR Spectra Analyzer is a Python-based desktop application for analytical chemists working with infrared spectroscopy data. It provides a professional workflow for loading OMNIC `.spa` files, identifying and annotating spectral peaks, assigning vibration bands, and generating PDF analysis reports.

## Features (v0.2.0 — current)

- **SPA File Import** — Custom binary OMNIC `.spa` reader (16-byte directory, type-27 metadata extraction)
- **Interactive Spectrum Viewer** — OMNIC-like PyQtGraph viewer: white background, inverted X-axis, in-ticks, tool modes (Select/Pan/Zoom/Add Peak)
- **Peak Picking** — Automatic SciPy detection and manual click-to-add mode
- **Vibration Assignment** — 12 default IR vibration presets; filter, highlight matching, assign by double-click
- **Baseline Correction** — Rubber-band (lower convex hull) algorithm, undoable
- **Undo / Redo** — Full `QUndoStack` covering peak add/delete/assign and baseline correction (Ctrl+Z / Ctrl+Y)
- **Project Files** — Save and load full project state (spectrum + peaks + assignments + corrected spectrum) as `.irproj` JSON
- **PDF Export** — Publication-quality reports with OMNIC-like spectrum image and peak table
- **CSV / XLSX Export** — Peaks table and raw spectrum data export; format selection dialog

## Architecture

Full architectural design: [`IR_Spectral_Software_Architecture.md`](IR_Spectral_Software_Architecture.md)

Project state and roadmap: [`PROJECT_STATE.md`](PROJECT_STATE.md)

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
git clone https://github.com/kubikhavran/ir-spectra-analyzer.git
cd ir-spectra-analyzer

# Create virtual environment
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install with dev dependencies
uv pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Run

```bash
python main.py
```

## Development

```bash
# Run tests
pytest

# Lint + format
ruff check . --fix && ruff format .

# Type check
mypy .
```

## Project Structure

```
ir-spectra-analyzer/
├── main.py              # Entry point
├── app/                 # Application lifecycle (Application, config)
├── core/                # Domain models (Spectrum, Peak, Project, VibrationPreset)
├── io/                  # File readers and exporters (SPA, CSV, XLSX)
├── processing/          # Signal processing — pure functions (peaks, baseline, smoothing)
├── matching/            # Spectral database matching (v0.3.0+)
├── chemistry/           # Cheminformatics — RDKit (v0.4.0+)
├── reporting/           # PDF report generation (ReportLab + Matplotlib)
├── ui/                  # PySide6 GUI (MainWindow, SpectrumWidget, panels, dialogs)
├── storage/             # SQLite + JSON persistence
├── utils/               # Shared utilities
└── tests/               # pytest test suite
```

## Roadmap

| Version | Name | Status |
|---------|------|--------|
| 0.1.0 | Basic Viewer + Manual Interpretation | ✅ Done |
| 0.2.0 | Professional Workflow (Undo/Redo, project files, baseline) | ✅ Done |
| 0.3.0 | Spectral Database Matching | ✅ Done |
| 0.4.0 | Chemistry + Advanced Reporting (RDKit) | 🔄 Next |

## License

MIT — see [LICENSE](LICENSE).
