# IR Spectra Analyzer — Project State

> **INSTRUKCE PRO AI AGENTY:** Před zahájením jakékoliv práce přečti tento soubor celý. Po dokončení práce ho aktualizuj — zapiš co jsi udělal, jaké bugs jsi objevil, a co je dalším krokem. Tento soubor je živý dokument a single source of truth pro stav projektu.

## Metadata projektu

- **Název:** IR Spectra Analyzer
- **Jazyk:** Python 3.11+
- **GUI:** PySide6 + PyQtGraph
- **Repozitář:** https://github.com/kubikhavran/ir-spectra-analyzer (private)
- **Hlavní architektura:** viz `IR_Spectral_Software_Architecture.md`
- **Poslední aktualizace:** 2026-04-01
- **Aktuálně pracuje:** nikdo

---

## Aktuální verze: 0.0.1 (Initial Setup)

## Roadmap

| Verze | Název | Status | Popis |
|-------|-------|--------|-------|
| 0.1.0 | Základní Viewer + Ruční Interpretace | 🔄 In Progress | MVP — načtení SPA, zobrazení spektra, peak picking, export PDF |
| 0.2.0 | Profesionální Workflow | ⏳ Planned | Undo/Redo, baseline, projekt soubory, XLSX export |
| 0.3.0 | Databázové Porovnávání | ⏳ Planned | Spectral matching, similarity algoritmy |
| 0.4.0 | Chemie + Pokročilý Reporting | ⏳ Planned | RDKit, Ketcher editor, profesionální reporty |

---

## Dokončené milestones

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

## Aktivní úkoly (v0.1.0)

### 🔄 In Progress
*(prázdné)*

### 📋 Todo — Prioritní
- [ ] **SPABinaryReader** — implementovat `io/spa_binary.py` s plným SPA block parsing (aktuálně NotImplementedError)
- [ ] **PDF Export** — implementovat `reporting/pdf_generator.py` s ReportLab layoutem (tabulka peaků, spektrum obrázek, metadata)
- [ ] **Main Window Docks** — přidat dockable QDockWidget panely do `MainWindow` (SpectrumWidget + PeakTable + VibrationPanel + MetadataPanel)
- [ ] **Peak Picker Integration** — propojit `PeakPicker` s `SpectrumWidget` click eventem via Qt signály
- [ ] **Auto Peak Detection UI** — tlačítko "Detect Peaks" volající `processing/peak_detection.py`, výsledky do `Project.peaks`
- [ ] **Vibration Assignment UI** — propojit `VibrationPanel` → `PeakTableWidget` pro přiřazení předvoleb k peakům

### 📋 Todo — Nízká priorita (v0.1.0)
- [ ] Toolbar s tool modes (Select / Zoom / Pan / Add Peak / Assign) — propojit s `SpectrumWidget`
- [ ] Status bar s kurzorovou pozicí (napojit na `SpectrumWidget` mouse move event)
- [ ] Recent files v menu (načíst z `Settings`)
- [ ] Keyboard shortcuts (Ctrl+O, Delete peak, Ctrl+Z)
- [ ] PyInstaller packaging script pro Windows .exe

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
