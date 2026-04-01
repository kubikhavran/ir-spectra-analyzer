# IR Spectra Analyzer — Agent Instructions (OpenAI Codex)

## Before doing anything, read these two files in full:
1. `PROJECT_STATE.md` — current status, roadmap, active tasks, known bugs
2. `IR_Spectral_Software_Architecture.md` — authoritative architectural design

---

## Project overview

Desktop scientific application for IR spectrum analysis.
**User:** Analytical chemistry lab, daily use with Thermo Fisher OMNIC `.spa` files on Windows.
**Goal:** Replace paper-based IR interpretation with a professional desktop tool.

## Stack

- **Language:** Python 3.11+
- **GUI:** PySide6 (Qt 6) + PyQtGraph (interactive spectrum viewer)
- **Numerics:** NumPy + SciPy (peak detection, baseline, smoothing)
- **SPA parser:** SpectroChemPy → custom binary fallback (3-stage)
- **Persistence:** SQLite (`storage/database.py`) + JSON (`storage/settings.py`)
- **PDF reporting:** ReportLab + Matplotlib (static render)
- **Formatter:** ruff | **Linter:** mypy (strict) | **Tests:** pytest

## Directory structure (key modules)

```
main.py                  Entry point
app/application.py       Lifecycle, wires components together
core/                    Domain models: Spectrum, Peak, Project, VibrationPreset
io/                      SPAReader (3-stage), CSV/XLSX exporters, FormatRegistry
processing/              Pure functions: peak_detection, baseline, smoothing, normalization
storage/                 SQLite schema + 12 default vibration presets, JSON settings
ui/                      PySide6 GUI: MainWindow, SpectrumWidget (PyQtGraph), panels, dialogs
reporting/               PDF report generation (ReportLab + Matplotlib)
matching/                Spectral database matching — v0.3.0+, stubs only
chemistry/               RDKit cheminformatics — v0.4.0+, stubs only
tests/                   pytest suite
```

## Hard architectural rules — do not violate

1. `ui/` layer NEVER performs I/O or calculations — delegates to `core/` via Qt signals
2. `processing/` is purely functional — input: numpy arrays, output: numpy arrays, zero state
3. `core/project.py` is single source of truth — holds spectrum + peaks + metadata
4. `io/format_registry.py` is plug-in architecture — add formats without touching other code
5. `storage/database.py` uses SQLite — no ORM, plain `sqlite3`

## How to work on this project

1. Read `PROJECT_STATE.md` fully
2. Pick a task from **"Todo — Prioritní"** section, mark it In Progress in the file
3. Implement it following the architecture document
4. Before committing: `ruff check . --fix && ruff format . && mypy . && pytest`
5. Update `PROJECT_STATE.md` — add milestone entry, move task to Done, log any bugs found

## Commit convention

```
feat: description
fix: description
refactor: description
test: description
docs: description
chore: build/deps
```

## Current priority (v0.1.0 MVP)

1. `reporting/pdf_generator.py` — implement ReportLab PDF with spectrum image + peak table
2. `ui/main_window.py` — add QDockWidget panels (SpectrumWidget + PeakTable + VibrationPanel)
3. Peak picker integration — connect SpectrumWidget click → PeakPicker → Project.add_peak()
4. Auto peak detection UI — "Detect Peaks" button calling `processing/peak_detection.detect_peaks()`
