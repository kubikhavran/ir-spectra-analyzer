# IR Spectra Analyzer

Professional desktop software for IR spectrum analysis and interpretation.

## Overview

IR Spectra Analyzer is a Python-based desktop application for analytical chemists working with infrared spectroscopy data. It provides a professional workflow for loading OMNIC `.spa` files, identifying and annotating spectral peaks, assigning vibration bands, and generating PDF analysis reports.

## Features (v0.1.0 — in development)

- **SPA File Import** — Robust OMNIC `.spa` reader with SpectroChemPy + binary fallback
- **Interactive Spectrum Viewer** — High-performance PyQtGraph viewer with zoom, pan, cursor readout
- **Peak Picking** — Automatic detection (SciPy) and manual click-to-add mode
- **Vibration Assignment** — Built-in 12 common IR vibration bands, user-extensible
- **PDF Export** — Publication-quality analysis reports with annotated spectrum and peak table
- **CSV / XLSX Export** — Peak tables for downstream data processing

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
| 0.1.0 | Basic Viewer + Manual Interpretation | 🔄 In Progress |
| 0.2.0 | Professional Workflow (Undo/Redo, project files) | ⏳ Planned |
| 0.3.0 | Spectral Database Matching | ⏳ Planned |
| 0.4.0 | Chemistry + Advanced Reporting (RDKit) | ⏳ Planned |

## License

MIT — see [LICENSE](LICENSE).
