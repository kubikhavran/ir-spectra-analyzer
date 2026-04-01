# Architektura IR Spektrálního Software — Kompletní Technický Návrh

**Autor:** Claude (Senior Software Architect)
**Datum:** 1. dubna 2026
**Verze dokumentu:** 1.0

---

## A. Doporučený Technologický Stack

### Hlavní doporučení: Python 3.11+ / PySide6 / PyQtGraph

| Vrstva | Technologie | Důvod |
|--------|-------------|-------|
| **Jazyk** | Python 3.11+ | Nejlepší ekosystém pro scientific computing, nejrychlejší cesta k funkčnímu MVP |
| **GUI framework** | PySide6 (Qt 6) | Nativní desktop look, profesionální widgety, oficiální Qt binding (LGPL) |
| **Spektrální rendering** | PyQtGraph | >1000 FPS, nativní Qt integrace, interaktivní anotace, scientific-grade |
| **Numerické výpočty** | NumPy + SciPy | De facto standard pro scientific Python, FFT, peak detection, baseline fitting |
| **SPA parser** | SpectroChemPy-OMNIC + vlastní fallback | Nejrobustnější existující parser, doplněný vlastním binárním čtením |
| **Lokální data** | SQLite (via `sqlite3`) + JSON config | Projekty a předvolby v SQLite, uživatelské nastavení v JSON |
| **PDF reporting** | ReportLab + Matplotlib (statický export) | ReportLab pro layout reportu, Matplotlib pro publication-quality statický obrázek spektra |
| **Chemie (budoucí)** | RDKit + Ketcher (embedded) | RDKit pro backend cheminformatiky, Ketcher pro interaktivní editor struktur |
| **Packaging** | PyInstaller nebo cx_Freeze | Distribuce jako standalone .exe / .app bez nutnosti instalovat Python |

### Proč PySide6 a ne PyQt6?

PySide6 je **oficiální Qt for Python binding** od Qt Company pod licencí LGPL. PyQt6 je pod GPL nebo komerční licencí (Riverbank Computing). Pro software, který může být v budoucnu distribuován nebo komercializován, je PySide6 výrazně bezpečnější volba. API je prakticky identické.

---

## B. Porovnání Variant

### Varianta 1: Python + PySide6 + PyQtGraph (DOPORUČENO)

**Výhody:**
- Nejrychlejší cesta k funkčnímu MVP (týdny, ne měsíce)
- Python má nejlepší ekosystém pro scientific computing — NumPy, SciPy, scikit-learn, RDKit
- SpectroChemPy (nejlepší SPA parser) je v Pythonu
- PyQtGraph dosahuje >1000 FPS pro interaktivní grafy s desítkami tisíc bodů — pro IR spektra (typicky 2000–8000 bodů) je to masivní rezerva
- PySide6 dává plně nativní desktop UI s profesionálním vzhledem
- ReportLab + Matplotlib pro PDF reporting jsou mature a production-ready
- RDKit pro budoucí cheminformatiku je Python-first
- Jeden jazyk pro celý projekt = jednodušší údržba, debugging, refactoring

**Nevýhody:**
- Python je pomalejší než C++ pro čistě výpočetní úlohy (ale NumPy/SciPy jsou napsané v C/Fortran)
- Distribuce standalone aplikace vyžaduje PyInstaller/cx_Freeze (výsledný balík ~150–300 MB)
- GIL (Global Interpreter Lock) může teoreticky limitovat paralelismus — řešitelné multiprocessingem nebo uvolněním GIL v NumPy operacích

**Verdikt pro MVP:** Ideální. Funkční prototyp za 2–4 týdny.
**Verdikt pro dlouhodobý vývoj:** Velmi dobrý. Hot paths lze optimalizovat přes Cython/C extensions.
**Verdikt pro kvalitu spektrálního vieweru:** Vynikající. PyQtGraph je navržený přesně pro tento typ aplikace.

---

### Varianta 2: C++ + Qt 6 + QCustomPlot

**Výhody:**
- Maximální výkon — nativní kompilovaný kód
- QCustomPlot je excelentní C++ knihovna pro scientific plotting
- Nejmenší výsledný binární soubor
- Žádný overhead interpretovaného jazyka
- Qt 6 v C++ je nejflexibilnější GUI toolkit na trhu

**Nevýhody:**
- Vývoj 3–5× pomalejší než v Pythonu
- Žádný přímý přístup ke SpectroChemPy (SPA parser) — nutné portovat nebo volat Python subprocess
- Scientific computing v C++ je výrazně náročnější (Eigen místo NumPy, žádný SciPy ekvivalent)
- RDKit má C++ API, ale je komplexnější na integraci
- Memory management, build systém, cross-platform kompilace — vše je náročnější
- Pro IR spektra (tisíce bodů) je výkonnostní rozdíl oproti Python+PyQtGraph neměřitelný

**Verdikt pro MVP:** Nevhodné — příliš pomalý vývoj pro jeden-vývojářský projekt.
**Verdikt pro dlouhodobý vývoj:** Technicky nejlepší, ale prakticky nerealizovatelné bez týmu.
**Verdikt pro kvalitu spektrálního vieweru:** Marginálně lepší než PyQtGraph, ale rozdíl je pro tento use case zanedbatelný.

---

