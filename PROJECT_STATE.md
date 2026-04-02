# IR Spectra Analyzer — Project State

> **INSTRUKCE PRO AI AGENTY:** Před zahájením jakékoliv práce přečti tento soubor celý. Po dokončení práce ho aktualizuj — zapiš co jsi udělal, jaké bugs jsi objevil, a co je dalším krokem. Tento soubor je živý dokument a single source of truth pro stav projektu.

## Metadata projektu

- **Název:** IR Spectra Analyzer
- **Jazyk:** Python 3.11+
- **GUI:** PySide6 + PyQtGraph
- **Repozitář:** https://github.com/kubikhavran/ir-spectra-analyzer (private)
- **Hlavní architektura:** viz `IR_Spectral_Software_Architecture.md`
- **Poslední aktualizace:** 2026-04-03
- **Aktuálně pracuje:** nikdo

---

## Aktuální verze: 0.4.0 (In Progress — Chemie + Pokročilý Reporting)

## Roadmap

| Verze | Název | Status | Popis |
|-------|-------|--------|-------|
| 0.1.0 | Základní Viewer + Ruční Interpretace | ✅ Done | MVP — načtení SPA, zobrazení spektra, peak picking, export PDF |
| 0.2.0 | Profesionální Workflow | ✅ Done | Undo/Redo, baseline, projekt soubory, XLSX export |
| 0.3.0 | Databázové Porovnávání | ✅ Done | Spectral matching, similarity algoritmy |
| 0.4.0 | Chemie + Pokročilý Reporting | 🔄 In Progress | RDKit, reporty s molekulami, reference library UI, batch workflow |

---

## Dokončené milestones

### ✅ 2026-04-03 — v0.4.0 post-batch step — Batch project generation
- `app/batch_project_generation.py`: nový `BatchProjectGenerator` + strukturované výsledky (`BatchProjectResult`, `BatchProjectSummary`) pro generování trvalých `.irproj` souborů ze složky `.spa` souborů
- `ui/dialogs/batch_project_generation_dialog.py`: dialog pro výběr input/output složek, volitelnou auto peak detection a přehled výsledků po souborech
- `ui/main_window.py`: `&Database` menu rozšířeno o "Batch Generate Projects..."
- `tests/test_batch_project_generation.py`: 8 nových testů pro generator, failure continuation, detect-peaks workflow a dialog option wiring
- 147 testů passing, 3 skipped (RDKit not installed)
- Poznámka: tento krok rozšiřuje původní batch workflow o durable project outputs přes existující `Project` + `ProjectSerializer` pipeline

### ✅ 2026-04-03 — v0.4.0 task #4 step 3 — Optional auto peak detection pro batch workflow
- `app/reference_import.py`: `detect_peaks` option pro single-file i batch import; detekované peaky se vrací ve strukturovaných výsledcích in-memory bez změny DB schématu
- `app/batch_pdf_export.py`: `detect_peaks` option pro batch PDF export; při zapnutí se peaky přidají do minimálního `Project` objektu před generováním reportu
- `ui/dialogs/batch_import_dialog.py` + `ui/dialogs/batch_pdf_export_dialog.py`: přidán checkbox "Auto-detect peaks"
- `tests/test_batch_import_dialog.py` + `tests/test_batch_pdf_export.py`: rozšířeny o coverage pro detect-peaks option wiring a service-level behavior
- 139 testů passing, 3 skipped (RDKit not installed)
- Batch processing scope je tímto pro v0.4.0 kompletní

### ✅ 2026-04-03 — v0.4.0 task #4 step 2 — Bulk PDF export
- `app/batch_pdf_export.py`: nový `BatchPDFExporter` + strukturované výsledky (`BatchPDFResult`, `BatchPDFSummary`) pro export PDF reportů ze složky `.spa` souborů
- `ui/dialogs/batch_pdf_export_dialog.py`: dialog pro výběr input/output složek, batch export a přehled výsledků po souborech
- `ui/main_window.py`: `&Database` menu rozšířeno o "Batch Export PDF Reports..."
- `tests/test_batch_pdf_export.py`: 5 nových testů pro exporter, failure continuation, summary counts a dialog rendering
- 135 testů passing, 3 skipped (RDKit not installed)
- Poznámka: auto peak detection pro batch workflow zatím není implementované

