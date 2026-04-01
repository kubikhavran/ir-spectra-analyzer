# IR Spectra Analyzer — GitHub Copilot Instructions

## Project context

Desktop scientific software for IR spectrum analysis (Python 3.11+, PySide6, PyQtGraph).
Used daily by analytical chemists to load OMNIC `.spa` files, pick peaks, assign vibration bands, and export PDF reports.
See `IR_Spectral_Software_Architecture.md` for the full design and `PROJECT_STATE.md` for current status and tasks.

## Stack & key dependencies

- **GUI:** PySide6 (Qt 6) — use `PySide6.QtWidgets`, `PySide6.QtCore`
- **Spectrum viewer:** PyQtGraph — `pyqtgraph.PlotWidget`
- **Numerics:** NumPy + SciPy — `scipy.signal.find_peaks` for peak detection
- **SPA files:** SpectroChemPy `scp.read_omnic()` as primary parser
- **Database:** `sqlite3` (stdlib) — no ORM
- **PDF:** ReportLab + Matplotlib (static spectrum render)
- **Formatter:** ruff | **Types:** mypy strict | **Tests:** pytest

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
```

## What NOT to generate

- Do not add `__all__` unless explicitly asked
- Do not add logging unless explicitly asked
- Do not use `PyQt6` — this project uses `PySide6`
- Do not use ORM (SQLAlchemy etc.) — plain `sqlite3` only
- Do not add abstract base classes for single implementations
- Do not generate `matching/` or `chemistry/` implementations — those are v0.3+/v0.4+ stubs

## Current priority tasks (v0.1.0)

1. `reporting/pdf_generator.py` — ReportLab layout: metadata header + Matplotlib spectrum PNG + peak table
2. `ui/main_window.py` — QDockWidget layout with SpectrumWidget, PeakTableWidget, VibrationPanel, MetadataPanel
3. `ui/interactions/peak_picker.py` — wire click event from SpectrumWidget to Project.add_peak()
4. Auto peak detection — button in toolbar calling `processing/peak_detection.detect_peaks()`