### Varianta 3: C# / .NET + WPF nebo Avalonia

**Výhody:**
- Dobrý desktop framework (WPF na Windows, Avalonia cross-platform)
- Silný typový systém, dobrý tooling
- SciSharp (NumSharp, TorchSharp) poskytuje scientific computing
- OxyPlot pro scientific charting

**Nevýhody:**
- WPF je Windows-only (Avalonia je cross-platform, ale méně mature)
- Scientific computing ekosystém v .NET je výrazně slabší než v Pythonu
- Žádný SPA parser — nutné psát od nuly
- RDKit nemá oficiální .NET bindings
- OxyPlot je méně flexibilní než PyQtGraph pro interaktivní scientific plotting
- Komunita pro scientific .NET je malá

**Verdikt:** Slepá cesta pro scientific software. .NET exceluje v enterprise aplikacích, ne v laboratorním software.

---

### Varianta 4: Rust + egui/iced/Slint

**Výhody:**
- Memory safety bez GC, excelentní výkon
- Moderní jazyk s rostoucím ekosystémem
- egui/iced nabízejí cross-platform GUI

**Nevýhody:**
- GUI ekosystém je stále nezralý — žádný z Rust GUI frameworků nedosahuje maturity Qt
- Scientific computing v Rustu je v raném stadiu (ndarray existuje, ale nemá šíři NumPy/SciPy)
- Žádný SPA parser, žádný RDKit binding
- Vývoj bude nejpomalejší ze všech variant
- Pro scientific desktop aplikaci je Rust předčasná optimalizace

**Verdikt:** Technologicky zajímavé, ale pro tento projekt prakticky nevhodné. Za 3–5 let se situace může změnit.

---

### Varianta 5: Electron / Web stack (React + Plotly)

**Výhody:**
- Rychlý vývoj UI
- Plotly/D3.js pro vizualizace

**Nevýhody:**
- Vysoká spotřeba paměti (Chromium runtime)
- Plotly má problémy s >50 000 body v interaktivním režimu
- Web rendering nikdy nebude vypadat jako nativní laboratorní software
- Zoom/pan v canvasu nikdy nedosáhne kvality nativního Qt renderingu
- Pro scientific desktop software je to architektonický anti-pattern

**Verdikt:** Nedoporučuji. Toto je přesně ten typ projektu, kde web stack selhává.

---

## C. Architektura Projektu

### Hlavní moduly

```
SpectraApp/
├── main.py                      # Entry point, QApplication setup
├── app/
│   ├── __init__.py
│   ├── application.py           # Hlavní aplikační třída, lifecycle
│   └── config.py                # Globální konfigurace, cesty
│
├── core/                        # ========== DOMÉNOVÁ LOGIKA ==========
│   ├── __init__.py
│   ├── spectrum.py              # Datový model spektra (Spectrum class)
│   ├── peak.py                  # Datový model peaku (Peak class)
│   ├── project.py               # Projekt = spektrum + peaky + metadata + interpretace
│   ├── vibration_presets.py     # Správa předvoleb vibrací
│   ├── metadata.py              # Metadata spektra
│   └── interpretation.py        # Přiřazení vibrací k peakům
│
├── io/                          # ========== VSTUP/VÝSTUP ==========
│   ├── __init__.py
│   ├── spa_reader.py            # SPA parser (SpectroChemPy + vlastní fallback)
│   ├── spa_binary.py            # Low-level binární čtení SPA
│   ├── csv_exporter.py          # Export tabulky do CSV/TXT
│   ├── xlsx_exporter.py         # Export do XLSX (openpyxl)
│   ├── project_io.py            # Ukládání/načítání projektů (.irproj)
│   └── format_registry.py       # Registr podporovaných formátů (rozšiřitelný)
│
├── processing/                  # ========== ZPRACOVÁNÍ SIGNÁLU ==========
│   ├── __init__.py
│   ├── baseline.py              # Korekce baseline (polynomial, rubber band, ALS)
│   ├── smoothing.py             # Savitzky-Golay, moving average
│   ├── normalization.py         # Normalizace spekter
│   ├── peak_detection.py        # Automatická detekce peaků (SciPy find_peaks)
│   ├── unit_conversion.py       # Transmittance ↔ Absorbance, wavenumber ↔ wavelength
│   └── interpolation.py         # Interpolace pro porovnávání spekter
│
├── matching/                    # ========== DATABÁZOVÉ POROVNÁVÁNÍ (v0.3+) ==========
│   ├── __init__.py
│   ├── similarity.py            # Algoritmy podobnosti (korelace, Euclidean, SAM, NLC)
│   ├── database.py              # Správa spektrální databáze
│   ├── search_engine.py         # Vyhledávání podobných spekter
│   └── preprocessing.py         # Preprocessing pro matching (normalizace, resampling)
│
├── chemistry/                   # ========== CHEMINFORMATIKA (v0.4+) ==========
│   ├── __init__.py
│   ├── structure_model.py       # Chemická struktura (SMILES, MOL)
│   ├── structure_renderer.py    # Renderování struktury (RDKit)
│   └── editor_bridge.py         # Bridge pro embedded Ketcher editor
│
├── reporting/                   # ========== REPORTING ==========
│   ├── __init__.py
│   ├── pdf_generator.py         # Generování PDF reportu (ReportLab)
│   ├── spectrum_renderer.py     # Statický render spektra pro PDF (Matplotlib)
│   ├── report_template.py       # Šablona reportu
│   └── report_builder.py        # Sestavení kompletního reportu
│
├── ui/                          # ========== GRAFICKÉ ROZHRANÍ ==========
│   ├── __init__.py
│   ├── main_window.py           # Hlavní okno aplikace
│   ├── spectrum_widget.py       # Spektrální viewer (PyQtGraph-based)
│   ├── peak_table_widget.py     # Tabulka peaků
│   ├── vibration_panel.py       # Panel předvoleb vibrací
│   ├── metadata_panel.py        # Panel metadat
│   ├── toolbar.py               # Hlavní toolbar
│   ├── status_bar.py            # Stavový řádek
│   ├── dialogs/
│   │   ├── __init__.py
│   │   ├── vibration_editor.py  # Editor předvoleb vibrací
│   │   ├── metadata_editor.py   # Editor metadat
│   │   ├── export_dialog.py     # Dialog exportu
│   │   └── about_dialog.py
│   ├── interactions/
│   │   ├── __init__.py
│   │   ├── peak_picker.py       # Interaktivní přidávání peaků klikáním
│   │   ├── peak_editor.py       # Editace peaků (drag, resize, delete)
│   │   ├── zoom_handler.py      # Zoom rectangle, scroll zoom
│   │   └── pan_handler.py       # Pan (drag pozadí)
│   └── styles/
│       ├── __init__.py
│       ├── theme.py             # Barevné schéma, fonty
│       └── scientific_style.py  # Styl os, tick marks, grid
│
├── storage/                     # ========== PERSISTENCE ==========
│   ├── __init__.py
│   ├── database.py              # SQLite databáze (projekty, předvolby)
│   ├── settings.py              # Uživatelské nastavení (JSON)
│   └── migrations.py            # Migrace DB schématu
│
└── utils/                       # ========== UTILITY ==========
    ├── __init__.py
    ├── units.py                 # Jednotky, konstanty
    ├── math_utils.py            # Pomocné matematické funkce
    └── file_utils.py            # Práce se soubory
```

