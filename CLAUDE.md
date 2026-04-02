# IR Spectra Analyzer — Claude Code Agent Instructions

## TL;DR pro každé spuštění

Tento projekt je desktopový vědecký software pro analýzu IR spekter (Python + PySide6 + PyQtGraph).

**Před jakoukoliv prací udělej toto:**
1. Přečti `PROJECT_STATE.md` — aktuální stav, roadmap, aktivní úkoly, known bugs
2. Přečti `IR_Spectral_Software_Architecture.md` — architektonický návrh (source of truth pro strukturu)
3. Vezmi si úkol z "Todo — Prioritní" v `PROJECT_STATE.md` a přesuň ho do "In Progress"
4. Po dokončení práce aktualizuj `PROJECT_STATE.md`

---

## Kontext projektu

- **Co to je:** Nástroj pro analytické chemistry v laboratoři — nahrazuje papírovou interpretaci IR spekter
- **Primární workflow:** otevřít OMNIC `.spa` soubor → zobrazit spektrum → označit peaky → přiřadit vibrační pásy → exportovat PDF report
- **Prostředí uživatele:** Windows desktop (primární), Python 3.11+

## Stack

| Vrstva | Technologie |
|--------|-------------|
| GUI | PySide6 (Qt 6) |
| Spektrální viewer | PyQtGraph |
| Numerika | NumPy + SciPy |
| SPA parser | vlastní `io/spa_binary.py` (dual-mode OMNIC + compact) |
| Persistence | SQLite (`storage/database.py`) + JSON (`storage/settings.py`) |
| PDF reporting | ReportLab + Matplotlib (OMNIC-like render) |
| Formatter/Linter | ruff + mypy (strict) |
| Testy | pytest + pytest-qt |

## Klíčová architektonická pravidla

1. **UI vrstva (ui/) NIKDY neprovádí výpočty ani I/O** — deleguje na core modely přes Qt signály
2. **Processing (processing/) je čistě funkcionální** — vstup: numpy arrays, výstup: numpy arrays, žádný stav
3. **Project (core/project.py) je single source of truth** — drží spektrum + peaky + metadata
4. **FormatRegistry (io/format_registry.py) je plug-in architektura** — nové formáty bez změny zbytku

## Aktuální stav (verze 0.3.0 — COMPLETE)

v0.3.0 je kompletní. 112 testů passing. Detaily viz `PROJECT_STATE.md`.

**Co je implementováno (celkem):**
- SPA binary parser (`io/spa_binary.py`) — dual-mode OMNIC/compact, type-27 metadata extraction
- PyQtGraph spektrální viewer s OMNIC vizuálním stylem + tool modes + overlay křivky (`set_overlay_spectra()`)
- MainWindow s kompletním QDockWidget layout — VibrationPanel, PeakTable, MetadataPanel, MatchResultsPanel
- Toolbar: tool modes, Detect Peaks, Correct Baseline, Export, Match Spectrum
- QUndoStack — AddPeak, DeletePeak, AssignPreset, CorrectBaseline (Ctrl+Z/Ctrl+Y)
- Rubber-band baseline correction, Project save/load (JSON `.irproj`), XLSX/PDF/CSV export
- **Spectral matching**: `reference_spectra` SQLite table, `Database.add_reference_spectrum()`, cosine similarity na fixed grid (400–4000 cm⁻¹, 1 cm⁻¹), `SearchEngine`, `MatchResultsPanel` s score% + barevným kódováním, overlay view pro referenční kandidáty
- Import referenčního spektra ze SPA souboru přes toolbar → dialog

**Aktuálně pracujeme na: v0.4.0 — Chemie + Pokročilý Reporting**

## Prioritní úkoly pro v0.4.0

V pořadí priority (viz `PROJECT_STATE.md` pro detaily):
1. **RDKit integrace** — `chemistry/structure_renderer.py`, SMILES → PNG, MoleculeWidget v UI
2. **Pokročilý PDF report** — molekulová struktura v reportu, `reporting/report_builder.py`
3. **Reference library management UI** — dialog pro správu referenční databáze
4. **Batch processing** — hromadný import SPA složky, bulk PDF export

## Technické poznámky pro agenty

### io/ package naming conflict
`io/` stíní stdlib `io`. Obcházeno přes:
- `conftest.py`: `sys.meta_path` finder který dává prioritu projektu
- `io/__init__.py`: re-exportuje `_io` C extension symboly pro ReportLab

Technický dluh: přejmenovat na `file_io/` v budoucnu (v0.2.0 nízká priorita).

### SPA parser dual-mode
`io/spa_binary.py` detekuje OMNIC magic `b"Spectral Data File"` na bytech 0-17:
- **OMNIC mode**: 16-byte directory entries od offsetu 288, fixed params na 564/576/580, type-27 text blok pro metadata
- **Compact mode**: 12-byte entries, pro syntetické testovací bloby

### Testovací fixtures
`tests/fixtures/` obsahuje 3 reálné Nicolet iS10 `.SPA` soubory (55 587 bodů, 650–4000 cm⁻¹, %Transmittance).
Test `test_real_spa_known_wavenumber_range` je specifický pro tento instrument — re-validuj s vlastními soubory.

## Workflow pro commity

```bash
# Před commitem vždy:
ruff check . --fix && ruff format . && pytest

# Konvence:
feat: přidána nová funkce
fix: oprava chyby
refactor: refaktorování
test: testy
docs: dokumentace
chore: build, závislosti
```

## Instalace

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
python main.py
```
