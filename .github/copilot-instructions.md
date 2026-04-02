# IR Spectra Analyzer — GitHub Copilot Instructions

## Project context

Desktop scientific software for IR spectrum analysis (Python 3.11+, PySide6, PyQtGraph).
Used daily by analytical chemists to load OMNIC `.spa` files, pick peaks, assign vibration bands, and export PDF reports.
See `IR_Spectral_Software_Architecture.md` for the full design and `PROJECT_STATE.md` for current status and tasks.

**Current version: 0.3.0 (COMPLETE — 112 tests passing). Working towards v0.4.0.**

## Stack & key dependencies

- **GUI:** PySide6 (Qt 6) — use `PySide6.QtWidgets`, `PySide6.QtCore`, `PySide6.QtGui`
- **Spectrum viewer:** PyQtGraph — `pyqtgraph.PlotWidget`, `pg.ViewBox.RectMode` / `PanMode` for tool modes
- **Numerics:** NumPy + SciPy — `scipy.signal.find_peaks` for peak detection
- **SPA files:** custom `io/spa_binary.py` — OMNIC binary format parser (no SpectroChemPy dependency in hot path)
- **Database:** `sqlite3` (stdlib) — no ORM
- **PDF:** ReportLab + Matplotlib (static OMNIC-like spectrum render)
- **Formatter:** ruff | **Types:** mypy strict | **Tests:** pytest + pytest-qt

## Code style

- All public functions and methods must have type annotations
- Docstrings in Google style
- `from __future__ import annotations` at top of every module
- Line length: 100 characters
- Imports: stdlib → third-party → local (ruff handles ordering)

## Architectural rules Copilot must follow

```
ui/          → NEVER call io/ or processing/ directly. Use core/ models and Qt signals.
processing/  → Pure functions only. No class state. Input/output: numpy arrays.
core/        → Project class is single source of truth. UI reads from it, never writes directly.
io/          → Plug-in pattern via FormatRegistry. New formats: register, don't modify callers.
storage/     → Plain sqlite3. Schema in database.py._apply_schema(). No raw SQL in UI.
```

## What is already implemented (do not re-implement)

- `io/spa_binary.py` — full SPA parser, dual-mode OMNIC/compact
- `io/xlsx_exporter.py` — Peaks + Spectrum sheets, openpyxl
- `ui/spectrum_widget.py` — PyQtGraph viewer with `set_spectrum()`, `set_peaks()`, `set_tool_mode()`
- `ui/main_window.py` — full layout, toolbar wiring, project save/load, undo/redo, export dialog, Delete shortcut, recent files
- `ui/toolbar.py` — tool modes, detect peaks, correct baseline, export
- `ui/dialogs/export_dialog.py` — PDF/CSV/XLSX selector
- `ui/vibration_panel.py` — filter, highlight_for_peak, preset assignment via double-click
- `core/commands/peak_commands.py` — AddPeakCommand, DeletePeakCommand, AssignPresetCommand, CorrectBaselineCommand
- `processing/baseline.py` — `rubber_band_baseline()`, `polynomial_baseline()`
- `processing/peak_detection.py` — SciPy-based, functional
- `storage/project_serializer.py` — JSON `.irproj` full roundtrip
- `reporting/pdf_generator.py` + `reporting/spectrum_renderer.py` — full implementation

## Preferred patterns

```python
# Signals: define at class level, emit don't call UI methods directly
peak_added = Signal(float, float)  # (wavenumber, intensity)

# Processing functions: always pure
def detect_peaks(wavenumbers: np.ndarray, intensities: np.ndarray, ...) -> list[Peak]: ...

# Dataclasses for domain models
@dataclass
class Peak:
    position: float
    intensity: float
    ...

# QUndoCommand pattern (for v0.2.0 undo/redo)
class AddPeakCommand(QUndoCommand):
    def __init__(self, project: Project, peak: Peak) -> None: ...
    def redo(self) -> None: project.add_peak(peak)
    def undo(self) -> None: project.peaks.remove(peak)
```

## What NOT to generate

- Do not add `__all__` unless explicitly asked
- Do not add logging unless explicitly asked
- Do not use `PyQt6` — this project uses `PySide6`
- Do not use ORM (SQLAlchemy etc.) — plain `sqlite3` only
- Do not add abstract base classes for single implementations
- Do not generate `matching/` or `chemistry/` implementations — those are v0.3+/v0.4+ stubs
- Do not re-implement already-done modules listed above

## Next priority tasks (v0.4.0)

1. **RDKit** — `chemistry/structure_renderer.py`: `render_smiles_to_png(smiles: str, size: tuple) -> bytes`. Add optional `smiles: str = ""` field to `Peak`. `MoleculeWidget(QLabel)` renders it as pixmap.
2. **Advanced PDF** — add molecule structure image to `PDFGenerator`. Implement `ReportBuilder` stub.
3. **Reference library dialog** — `ui/dialogs/reference_library_dialog.py`: QTableWidget listing all `reference_spectra` rows; delete + rename + preview spectrum.
4. **Batch SPA import** — `ui/dialogs/batch_import_dialog.py`: folder picker → import all `.spa` files as references via `db.add_reference_spectrum()`.