### Datové toky

```
┌─────────────────────────────────────────────────────────────────────┐
│                         UŽIVATELSKÁ AKCE                            │
│  (otevření .spa, kliknutí na peak, přiřazení vibrace, export PDF)  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          UI VRSTVA (ui/)                             │
│  main_window ← spectrum_widget ← peak_table ← vibration_panel      │
│                                                                     │
│  UI vrstva NIKDY neprovádí výpočty ani I/O.                        │
│  Pouze zobrazuje data a předává uživatelské akce dolů.             │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ signály / callbacky
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      CORE VRSTVA (core/)                            │
│  Spectrum, Peak, Project, VibrationPresets, Interpretation          │
│                                                                     │
│  Drží aktuální stav projektu.                                      │
│  Validuje data.                                                    │
│  Emituje změnové signály pro UI.                                   │
└──────────┬──────────────────────────────┬───────────────────────────┘
           │                              │
           ▼                              ▼
┌──────────────────────┐    ┌──────────────────────────────────────────┐
│    IO VRSTVA (io/)   │    │       PROCESSING VRSTVA (processing/)   │
│                      │    │                                          │
│  spa_reader          │    │  baseline, smoothing, peak_detection,   │
│  csv_exporter        │    │  normalization, unit_conversion          │
│  project_io          │    │                                          │
│  format_registry     │    │  Čistě funkcionální — vstup: numpy      │
│                      │    │  array, výstup: numpy array.             │
└──────────────────────┘    └──────────────────────────────────────────┘
           │                              │
           ▼                              ▼
┌──────────────────────┐    ┌──────────────────────────────────────────┐
│  STORAGE (storage/)  │    │      REPORTING (reporting/)              │
│                      │    │                                          │
│  SQLite DB           │    │  pdf_generator, spectrum_renderer,       │
│  JSON settings       │    │  report_template, report_builder         │
└──────────────────────┘    └──────────────────────────────────────────┘
```

### Klíčové architektonické principy

1. **Striktní oddělení vrstev.** UI vrstva nikdy přímo nevolá I/O nebo processing. Vše prochází přes core modely.

2. **Datový model je single source of truth.** `Project` třída drží veškerý stav — spektrum, peaky, metadata, interpretace. UI se na něj napojuje přes Qt signály.

3. **Processing je čistě funkcionální.** Funkce v `processing/` berou numpy arrays a vracejí numpy arrays. Žádný side-effect, žádný stav. Snadno testovatelné.

4. **IO je plug-in architektura.** `format_registry.py` umožňuje registrovat nové formáty (SPA, SPC, JCAMP-DX, CSV...) bez změny zbytku kódu.

5. **Undo/Redo od začátku.** Core modely implementují command pattern — každá akce (přidání peaku, změna labelu, přiřazení vibrace) je reversibilní operace.

---

## D. Řešení .SPA Souboru

### Současný stav

SPA je **proprietární binární formát** Thermo Fisher Scientific. Neexistuje oficiální dokumentace. Veškeré existující parsery jsou založeny na reverse engineeringu.

### Co lze spolehlivě extrahovat