### ✅ 2026-04-03 — v0.4.0 task #4 foundation — Batch reference import
- `app/reference_import.py`: nový `ReferenceImportService` + strukturované výsledky (`ImportedReference`, `BatchImportResult`, `BatchImportSummary`) pro single-file i batch import workflow
- `ui/dialogs/batch_import_dialog.py`: dialog pro výběr složky, duplicate-skip policy, batch import a přehled výsledků po souborech
- `ui/main_window.py`: `&Database` menu rozšířeno o "Batch Import References..."; single-file import nyní reuseuje stejný import helper
- `tests/test_batch_import_dialog.py`: 5 nových testů pro dialog, batch import service, duplicate-skip logiku a summary reporting
- 130 testů passing, 3 skipped (RDKit not installed)
- Poznámka: bulk PDF export a auto peak detection pro batch workflow zatím nejsou implementované

### ✅ 2026-04-03 — v0.4.0 task #3 — Reference Library management UI
- `storage/database.py`: `Database` nyní korektně podporuje `":memory:"` i string paths; přidáno `rename_reference_spectrum()`
- `ui/dialogs/reference_library_dialog.py`: nový dialog "Reference Library" s `QSplitter`, read-only tabulkou referencí, preview panelem a akcemi Rename/Delete/Close
- `ui/main_window.py`: nové top-level menu `&Database` s akcí "Reference Library..."
- `tests/test_reference_library_dialog.py`: přidány testy pro empty state, table population, button enable/disable, preview update, rename a delete workflow
- Opraveny validační blokery (`matching/search_engine.py`, `tests/test_spa_reader.py`, `pyproject.toml`)
- 125 testů passing, 3 skipped (RDKit not installed)

### ✅ 2026-04-03 — v0.4.0 task #2 — Pokročilý PDF report
- Ověřeno v kódu: `reporting/pdf_generator.py` používá `ReportOptions(include_structures=...)` a přidává sekci "Molecular structures" pro peaky se SMILES
- `reporting/report_builder.py` už není stub; deleguje na `PDFGenerator` a podporuje `build_with_options()`
- `tests/test_pdf_generator.py`: obsahuje coverage pro `ReportBuilder.build_with_options()` a workflow bez struktur
- Stav při ověření: 117 testů passing, 3 skipped (RDKit), před doplněním task #3 testů

### ✅ 2026-04-02 — v0.3.0 COMPLETE — Match Results UI + Overlay view
- `ui/match_results_panel.py`: QDockWidget s top-10 výsledky, score%, barevné kódování (≥90% zelená, ≥70% oranžová), `candidate_selected` + `import_reference` signály
- `ui/spectrum_widget.py`: `set_overlay_spectra(spectra)` — gray dotted lines pro referenční kandidáty
- `ui/toolbar.py`: "Match Spectrum" action + `match_spectrum` signal
- `ui/main_window.py`: Match Results dock (tabbed s Metadata), `_on_match_spectrum`, `_on_match_candidate_selected`, `_on_import_reference`; `_on_match_candidate_selected` cachuje refs z poslední search operace (ne opakovaný DB hit)
- `tests/test_match_results_panel.py`: 5 nových testů
- 112/112 testů passing — v0.3.0 fully shipped

### ✅ 2026-04-02 — v0.3.0 matching backend (tasks #1-3)
- `storage/database.py`: `reference_spectra` tabulka (BLOB float64), CRUD: `add_reference_spectrum()`, `get_reference_spectra()`, `delete_reference_spectrum()`
- `matching/similarity.py`: `cosine_similarity(a, b)` na aligned vektorech, `STANDARD_GRID` (400–4000 cm⁻¹, 1 cm⁻¹), clipped to [0,1]
- `matching/search_engine.py`: `MatchResult` dataclass, `SearchEngine.load_references()` + `search()` — full pipeline přes `prepare_for_matching` + cosine
- `tests/test_matching.py`: 13 nových testů (DB CRUD, similarity, SearchEngine)
- 107/107 testů passing

