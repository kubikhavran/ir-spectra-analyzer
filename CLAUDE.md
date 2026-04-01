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
| SPA parser | SpectroChemPy + vlastní binary fallback |
| Persistence | SQLite (`storage/database.py`) + JSON settings |
| PDF reporting | ReportLab + Matplotlib |
| Formatter/Linter | ruff + mypy (strict) |
| Testy | pytest |

## Klíčová architektonická pravidla

1. **UI vrstva (ui/) NIKDY neprovádí výpočty ani I/O** — deleguje na core modely přes Qt signály
2. **Processing (processing/) je čistě funkcionální** — vstup: numpy arrays, výstup: numpy arrays, žádný stav
3. **Project (core/project.py) je single source of truth** — drží spektrum + peaky + metadata
4. **FormatRegistry (io/format_registry.py) je plug-in architektura** — nové formáty bez změny zbytku

## Aktuální stav (verze 0.0.1)

Projekt je v iniciálním setupu. Veškerá adresářová struktura a stub moduly jsou vytvořeny.
Detaily viz `PROJECT_STATE.md`.

## Prioritní úkoly pro v0.1.0 MVP

V pořadí priority:
1. **PDF Export** (`reporting/pdf_generator.py`) — ReportLab layout s tabulkou peaků + obrázkem spektra
2. **Main Window Docks** (`ui/main_window.py`) — přidat QDockWidget panely
3. **Peak Picker Integration** — propojit klikání v grafu s přidáváním peaků do Project
4. **Auto Peak Detection UI** — tlačítko volající `processing/peak_detection.py`

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

## Instalace (pro referenci)

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
python main.py
```