| Data | Spolehlivost | Zdroj |
|------|-------------|-------|
| Spektrální data (wavenumber + absorbance/transmittance) | **Vysoká** | SpectroChemPy, spa-on-python |
| Titul/název spektra | **Vysoká** | SpectroChemPy |
| Datum akvizice | **Vysoká** | SpectroChemPy |
| Spektrální jednotky (abs/trans/reflectance) | **Vysoká** | SpectroChemPy |
| X-axis jednotky (cm⁻¹, nm, μm) | **Vysoká** | SpectroChemPy |
| Textová metadata (komentáře, popis) | **Střední** | Závisí na tom, co uživatel zapsal v OMNIC |
| Historie zpracování | **Nízká** | Částečně, ne vždy parsovatelná |

### Co pravděpodobně NEJDE spolehlivě extrahovat

| Data | Problém |
|------|---------|
| **Peak picks / označené pásy** | OMNIC ukládá peak picks jako součást "processing history" v proprietárním binárním bloku. Žádný open-source parser toto spolehlivě neextrahuje. |
| **Baseline korekce** | Parametry baseline korekce nejsou v parsovatelné formě. |
| **Uživatelské anotace** | Textové anotace přidané v OMNIC (šipky, komentáře) nejsou v žádném známém parseru podporovány. |
| **Mikroskopické snímky** | Embedded obrázky ze stage kamery — žádný parser je neextrahuje. |
| **Experiment nastavení** | Uloženo v separátních .exp/.expx souborech, ne v .spa. |

### Doporučená strategie pro SPA import

```python
# Pseudokód importní vrstvy

class SPAImporter:
    """Třístupňový fallback systém pro čtení SPA souborů."""

    def read(self, filepath: str) -> ImportResult:

        # Stupeň 1: SpectroChemPy (nejrobustnější)
        try:
            result = self._read_spectrochempy(filepath)
            if result.is_valid():
                return result
        except Exception:
            pass

        # Stupeň 2: Vlastní binární parser (lightweight, méně metadat)
        try:
            result = self._read_custom_binary(filepath)
            if result.is_valid():
                return result
        except Exception:
            pass

        # Stupeň 3: spa-on-python (minimální, ale funkční)
        try:
            result = self._read_spa_on_python(filepath)
            if result.is_valid():
                return result
        except Exception:
            pass

        raise SPAReadError(f"Nepodařilo se přečíst {filepath}")
```

### Peak picks — realistické řešení

Protože peak picks z SPA nelze spolehlivě extrahovat, architektura počítá se dvěma cestami:

1. **Automatická detekce peaků** (`scipy.signal.find_peaks`) při importu — nabídne uživateli detekované peaky, které může potvrdit/upravit.
2. **Ruční peak picking** — uživatel klikne do spektra a přidá peak ručně. Toto je primární workflow.

### Rozšiřitelnost importní vrstvy

`format_registry.py` umožňuje přidat nové formáty:

```python
class FormatRegistry:
    _readers: dict[str, type[SpectrumReader]] = {}

    @classmethod
    def register(cls, extension: str, reader_class: type[SpectrumReader]):
        cls._readers[extension.lower()] = reader_class

    @classmethod
    def read(cls, filepath: str) -> ImportResult:
        ext = Path(filepath).suffix.lower()
        reader = cls._readers.get(ext)
        if not reader:
            raise UnsupportedFormatError(ext)
        return reader().read(filepath)

# Registrace formátů
FormatRegistry.register('.spa', SPAReader)
FormatRegistry.register('.spc', SPCReader)       # budoucí
FormatRegistry.register('.jdx', JCAMPDXReader)   # budoucí
FormatRegistry.register('.csv', CSVReader)        # budoucí
```

---

## E. Přesný MVP Plán

### Verze 0.1 — "Základní Viewer + Ruční Interpretace"

**Cíl:** Nahradit papírovou interpretaci. Uživatel otevře SPA, vidí spektrum, přidá peaky, přiřadí vibrace, exportuje PDF.

**Funkce:**
- Načtení .spa souboru (SpectroChemPy + fallback)
- Zobrazení spektra (PyQtGraph) s profesionálním stylem os
- Automatická detekce peaků (scipy.signal.find_peaks) při importu
- Ruční přidávání peaků klikáním do spektra
- Smazání peaku (klik pravým + Delete)
- Tabulka peaků (pozice, intenzita, přiřazená vibrace)
- Předvolby vibrací (hardcoded základní sada + možnost přidávat vlastní)
- Rychlé přiřazování: vyber předvolbu → klikni na peak → hotovo
- Základní metadata (název, číslo vzorku, typ měření, poznámky) — ruční zadání
- Export PDF s grafem spektra + tabulkou peaků + metadaty
- Export tabulky jako CSV
- Zoom (obdélníkový výběr + scroll kolečko) a pan (prostřední tlačítko / shift+drag)

**Časový odhad:** 3–5 týdnů pro jednoho vývojáře.

---

### Verze 0.2 — "Profesionální Workflow"

**Cíl:** Posunout UX na úroveň, kde je software pohodlnější než OMNIC pro interpretaci.