### ✅ 2026-04-02 — v0.2.0 review a opravy po Copilot implementaci
- Ověřena implementace Copilota — vše funkční, identifikovány 4 problémy
- **Oprava**: `_load_spectrum()` a `_on_open_project()` nyní volají `self._undo_stack.clear()` — undo stav se čistí při načtení nového projektu/souboru
- **Oprava**: XLSX auto-width smyčka přesunuta mimo per-row loop (O(n²) → O(n))
- **Oprava**: XLSX vibration column logika — `peak.vibration_id is not None` místo fragile string comparison
- **Oprava**: Přidáno 6 nových testů pro project_serializer: FileNotFoundError, no-spectrum project, extra_metadata roundtrip, source_path roundtrip, empty peaks, vibration assignment roundtrip
- 94/94 testů passing
- README, AGENTS.md, CLAUDE.md, copilot-instructions.md aktualizovány pro v0.3.0

### ✅ 2026-04-02 — XLSX export implementován (v0.2.0 task #4)
- `io/xlsx_exporter.py`: kompletní implementace s sheets "Peaks" (position, intensity, label, vibration) a "Spectrum" (wavenumbers, intensities)
- `ui/main_window.py`: `_on_export()` s ExportDialog, `_export_xlsx()` metoda, toolbar "Export" action
- `ui/toolbar.py`: export action přejmenován z "Export PDF" na "Export"
- `tests/test_xlsx_exporter.py`: 3 nové testy (peaks only, with spectrum, empty peaks)
- 88/88 testů passing — v0.2.0 fully shipped
- `core/commands/__init__.py` + `core/commands/peak_commands.py`: `AddPeakCommand`, `DeletePeakCommand`, `AssignPresetCommand` (QUndoCommand subclasses)
- `ui/main_window.py`: `QUndoStack` instance, Edit menu s Ctrl+Z/Ctrl+Y, všechny mutace peaks přes push()
- Detect peaks jako makro — jeden Ctrl+Z vrátí celou detekci
- `tests/test_commands.py`: 4 nové testy (redo/undo pro všechny 3 commands + makro test)
- 77/77 testů passing

### ✅ 2026-04-02 — v0.1.0 MVP COMPLETE — Toolbar modes, keyboard shortcuts, recent files
- `ui/spectrum_widget.py`: `set_tool_mode(mode)` — wires Select/Pan → `pg.ViewBox.PanMode`, Zoom → `pg.ViewBox.RectMode`, Add Peak → PanMode + `_add_peak_mode=True`
- `ui/main_window.py`: Delete shortcut (`_on_delete_peak`), Open Recent submenu (max 5, deduped, from Settings), `_on_tool_mode_changed` → `set_tool_mode(mode)`
- 73/73 testů passing — v0.1.0 fully shipped

