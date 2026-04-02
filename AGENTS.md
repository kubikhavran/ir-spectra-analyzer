# IR Spectra Analyzer — Agent Instructions (OpenAI Codex / Codex CLI)

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
- **SPA parser:** custom `io/spa_binary.py` — dual-mode (OMNIC binary + compact synthetic)
- **Persistence:** SQLite (`storage/database.py`) + JSON (`storage/settings.py`)
- **PDF reporting:** ReportLab + Matplotlib (OMNIC-like static render)
- **Formatter:** ruff | **Linter:** mypy (strict) | **Tests:** pytest + pytest-qt

## Current version: 0.3.0 (COMPLETE — 112/112 tests passing)

v0.3.0 is fully shipped. The next target is **v0.4.0 — Chemistry + Advanced Reporting**.

### What is implemented
- `io/spa_binary.py` — full OMNIC SPA binary parser (16-byte directory, type-3 intensities, type-27 metadata text extraction for y_unit/acquired_at/resolution)
- `ui/spectrum_widget.py` — PyQtGraph viewer: OMNIC-like white background, inverted X-axis, in-ticks, peak annotations, `set_tool_mode()` wired to ViewBox mouse modes
- `ui/main_window.py` — QDockWidget layout, toolbar wiring, peak detection, export, project save/load, undo stack (cleared on file/project load)
- `ui/toolbar.py` — Select/Pan/Zoom/Add Peak modes, Detect Peaks, Correct Baseline, Export
- `ui/dialogs/export_dialog.py` — PDF/CSV/XLSX format selector
- `ui/vibration_panel.py` — filter, highlight_for_peak, double-click assignment workflow
- `core/commands/peak_commands.py` — AddPeakCommand, DeletePeakCommand, AssignPresetCommand, CorrectBaselineCommand
- `processing/baseline.py` — `rubber_band_baseline()` (lower convex hull), `polynomial_baseline()` (existing)
- `processing/peak_detection.py` — SciPy find_peaks with prominence threshold
- `storage/project_serializer.py` — JSON `.irproj` save/load (spectrum + corrected_spectrum + peaks + metadata)
- `io/xlsx_exporter.py` — Peaks sheet + Spectrum sheet, openpyxl
- `reporting/pdf_generator.py` — ReportLab A4 report (header + metadata table + spectrum image + peaks table + footer)
- `reporting/spectrum_renderer.py` — Matplotlib OMNIC-like render (%T and Absorbance modes)

### Also implemented (v0.3.0)
- `storage/database.py` — `reference_spectra` table (BLOB float64 arrays), `add_reference_spectrum()`, `get_reference_spectra()`, `delete_reference_spectrum()`
- `matching/similarity.py` — `cosine_similarity()`, `STANDARD_GRID` (400–4000 cm⁻¹, 1 cm⁻¹)
- `matching/search_engine.py` — `MatchResult` dataclass, `SearchEngine` (load_references + search)
- `matching/preprocessing.py` — `prepare_for_matching()` (resample + peak_normalize)
- `ui/match_results_panel.py` — ranked results dock, score% with color coding, candidate_selected + import_reference signals
- `ui/spectrum_widget.py` — `set_overlay_spectra()` for gray dotted reference curves
- `ui/toolbar.py` — "Match Spectrum" action
- `ui/main_window.py` — full matching workflow wired; `_last_search_refs` cache avoids repeated DB hits

### What is NOT yet implemented (v0.4.0 scope)
- RDKit structure rendering — `chemistry/` contains stubs only
- Advanced PDF with molecule structure — `reporting/report_builder.py` is a stub
- Reference library management UI — no browse/edit dialog yet
- Batch processing — no folder-level SPA import or bulk export

## Directory structure (key modules)

```
main.py                  Entry point (QApplication setup)
app/application.py       Lifecycle — wires Database, Settings, MainWindow together
core/                    Domain models: Spectrum, Peak, Project, VibrationPreset, SpectrumMetadata
io/                      SPABinaryReader, CSVExporter, XLSXExporter (stub), FormatRegistry
processing/              Pure functions: peak_detection, baseline (stub), smoothing, normalization
storage/                 SQLite (12 default vibration presets), JSON settings
ui/                      PySide6 GUI: MainWindow, SpectrumWidget, panels, toolbar, dialogs
reporting/               PDFGenerator (full), SpectrumRenderer (full), ReportBuilder (stub)
matching/                Spectral database matching — v0.3.0+, stubs only
chemistry/               RDKit cheminformatics — v0.4.0+, stubs only
tests/                   pytest suite (73 tests), fixtures/ has 3 real Nicolet iS10 SPA files
```

## Hard architectural rules — do not violate

1. `ui/` layer NEVER performs I/O or calculations — delegates to `core/` via Qt signals
2. `processing/` is purely functional — input: numpy arrays, output: numpy arrays, zero state
3. `core/project.py` is single source of truth — holds spectrum + peaks + metadata
4. `io/format_registry.py` is plug-in architecture — add formats without touching other code
5. `storage/database.py` uses SQLite — no ORM, plain `sqlite3`

## Known technical debt

- `io/` package name shadows stdlib `io`. Workaround in `conftest.py` (meta_path finder) + `io/__init__.py` (re-exports `_io` symbols). Clean fix: rename to `file_io/` — deferred to v0.2.0.
- PDF footer shows "Page N" only — "Page N of M" needs two-pass ReportLab pattern.

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

## Next priority tasks (v0.4.0)

1. **RDKit integration** — `chemistry/structure_renderer.py`: render SMILES → PNG bytes. New `MoleculeWidget` in the right dock. Store optional SMILES on `Peak`.
2. **Advanced PDF report** — add molecule structure image to `reporting/pdf_generator.py`. Implement `reporting/report_builder.py`.
3. **Reference library management UI** — `ui/dialogs/reference_library_dialog.py`: browse, delete, rename, preview reference spectra.
4. **Batch processing** — `ui/dialogs/batch_import_dialog.py`: import whole SPA folder as references; bulk PDF export.