**Nové funkce:**
- Metadata parsovaná ze SPA (co je dostupné)
- Drag & drop peaků (přesun pozice v grafu)
- Editace peak labelů přímo v grafu (double-click → inline edit)
- Smart label placement (automatické vyhýbání se překryvům)
- Uživatelské předvolby vibrací uložené v SQLite
- Undo/Redo (Ctrl+Z / Ctrl+Y)
- Přepínání Absorbance ↔ Transmittance
- Baseline korekce (rubber band, polynomial)
- Ukládání/načítání projektů (.irproj — vlastní formát, JSON+binary)
- Vylepšený PDF report (lepší layout, volitelné sekce)
- Export XLSX (openpyxl)
- Keyboard shortcuts pro časté akce
- Recent files menu

**Časový odhad:** 4–6 týdnů.

---

### Verze 0.3 — "Databázové Porovnávání"

**Cíl:** Porovnat spektrum s referenční databází a najít podobné látky.

**Nové funkce:**
- Import složky spekter jako lokální databáze
- Indexování databáze (SQLite + numpy arrays)
- Preprocessing pipeline pro matching (normalizace, interpolace na společnou osu)
- Similarity algoritmy: korelační koeficient, normalized Euclidean distance, SAM
- Výsledky matchingu: seřazený seznam kandidátů s skóre
- Overlay dvou spekter pro vizuální porovnání
- Filtrování databáze podle metadat
- Batch import SPA souborů

**Časový odhad:** 6–8 týdnů.

---

### Verze 0.4 — "Chemie + Pokročilý Reporting"

**Nové funkce:**
- Integrace RDKit pro rendering chemických struktur
- Embedded Ketcher editor (QWebEngineView) pro kreslení struktur
- Přiřazení chemické struktury k projektu
- Profesionální report: spektrum + peak table + struktura + srovnání s databází
- Šablony reportů (uživatel si může přizpůsobit layout)
- JCAMP-DX import (.jdx/.dx)
- SPC import (.spc)

---

### Co NEDĚLAT příliš brzy

- **AI-assisted interpretaci** — dokud není solidní manuální workflow, AI vrstva nemá na čem stavět
- **Cloud synchronizaci** — desktop-first, lokální data
- **Multi-spektrum editor** (více spekter v jednom projektu) — přidat až po v0.3, protože zásadně komplikuje UI
- **3D vizualizace** — pro IR spektra zbytečné
- **Real-time akvizici ze spektrometru** — úplně jiný typ software, nemíchat

---

## F. UI/UX Návrh pro Scientific Desktop App

### Rozložení hlavního okna

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Menu Bar: File │ Edit │ View │ Processing │ Analysis │ Tools │ Help    │
├──────────────────────────────────────────────────────────────────────────┤
│  Toolbar: [Open] [Save] [Export PDF] [Export CSV] │ [Zoom] [Pan]       │
│           [Add Peak] [Delete Peak] [Assign Vibration] │ [Undo] [Redo]  │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                                                                   │    │
│  │                     SPEKTRÁLNÍ VIEWER                             │    │
│  │                                                                   │    │
│  │  Wavenumber (cm⁻¹) →                                            │    │
│  │  4000         3000         2000         1500         1000   400  │    │
│  │  ┌──────────────────────────────────────────────────────────┐   │    │
│  │  │            ╱╲                                             │   │    │
│  │  │           ╱  ╲      ╱╲       C=O                         │   │    │
│  │  │  ────────╱    ╲────╱  ╲──────↓───────────────────────   │   │    │
│  │  │         O-H         C-H    1715                          │   │    │
│  │  │         3400        2920                                  │   │    │
│  │  │                                                           │   │    │
│  │  │  Absorbance ↑                                             │   │    │
│  │  └──────────────────────────────────────────────────────────┘   │    │
│  │                                                                   │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
├──────────────────────────────────┬───────────────────────────────────────┤
│                                  │                                       │
│  PEAK TABLE                      │  PRAVÝ PANEL                         │
│  ┌──────────────────────────┐    │  ┌───────────────────────────────┐   │
│  │ # │ cm⁻¹  │ Int. │ Vibr.│    │  │  PŘEDVOLBY VIBRACÍ            │   │
│  │───┼───────┼──────┼──────│    │  │                               │   │
│  │ 1 │ 3400  │ 0.82 │ O-H  │    │  │  [■] O-H stretch    3200-3600│   │
│  │ 2 │ 2920  │ 0.45 │ C-H  │    │  │  [■] N-H stretch    3300-3500│   │
│  │ 3 │ 1715  │ 0.91 │ C=O  │    │  │  [■] C-H stretch    2850-3000│   │
│  │ 4 │ 1450  │ 0.33 │ --   │    │  │  [■] C=O stretch    1680-1750│   │
│  │ 5 │ 1250  │ 0.55 │ --   │    │  │  [■] C=C aromatic   1450-1600│   │
│  │ 6 │ 1050  │ 0.67 │ C-O  │    │  │  [■] C-O stretch    1000-1260│   │
│  └──────────────────────────┘    │  │  [■] C-Cl stretch    600- 800│   │
│                                  │  │                               │   │
│  [+ Add] [× Delete] [↑↓ Sort]   │  │  [+ Nová] [✎ Edit] [× Smaž] │   │
│                                  │  │                               │   │
│                                  │  ├───────────────────────────────┤   │
│                                  │  │  METADATA                     │   │
│                                  │  │                               │   │
│                                  │  │  Vzorek: ____________         │   │
│                                  │  │  Číslo:  ____________         │   │
│                                  │  │  Od:     ____________         │   │
│                                  │  │  Měření: [KBr tablet ▼]      │   │
│                                  │  │  Pozn.:  ____________         │   │
│                                  │  │          ____________         │   │
│                                  │  └───────────────────────────────┘   │
├──────────────────────────────────┴───────────────────────────────────────┤
│  Status Bar: [Ready] │ File: sample_001.spa │ 3842 points │ 400-4000   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Klíčové UI principy