### ✅ 2026-04-02 — Vibration Assignment UI dokončen (v0.1.0 prioritní úkoly HOTOVO)
- `ui/vibration_panel.py`: QLineEdit filtr, `highlight_for_peak()` (zelené pozadí #E8F5E9 pro matching presets), `preset_selected` signal na double-click, UserRole data na QListWidgetItem
- `ui/peak_table_widget.py`: přidána `selected_peak() -> Peak | None`, sloupec 3 zobrazuje přiřazenou vibraci
- `ui/main_window.py`: `_on_peak_selected` → `highlight_for_peak()`, `_on_preset_selected` → `peak.vibration_id = preset.db_id`, `peak.label = preset.name`, refresh table+spectrum
- 4 nové testy: signal emission, highlight, filter, label update po přiřazení
- 68/68 testů passing

### ✅ 2026-04-02 — Main Window Docks + Peak Picker + Auto Detection
- `ui/main_window.py`: QDockWidget layout (left=VibrationPanel, bottom=PeakTable, right=MetadataPanel), `_load_spectrum()`, `_on_detect_peaks()`, `_on_export_pdf()`
- `ui/spectrum_widget.py`: PyQtGraph OMNIC-like viewer (bílé pozadí, invertovaná X-osa, peak markers, cursor_moved signal)
- `ui/toolbar.py`: QActionGroup (Select/Zoom/Pan/Add Peak), Detect Peaks, Export PDF akce
- `_on_peak_clicked()`: ruční přidávání peaků kliknutím v grafu

### ✅ 2026-04-02 — OMNIC-like PDF spectrum rendering
- `reporting/spectrum_renderer.py`: Matplotlib render s OMNIC vizuálním stylem — bílé pozadí, 4-stranný box, invertovaná X-osa, ticks direction=in na všech stranách, major/minor ticks, peak annotations (svislá čára + rotovaný text), headless Agg backend
- Podporuje %Transmittance (ylim 0-110) i Absorbance (autoscale) dle y_unit
- `render_to_bytes()` pro in-memory PNG (ReportLab), `render_to_file()` pro PDF

### ✅ 2026-04-02 — PDF Export implementován
- `reporting/pdf_generator.py`: plný ReportLab layout — A4, 2 cm margins, SimpleDocTemplate
- Sekce: header (název + soubor), metadata tabulka, spektrum obrázek, peaks tabulka, footer
- `reporting/spectrum_renderer.py`: přidána `render_to_bytes()` (in-memory PNG via BytesIO), opravena Y-axis label (z y_unit.value), headless Agg backend, peak annotations jako axvline + rotovaný text
- `tests/test_pdf_generator.py`: 5 nových testů (file exists, peaks, no-spectrum ValueError, %PDF magic, PNG bytes)
- scipy nainstalován — peak detection testy odblokované
- 59/59 testů passing

### ✅ 2026-04-02 — Real-file SPA validation + fixture tests
- 3 real Nicolet iS10 .SPA files added to `tests/fixtures/` (public sample data)
- Binary structure fully reverse-engineered (see `tests/fixtures/README_spa_metadata.md`)
- Confirmed: section dir at offset 288 (16-byte entries), fixed params at 564/576/580
- Confirmed: `spa_binary.py` dual-mode OMNIC detection works on all 3 fixtures
- 24 new fixture-parametrized tests, 36 total passing (0 failures)
- Known bug identified: `y_unit` hardcoded as ABSORBANCE but real files are %Transmittance
- Metadata matrix documented with CONFIRMED / DEFERRED / UNKNOWN per field
- Next: parse type-27 text block → extract `acquired_at`, `y_unit`, `resolution_cm`

### ✅ 2026-04-01 — SPABinaryReader implementován
- `io/spa_binary.py`: plná implementace SPA block parsing (sekce type 3 = intensities, type 11 = parameters)
- Podporuje Variant A a B layoutu parametrového bloku, graceful fallback s `UserWarning`
- Validace offsetů, sanity check počtu sekcí, ascending order normalizace
- `tests/test_spa_reader.py`: 4 nové testy se syntetickým SPA blobem (5/5 passing)
- `conftest.py`: meta-path finder workaround pro `io/` package collision se stdlib
- Known risk: `io/` package name stíní stdlib `io` modul — doporučeno přejmenovat na `file_io/` v budoucnu

### ✅ 2026-04-01 — Initial project setup
- Vytvořen GitHub repozitář (private): https://github.com/kubikhavran/ir-spectra-analyzer
- Vytvořena kompletní adresářová struktura dle architektonického dokumentu
- Nastaven `pyproject.toml` (PEP 621) s všemi závislostmi
- Nastaven `.gitignore`, `.pre-commit-config.yaml`, `.python-version`
- Implementovány **core datové modely**: `Spectrum`, `Peak`, `Project`, `VibrationPreset`, `SpectrumMetadata`, `VibrationAssignment`
- Implementovány **processing funkce** (čistě funkcionální): `peak_detection`, `baseline`, `smoothing`, `normalization`, `unit_conversion`, `interpolation`
- Implementována **storage vrstva**: `Database` (SQLite schéma + 12 výchozích vibračních předvoleb), `Settings` (JSON)
- Implementovány **io moduly**: `SPAReader` (3-stage fallback), `SPABinaryReader` (stub/TODO), `CSVExporter`, `XLSXExporter`, `FormatRegistry`
- Implementovány **ui stubs**: `MainWindow`, `SpectrumWidget` (PyQtGraph), `PeakTableWidget`, `VibrationPanel`, `MetadataPanel`, `Toolbar`, `StatusBar`, dialogy, interakce
- Implementovány **reporting stubs**: `PDFGenerator`, `SpectrumRenderer`, `ReportBuilder`
- Implementovány **matching/chemistry stubs** (v0.3+/v0.4+)
- Vytvořeny základní **pytest testy** (3 soubory)
- Vytvořen `README.md` a `LICENSE` (MIT)

---

## Aktivní úkoly (v0.4.0)

### 🔄 In Progress
*(prázdné)*

### ✅ Done (v0.4.0 task #1 — RDKit integrace)
- `chemistry/structure_renderer.py`: `render_smiles_to_png(smiles, size)` — graceful fallback pokud RDKit není nainstalován
- `core/peak.py`: přidáno `smiles: str = ""` pole do Peak dataclass
- `ui/molecule_widget.py`: nový `MoleculeWidget(QLabel)` — zobrazí PNG struktury nebo placeholder text
- `ui/main_window.py`: import MoleculeWidget, "Structure" dock (tabbed s Metadata), `_on_peak_selected` volá `set_smiles(peak.smiles)`
- `storage/project_serializer.py`: smiles pole serializováno/deserializováno
- `pyproject.toml`: `chemistry = ["rdkit>=2024.3.0"]` optional extra
- `tests/test_structure_renderer.py` + `tests/test_molecule_widget.py`: nové testy (rdkit-dependent testy se přeskočí bez rdkit)
- `tests/test_project_serializer.py`: přidán `test_project_serializer_smiles_roundtrip`
- 115 testů passing, 3 skipped (rdkit), 0 failures

### ✅ Done (v0.4.0 task #2 — Pokročilý PDF report)
- `reporting/pdf_generator.py`: přidána `ReportOptions`, volitelná sekce molekulových struktur a render SMILES → PNG pro peaky
- `reporting/report_builder.py`: stub nahrazen funkčním builderem s `build()` a `build_with_options()`
- `tests/test_pdf_generator.py`: coverage pro report builder a variantu bez struktur

### ✅ Done (v0.4.0 task #3 — Reference library management UI)
- `storage/database.py`: `rename_reference_spectrum()` + podpora `Database(":memory:")` pro testy
- `ui/dialogs/reference_library_dialog.py`: browse / rename / delete workflow, preview s metadaty a počtem bodů
- `ui/main_window.py`: menu `&Database` → "Reference Library..."
- `tests/test_reference_library_dialog.py`: 8 testů pro dialog a akce

### 📋 Todo — Prioritní (v0.4.0)

1. ~~**RDKit integrace**~~ ✅ Done
2. ~~**Pokročilý PDF report**~~ ✅ Done
3. ~~**Reference library management UI**~~ ✅ Done
4. ~~**Batch processing**~~ ✅ Done

### 📋 Todo — Nízká priorita (přetaženo)
- [ ] PyInstaller packaging script pro Windows .exe
- [ ] "Page N of M" v PDF footer (ReportLab two-pass pattern)
- [ ] `io/` → `file_io/` přejmenování (eliminuje stdlib name collision)

---

## Known Bugs & Issues

*(žádné — nový projekt)*

---

## Architektonická rozhodnutí (ADR)

### ADR-001: PyQtGraph místo Matplotlib pro interaktivní viewer
- **Rozhodnutí:** Hlavní spektrální viewer používá PyQtGraph
- **Důvod:** >1000 FPS pro interaktivní grafy, nativní Qt integrace, lepší interaktivita pro peak picking
- **Kompromis:** Matplotlib je stále použit pro statický render při PDF exportu (publication quality)

### ADR-002: SpectroChemPy jako primární SPA parser
- **Rozhodnutí:** `spectrochempy.read_omnic()` jako první stupeň, vlastní binární fallback jako stupeň 2
- **Důvod:** Nejrobustnější open-source SPA implementace, aktivně udržovaná
- **Riziko:** SPA je proprietární formát bez dokumentace — u exotických modelů spektrometrů může selhat

### ADR-003: SQLite pro lokální persistenci
- **Rozhodnutí:** SQLite pro projekty a vibration presets, JSON pro uživatelské nastavení
- **Důvod:** Zero-configuration, single file, vestavěný v Pythonu, ACID compliance

### ADR-004: ReportLab pro PDF export
- **Rozhodnutí:** ReportLab s vlastním template systémem
- **Důvod:** Nejflexibilnější Python PDF knihovna, fine-grained control nad layoutem, production-ready

---

## Závislosti a integrace

### Python packages (viz pyproject.toml)
- `PySide6` — GUI framework
- `PyQtGraph` — interaktivní spectral viewer
- `NumPy` + `SciPy` — numerické výpočty, peak detection
- `SpectroChemPy` — SPA file parser
- `ReportLab` — PDF generation
- `Matplotlib` — statický render pro PDF
- `openpyxl` — XLSX export

### Budoucí závislosti (v0.3+)
- `RDKit` — cheminformatika, struktura molekul
- `scikit-learn` — ML pro spectral matching

---

## Styl kódu

- **Formatter:** ruff (nahrazuje black + isort)
- **Linter:** ruff + mypy (strict type hints)
- **Docstrings:** Google style
- **Typy:** Povinné pro všechny public funkce a metody
- **Testy:** pytest + pytest-qt

---

## Poznámky pro AI agenty

### Jak pracovat na tomto projektu
1. **Vždy nejdříve přečti** tento soubor (`PROJECT_STATE.md`) a `IR_Spectral_Software_Architecture.md`
2. **Vezmi si úkol** z sekce "Todo — Prioritní" a přesuň ho do "In Progress"
3. **Pracuj** na úkolu. Sleduj architektonický dokument.
4. **Po dokončení:** aktualizuj tento soubor — přidej milestone, přesuň úkol do Done, zapiš zjištěné bugy
5. **Před každým commitem:** spusť `ruff check . && mypy . && pytest`

### Doporučené MCP a nástroje
Před zahájením práce vždy zvaž, zda lze využít dostupné MCP servery:

- **GitHub MCP** — pro správu repozitáře, issues, PR (`gh` CLI je dostupné)
- **Memory/Context MCP** — pro udržení kontextu přes sessions
- **Figma/UI MCP** — pro inspiraci UI komponent a layoutů (Figma MCP je dostupný)
- **Web Search** — pro aktuální dokumentaci PySide6, PyQtGraph, SpectroChemPy

### Konvence commitů
```
feat: přidána nová funkce
fix: oprava chyby
refactor: refaktorování bez změny funkcionality
test: přidání nebo oprava testů
docs: dokumentace
chore: build systém, závislosti
```

### Klíčová architektonická pravidla (připomenutí)
- **UI vrstva NIKDY neprovádí výpočty ani I/O** — deleguje na core modely
- **Processing je čistě funkcionální** — vstup: numpy arrays, výstup: numpy arrays
- **Project je single source of truth** — drží veškerý stav analýzy
- **FormatRegistry** je plug-in architektura — nové formáty přidávej bez změny zbytku kódu

---

## Kontakt / Kontext
- **Projekt:** Osobní laboratorní nástroj pro analýzu IR spekter (nahrazení papírové interpretace)
- **Primární uživatel:** Analytická chemie laboratoř, každodenní použití s OMNIC .spa soubory
- **Prostředí:** Windows desktop (primární), možná Linux

---
*Tento soubor je generován a udržován AI agenty. Poslední aktualizace: viz git log.*
