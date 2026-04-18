# IR Spectra Analyzer

A professional desktop workbench for infrared spectrum analysis — purpose-built for
analytical chemistry labs that work with Thermo Fisher **OMNIC `.spa`** files and want
to replace paper-based IR interpretation with a fast, reproducible digital workflow.

Open a spectrum, pick peaks (manually or automatically), assign vibration bands from
a curated preset library, match against a local reference-spectra database, sketch
the candidate molecule, and export a publication-quality PDF report — all in one
native app.

---

## Table of contents

- [Features](#features)
- [Screenshots](#screenshots)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Typical workflow](#typical-workflow)
- [Reference library](#reference-library)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Project files (`.irproj`)](#project-files-irproj)
- [File format support](#file-format-support)
- [Project structure](#project-structure)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Features

### Spectrum viewing & editing
- **OMNIC-style interactive viewer** built on PyQtGraph (>1000 FPS, inverted x-axis,
  in-ticks, white background matching OMNIC's default look).
- **Tool modes** — Select / Pan / Zoom / Add Peak — toggle from the toolbar or keyboard.
- **Rubber-band baseline correction** (lower-convex-hull algorithm), fully undoable.
- **Multi-spectrum overlay** with legend and independent color assignment.
- **Unit conversion** between Absorbance / Transmittance / Reflectance / Single-Beam.

### Peak picking & interpretation
- **Automatic peak detection** (SciPy `find_peaks` with tunable prominence / width).
- **Manual click-to-add** and drag-to-reposition of individual peaks.
- **Vibration preset library** — 12 default IR bands (C=O, O–H, C–H, N–H, aromatic, …)
  with wavenumber ranges. Double-click a peak to assign, or filter-highlight peaks
  that fall inside a preset's range.
- **Full undo/redo** via `QUndoStack` — peak add/delete/assign, baseline correction,
  and molecule edits all participate. `Ctrl+Z` / `Ctrl+Y`.

### Chemistry
- **Embedded JSME molecule editor** (JavaScript structure editor in a Qt WebView)
  with periodic-table picker and custom-element support (Na, K, Fe, …).
- **SMILES round-trip** via RDKit — paste a SMILES to pre-populate the editor, or
  export the edited structure as SMILES / MOL block.
- **Structure panel** attaches a molecule to the project — shown in the viewer and
  embedded in PDF reports.

### Reference library & similarity search
- **Local SQLite-backed library** of reference spectra. Import any `.spa` file in
  one click, or drop a whole folder onto the library dialog (recurses subfolders).
- **Cosine-similarity search** on a fixed 400–4000 cm⁻¹ / 1 cm⁻¹ grid with
  auto-interpolation. Results ranked, color-coded by score%, shown in a dedicated
  panel with overlay preview of the top candidates.
- **Library curator UI** — multi-select, bulk delete, inline description editing,
  drag-and-drop import, keyboard shortcuts (`Delete` / `F2` / `Enter`), footer stats
  (count, date range, unit mix), and "Open in main window" to pull any reference
  back as the working spectrum.
- **Find similar to selected** — use any library entry itself as the query.

### Reporting & export
- **Publication-quality PDF reports** — OMNIC-style spectrum render (Matplotlib),
  peak table, vibration assignments, metadata block, and embedded molecule
  structure. Fully customizable header / footer / spectrum X-range via dialog.
- **Data export** — peaks + spectrum to `.xlsx` or `.csv` with format-selection dialog.
- **Project save/load** — full workspace (spectrum + peaks + assignments + baseline +
  structure + metadata) as a single human-readable `.irproj` JSON file.

### Batch processing
- **Bulk SPA import** from a folder, with progress dialog and summary.
- **Batch PDF export** — generate a report for every spectrum in a project.

---

## Screenshots

> _Add a screenshot of the main window and reference-library dialog here
> (PNG in `docs/screenshots/`)._

---

## Requirements

| Component | Minimum |
|-----------|---------|
| Python | 3.11+ |
| Platform | Windows, macOS, Linux (primary target: Windows desktop) |
| Memory | ~500 MB for typical workflow |
| Disk | ~400 MB with the full venv (includes RDKit, Matplotlib, Qt) |

Runtime dependencies (installed automatically): PySide6 (Qt 6), PyQtGraph, NumPy,
SciPy, RDKit, ReportLab, Matplotlib, openpyxl, SpectroChemPy.

---

## Installation

### With [uv](https://github.com/astral-sh/uv) (recommended)

```bash
git clone https://github.com/kubikhavran/ir-spectra-analyzer.git
cd ir-spectra-analyzer

uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
```

### With plain pip

```bash
git clone https://github.com/kubikhavran/ir-spectra-analyzer.git
cd ir-spectra-analyzer

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

---

## Quick start

```bash
python main.py
```

The app opens to an empty main window. Use **File → Open** (or the toolbar)
to load a `.spa` file and start picking peaks.

To try a pre-wired workflow end-to-end without clicking through the UI:

```bash
pytest -q                           # runs the full test suite (offscreen Qt)
```

---

## Typical workflow

1. **Load a spectrum** — `File → Open`, pick a `.spa` file. The viewer auto-scales
   and the metadata panel populates from the OMNIC type-27 text block.
2. **Detect peaks** — click **Detect Peaks** on the toolbar. Tune prominence /
   width in the dialog if needed. Or switch to **Add Peak** mode and click directly
   on the spectrum.
3. **Assign vibrations** — pick a preset in the vibration panel to highlight peaks
   that fall in its range, then double-click a peak to assign.
4. **(Optional) Correct baseline** — click **Correct Baseline** → rubber-band.
   `Ctrl+Z` if the result is wrong.
5. **(Optional) Sketch the molecule** — open the structure panel, use the embedded
   JSME editor, or paste a SMILES.
6. **Match against the library** — `Match Spectrum` on the toolbar (requires a
   reference-library folder to be selected in the library dialog). Top hits are
   shown with score% and can be overlaid on the current spectrum for visual
   comparison.
7. **Export** — `File → Export PDF Report` (with molecule + peaks + metadata),
   or `File → Export Data` for `.xlsx` / `.csv`.
8. **Save the project** — `File → Save Project` writes a `.irproj` JSON you can
   re-open later with the exact same peaks, assignments, and baseline state.

---

## Reference library

The library lives in a local SQLite database (`~/.ir-spectra-analyzer/library.db`
on Linux/macOS, `%APPDATA%\ir-spectra-analyzer\` on Windows) and a user-chosen
folder of `.spa` files on disk.

**Open the library:** toolbar → **Reference Library** (or via the match dialog).

**Import spectra** — three ways:

- **Drag & drop** one or more `.spa` files (or a whole folder) onto the dialog.
- **Import File** button for a file-picker.
- **Choose / Sync Folder** to designate the active library folder; the app
  auto-imports any new `.spa` files found there.

**Curate** — multi-select rows with Shift/Ctrl+click, then:

| Action | Shortcut | Notes |
|--------|----------|-------|
| Delete selected | `Delete` / `Backspace` | With confirmation |
| Rename selected | `F2` | Prompts for new name |
| Open in main window | `Enter` / `Return` | Loads the source `.spa` |
| Edit description | Double-click the *Description* cell | Persists to DB |
| Find similar to selected | button | Uses the selected entry as query |

**Preview** — select up to five rows to see their curves overlaid
(normalized to 0-1 when comparing across entries).

**Stats footer** — total count, import-date range, unit mix (e.g. "12× Absorbance,
3× Transmittance").

---

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open `.spa` spectrum |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save As project |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Ctrl+E` | Export PDF report |
| `Delete` | Delete selected peak |
| `A` | Switch to Add-Peak tool |
| `S` | Switch to Select tool |
| `P` | Switch to Pan tool |
| `Z` | Switch to Zoom tool |

---

## Project files (`.irproj`)

A project file is a single UTF-8 JSON document:

```json
{
  "version": 1,
  "spectrum": { "wavenumbers": [...], "intensities": [...], "y_unit": "Absorbance", ... },
  "peaks": [ { "position": 1720.5, "intensity": 0.42, "vibration_id": 3, ... } ],
  "structure": { "smiles": "CC(=O)C", "mol_block": "..." },
  "metadata": { "title": "...", "comments": "...", "source_path": "..." }
}
```

Human-readable, diff-friendly, safe to commit to your own lab-notebook repo.

---

## File format support

| Format | Read | Write | Notes |
|--------|:----:|:-----:|-------|
| OMNIC `.spa` | ✅ | — | Dual-mode parser: OMNIC 16-byte directory + type-27 metadata, plus a compact synthetic mode for tests |
| `.irproj` | ✅ | ✅ | Native project format (JSON) |
| `.xlsx` | — | ✅ | Peaks + spectrum, multi-sheet |
| `.csv` | — | ✅ | Peaks or spectrum (separate files) |
| `.pdf` | — | ✅ | Full analysis report |

---

## Project structure

```
ir-spectra-analyzer/
├── main.py                 # Entry point
├── app/                    # Application lifecycle, config, library service
├── core/                   # Domain models — Spectrum, Peak, Project, commands (undo)
├── file_io/                # Format registry, SPA binary parser, export writers
├── processing/             # Pure-function signal processing (peaks, baseline, smoothing)
├── matching/               # Reference DB, similarity search, quality scoring
├── chemistry/              # RDKit adapters, JSME structure model
├── reporting/              # PDF report builder + Matplotlib spectrum renderer
├── ui/                     # PySide6 GUI (MainWindow, panels, dialogs, widgets)
├── storage/                # SQLite + JSON settings persistence
├── utils/                  # Shared helpers
├── tests/                  # pytest + pytest-qt test suite (333 tests)
├── pyproject.toml          # Build + tooling config
├── IR_Spectral_Software_Architecture.md   # Full architectural design doc
└── LICENSE
```

**Architectural rules** (if you plan to contribute):

1. The UI layer (`ui/`) never does I/O or numerics — it delegates to the core models
   over Qt signals.
2. `processing/` is purely functional — numpy arrays in, numpy arrays out, no state.
3. `core.project.Project` is the single source of truth for the current workspace.
4. `file_io.format_registry.FormatRegistry` is a plug-in point — new file formats
   are added by registering a reader/writer, without touching the rest of the app.

See `IR_Spectral_Software_Architecture.md` for the full design rationale.

---

## Development

```bash
# Run the full test suite (333 tests, runs headless)
pytest -q

# Run just the UI-dialog tests
pytest -q tests/test_reference_library_dialog.py

# Format and lint
ruff format . && ruff check . --fix

# Type-check (strict)
mypy .

# Pre-commit (auto-installs on clone)
pre-commit install
pre-commit run --all-files
```

### Test suite

- **Framework:** `pytest` + `pytest-qt` for Qt-widget interaction tests.
- **Headless:** tests set `QT_QPA_PLATFORM=offscreen` automatically — no display
  required on CI.
- **Fixtures:** `tests/fixtures/` holds three real Nicolet iS10 `.spa` files that
  drive end-to-end parser verification.

### Contributing

1. Fork & branch from `main`.
2. Add a test for the behavior you're changing.
3. Run `ruff format . && ruff check . && pytest` before pushing.
4. Open a PR. Conventional-commit style is preferred (`feat:`, `fix:`, `refactor:`,
   `test:`, `docs:`, `chore:`).

---

## Troubleshooting

**`ImportError: DLL load failed` on Windows for PySide6**
Install the [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
and relaunch.

**JSME molecule editor won't load elements**
The first launch downloads JSME + its GWT code-split fragments into
`~/.ir-spectra-analyzer/jsme_cache/`. If you see a "Loading JS code failed" dialog,
delete that cache folder and relaunch — the app will re-download everything.

**`.spa` parsing fails with "unknown magic"**
The file is probably not a standard OMNIC SPA. Known-good instruments: Nicolet iS5,
iS10, iS50. Share the file via an issue if it's from a different vendor.

**No peaks detected on a transmittance spectrum**
Check that the y-axis unit is correctly identified in the metadata panel. The app
auto-detects dip-vs-peak from the declared unit; for mislabeled files you can toggle
the unit manually.

---

## License

MIT — see [LICENSE](LICENSE). Free for commercial and academic use.

---

## Acknowledgements

- **OMNIC** is a registered trademark of Thermo Fisher Scientific. This project
  reads the `.spa` file format but is otherwise unaffiliated.
- **JSME** molecule editor by Bruno Bienfait and Peter Ertl, distributed under BSD.
- **RDKit**, **PyQtGraph**, **PySide6**, **ReportLab**, **Matplotlib** — thanks to
  their maintainers for the foundational libraries.