**Spektrální viewer:**
- Osy ve stylu OMNIC: wavenumber klesá zleva doprava (4000 → 400 cm⁻¹)
- Černé pozadí nebo bílé pozadí (přepínatelné, default bílé pro print)
- Osy: tenké černé linky, tick marks ven z grafu, sans-serif font (Arial/Helvetica)
- Grid: jemný šedý, volitelný
- Spektrální čára: tmavě modrá nebo černá, šířka 1–1.5 px
- Peak labels: svislá čára od peaku nahoru + wavenumber text nahoře

**Toolbar:**
- Ikonky ve stylu laboratorního software (ne Material Design, ne Fluent)
- Oddělené sekce: Soubor | Navigace | Peaky | Export
- Tooltips s keyboard shortcuts

**Peak table:**
- Řádky zvýrazněné při hoveru
- Klik na řádek = zvýrazní odpovídající peak ve spektru
- Double-click na buňku = inline editace
- Kontextové menu pravým klikem

**Barevné schéma:**
- Neutrální šedé pozadí panelů (#F0F0F0)
- Bílé pozadí spektra a tabulky
- Akcentová barva: tmavě modrá (#1B3A5C) pro vybrané peaky
- Červená pro neinterpretované peaky, zelená pro přiřazené

---

## G. Rendering a Přidávání Peaků — Detailní Návrh

### Interakční módy (tool modes)

Toolbar obsahuje přepínatelné nástroje (radio-group):

| Mód | Ikona | Popis |
|-----|-------|-------|
| **Select** | šipka | Default. Klik na peak = výběr. Drag = přesun labelu. |
| **Zoom** | lupa | Klik+drag = obdélníkový zoom. Scroll = zoom na kurzor. |
| **Pan** | ruka | Drag = posun spektra. |
| **Add Peak** | + s křížkem | Klik do spektra = přidá peak na nejbližší lokální maximum. |
| **Assign** | tag ikona | Klik na peak = otevře quick-assign popup. |

### Přidávání peaků — implementace

```
Uživatel klikne do spektra v módu "Add Peak"
    │
    ▼
1. Zachytit x-souřadnici kliknutí (wavenumber)
    │
    ▼
2. Najít nejbližší lokální maximum v okolí ±20 cm⁻¹
   (scipy.signal.argrelextrema nebo vlastní search)
    │
    ▼
3. Snap na přesnou pozici maxima (ne na bod kliknutí)
    │
    ▼
4. Vytvořit Peak objekt:
   - position: float (cm⁻¹)
   - intensity: float (absorbance value na této pozici)
   - label: str (default = zaokrouhlená pozice, např. "1715")
   - vibration: Optional[str] (None = nepřiřazeno)
   - label_offset: QPointF (relativní offset labelu od peaku)
    │
    ▼
5. Vykreslit peak marker:
   - Svislá čárkovaná čára od spektrální křivky nahoru
   - Text labelu nahoře
   - Malý trojúhelník/šipka u křivky
    │
    ▼
6. Přidat peak do modelu + aktualizovat tabulku
    │
    ▼
7. Push na undo stack
```

### Hit-testing (detekce kliknutí na peak)

PyQtGraph používá Qt's QGraphicsScene, která má vestavěný hit-testing. Implementace:

```python
class PeakMarkerItem(pg.GraphicsObject):
    """Grafický objekt reprezentující jeden peak ve spektru."""

    def __init__(self, peak: Peak):
        super().__init__()
        self.peak = peak
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

    def boundingRect(self) -> QRectF:
        # Hit-test oblast: svislý pruh ±5px kolem peak čáry
        # + oblast labelu
        return self._calculate_bounds()

    def shape(self) -> QPainterPath:
        # Přesnější hit-test shape než boundingRect
        path = QPainterPath()
        # Svislá čára (hit area ±4px)
        path.addRect(self.line_rect.adjusted(-4, 0, 4, 0))
        # Label text (hit area = bounding box textu)
        path.addRect(self.label_rect)
        return path

    def paint(self, painter, option, widget):
        # 1. Svislá čárkovaná čára
        pen = QPen(Qt.black, 1, Qt.DashLine)
        if self.isSelected():
            pen = QPen(QColor("#1B3A5C"), 2, Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(self.line_start, self.line_end)

        # 2. Label text
        painter.setFont(self.label_font)
        painter.drawText(self.label_position, self.peak.label)

        # 3. Malý marker na křivce
        painter.setBrush(QBrush(Qt.red if not self.peak.vibration else Qt.green))
        painter.drawEllipse(self.curve_point, 3, 3)
```

### Posun labelů (label dragging)

Když uživatel chytí label peaku a táhne:

1. Pouze mění `label_offset` — relativní pozici labelu vůči peaku
2. Svislá čára se natáhne/zkrátí, aby stále spojovala label s křivkou
3. Label se může přesunout kamkoli (nahoru, do strany)
4. Při uvolnění se uloží nový offset
5. Toto je push na undo stack

### Řešení překrývání labelů

**Automatický systém (smart placement):**

```python
def resolve_label_overlaps(peaks: list[Peak], view_rect: QRectF):
    """Posune labely tak, aby se nepřekrývaly."""

    # 1. Seřadit peaky podle x-pozice
    sorted_peaks = sorted(peaks, key=lambda p: p.position)

    # 2. Pro každý label spočítat bounding box
    label_rects = [calculate_label_rect(p) for p in sorted_peaks]

    # 3. Iterativní řešení kolizí (greedy)
    for i in range(1, len(label_rects)):
        for j in range(i):
            if label_rects[i].intersects(label_rects[j]):
                # Posunout label i nahoru (nebo střídavě vlevo/vpravo)
                shift = label_rects[j].bottom() - label_rects[i].top() + 5
                label_rects[i].translate(0, -shift)
                sorted_peaks[i].label_offset.setY(
                    sorted_peaks[i].label_offset.y() - shift
                )

    # 4. Alternativně: střídavé výšky pro blízké peaky
    #    lichý peak = label nahoře, sudý = o řádek výš
```

**Uživatelský override:** Pokud uživatel ručně posune label, automatické umístění se pro tento label deaktivuje (flag `manual_placement = True`).

### Srovnání s OMNIC

OMNIC zobrazuje peaky takto:
- Svislá čára od křivky nahoru k hornímu okraji grafu
- Wavenumber text horizontálně nahoře
- Žádný automatický anti-overlap (uživatel musí řešit ručně)

Naše vylepšení oproti OMNIC:
- **Smart label placement** — automatické vyhýbání se překryvům
- **Barevné kódování** — nepřiřazené vs. přiřazené peaky
- **Drag labels** — interaktivní přesun (OMNIC to neumí)
- **Inline editace** — double-click na label = editace textu

---

## H. Cesta do Budoucna

### 1. Databázové porovnávání spekter (v0.3)

**Architektura:**

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Aktivní     │     │  Preprocessing   │     │  Similarity  │
│  spektrum    │────▶│  Pipeline        │────▶│  Engine      │
│              │     │  (norm, resample) │     │              │
└──────────────┘     └──────────────────┘     └──────┬───────┘
                                                      │
                     ┌──────────────────┐             │
                     │  Spektrální DB   │◀────────────┘
                     │  (SQLite +       │
                     │   numpy blobs)   │──────▶ Ranked results
                     └──────────────────┘
```

**Preprocessing pipeline:**
1. Normalizace (min-max nebo vector normalization)
2. Interpolace na společnou wavenumber osu (např. 400–4000 cm⁻¹, krok 1 cm⁻¹)
3. Volitelně: derivace (1st/2nd) pro potlačení baseline artefaktů
4. Volitelně: smoothing (Savitzky-Golay)

**Similarity algoritmy (od jednoduchých po pokročilé):**
1. **Pearsonova korelace** — rychlá, robustní baseline tolerance
2. **Normalized Euclidean distance** — dobrá pro přesné shody
3. **Spectral Angle Mapper** — invariantní vůči škálování
4. **Normalized Local Change (NLC)** — nejlepší výsledky v benchmarcích pro IR spektra
5. **Weighted correlation** — váhy podle informativnosti regionu (fingerprint region má vyšší váhu)

**Uložení databáze:**
- SQLite tabulka: `spectra(id, name, metadata_json, wavenumber_blob, intensity_blob)`
- Numpy arrays serializované jako BLOB
- Index pro rychlé vyhledávání metadata
- Pre-computed fingerprints pro rychlý screening

### 2. Editor chemických struktur (v0.4+)

**Doporučená strategie:**

- **Backend:** RDKit pro veškerou cheminformatiku (SMILES parsing, fingerprints, rendering 2D struktur, substructure search)
- **Editor:** Ketcher od EPAM, embedded přes QWebEngineView
  - Ketcher je plnohodnotný web-based editor (JavaScript)
  - QWebEngineView ho hostuje uvnitř Qt aplikace
  - Komunikace přes JavaScript bridge (QWebChannel)
  - Ketcher vrací SMILES/MOL, RDKit ho zpracuje

**Alternativa pro lehčí integraci:**
- rdEditor (PySide2 nativní, ale omezený)
- Vlastní minimální editor pomocí RDKit 2D rendering + Qt interakce

**Proč ne vlastní editor od nuly:**
Editor chemických struktur je extrémně komplexní (stereochemie, aromaticita, templating, ring perception). Ketcher má 10+ let vývoje. Neimplementovat znovu.

### 3. Profesionální report builder (v0.4+)

**Architektura:**

```python
class ReportBuilder:
    """Sestaví PDF report z komponent."""

    def build(self, project: Project, template: ReportTemplate) -> bytes:
        sections = []

        # 1. Hlavička (metadata, datum, logo)
        sections.append(HeaderSection(project.metadata))

        # 2. Spektrum (Matplotlib statický render, publication quality)
        fig = self.render_spectrum_for_pdf(project)
        sections.append(ImageSection(fig))

        # 3. Peak table
        sections.append(TableSection(project.peaks))

        # 4. Chemická struktura (RDKit SVG render)
        if project.structure:
            svg = render_structure_svg(project.structure)
            sections.append(ImageSection(svg))

        # 5. Interpretace / závěry
        sections.append(TextSection(project.interpretation_notes))

        # 6. Database match results
        if project.match_results:
            sections.append(MatchResultsSection(project.match_results))

        return self.pdf_engine.render(sections, template)
```

**PDF engine:** ReportLab s custom template systémem.
- Šablony definují layout (kde je spektrum, kde tabulka, kde struktura)
- Uživatel může mít více šablon pro různé účely
- Export do A4 (default) nebo custom formát

### 4. Skriptovatelnost / Pluginy (v0.5+)

**Python scripting console:**
- Embedded IPython konzole v dolním panelu (volitelně)
- Přímý přístup k aktuálnímu projektu, spektru, peakům
- Umožňuje power users psát vlastní processing scripty

**Plugin systém:**
```python
class Plugin(ABC):
    """Základní třída pro plugin."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def activate(self, app: Application) -> None: ...

    @abstractmethod
    def deactivate(self) -> None: ...
```

- Pluginy jako Python balíčky v `~/.spectraapp/plugins/`
- Mohou přidávat: nové formáty, nové processing algoritmy, nové UI panely, nové export formáty
- Registrace přes entry points (setuptools) nebo vlastní manifest

### 5. AI-Assisted interpretace (v0.6+)

Až bude hotový solidní manuální workflow + databáze:
- **Suggestion engine:** Na základě pozice peaků a jejich vzorců navrhnout pravděpodobné funkční skupiny
- **LLM integration:** Odeslat peak list do Claude/GPT API a získat interpretační návrh
- **ML matching:** Trénovaný model na IR spektrech pro klasifikaci látek

---

## Závěrečné Doporučení

### 1. Hlavní doporučení (co bych udělal já)

**Python 3.11+ / PySide6 / PyQtGraph / SpectroChemPy / ReportLab**

Důvod: Nejlepší poměr kvalita výsledku / čas vývoje. PyQtGraph poskytuje profesionální scientific plotting s nativní Qt integrací. Python ekosystém pokrývá 100 % potřeb projektu — od SPA parsingu přes signal processing po cheminformatiku. Jeden jazyk = jeden codebase = jednodušší údržba. Pro IR spektra (tisíce bodů) je Python více než dostatečně rychlý. Hot paths lze později optimalizovat přes Cython/C extensions, ale s vysokou pravděpodobností to nebude potřeba.

### 2. Konzervativní varianta

**Python 3.11+ / PySide6 / Matplotlib (embedded) / SpectroChemPy / ReportLab**

Matplotlib místo PyQtGraph. Výhoda: Matplotlib je etablovanější, více příkladů, lepší statický export. Nevýhoda: interaktivní performance je výrazně horší (~40 FPS vs >1000 FPS), zoom/pan je méně plynulý. Pro statické zobrazení OK, pro interaktivní peak picking suboptimální. Doporučuji jen pokud je priorita statická kvalita výstupu nad interaktivitou.

### 3. Varianta "bez kompromisů"

**C++ 17 / Qt 6 / QCustomPlot / vlastní SPA parser / RDKit (C++ API) / Qt PDF**

Maximální výkon, nejmenší binárka, nativní rendering. QCustomPlot je excelentní C++ scientific plotting knihovna. Vše kompilované, žádný interpreter overhead. Ale: vývoj bude 3–5× pomalejší, scientific computing v C++ je náročnější (žádný SciPy), SPA parser nutno portovat ručně. Doporučuji pouze pokud máte tým 2+ vývojářů a časový horizont 6+ měsíců pro MVP.

### 4. Konkrétní první implementační plán

**Týden 1: Základ**
- Setup projektu (pyproject.toml, uv/pip, git)
- Hlavní okno s QMainWindow, dockable panely
- SPA reader wrapper (SpectroChemPy)
- Načtení a zobrazení spektra v PyQtGraph (základní)

**Týden 2: Spektrální viewer**
- Profesionální styl os (OMNIC-like: wavenumber descending, tick marks, grid)
- Zoom (obdélníkový výběr, scroll)
- Pan (middle button drag)
- Automatická detekce peaků (scipy.signal.find_peaks) s vizualizací

**Týden 3: Peak management**
- Ruční přidávání peaků klikáním (snap na lokální maximum)
- Peak marker rendering (svislá čára + label)
- Hit-testing a výběr peaků
- Smazání peaku
- Tabulka peaků (QTableView s custom modelem)
- Synchronizace tabulka ↔ graf (klik na řádek = highlight ve spektru)

**Týden 4: Interpretace**
- Předvolby vibrací (hardcoded sada + JSON persistence)
- Quick-assign workflow (vyber vibrace → klikni na peak)
- Metadata panel (ruční vstup)
- Barevné kódování peaků (přiřazené vs. nepřiřazené)

**Týden 5: Export + Polish**
- PDF report (ReportLab + Matplotlib statický render)
- CSV export tabulky
- Keyboard shortcuts
- Error handling, edge cases
- Testování s reálnými SPA soubory
- Packaging (PyInstaller) pro distribuci

---

*Tento dokument je živý architektonický plán. Měl by být aktualizován s každou novou verzí software.*
