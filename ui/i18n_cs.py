"""
Czech UI texts.

Klíč je anglický text přesně tak, jak stojí v kódu; hodnota je český překlad.
Text, který tu chybí, zůstane v aplikaci anglicky — proto sem patří každý nový
řetězec rozhraní. Zástupné symboly ``{name}`` musí zůstat beze změny.

Chemické názvy (vibrace, funkční skupiny) se záměrně nepřekládají: jsou to
data, stejná v aplikaci i v reportu.
"""

from __future__ import annotations

CZECH_TEXTS: dict[str, str] = {
    # ── Menu ────────────────────────────────────────────────────────────────
    "&File": "&Soubor",
    "&Edit": "Ú&pravy",
    "&Database": "&Databáze",
    "&View": "&Zobrazení",
    "&Help": "&Nápověda",
    "&Language": "&Jazyk",
    "System": "Podle systému",
    "&Appearance": "&Vzhled",
    "Appearance": "Vzhled",
    "Follow system": "Podle systému",
    "Light": "Světlý",
    "Dark": "Tmavý",
    "The new appearance is used the next time the application starts.": (
        "Nový vzhled se použije při příštím spuštění aplikace."
    ),
    "New &Window": "Nové &okno",
    "&Open Spectrum...": "&Otevřít spektrum...",
    "Open &Project...": "Otevřít &projekt...",
    "&Save Project": "&Uložit projekt",
    "Save Project &As...": "Uložit projekt &jako...",
    "Open &Recent": "&Naposledy otevřené",
    "(empty)": "(prázdné)",
    "E&xit": "&Konec",
    "&Undo": "&Zpět",
    "&Redo": "Z&novu",
    "&About": "&O aplikaci",
    "&Reset Layout": "&Obnovit rozložení panelů",
    "Put every panel back where it was when first installed": (
        "Vrátí všechny panely tam, kde byly po instalaci"
    ),
    "Panel layout reset": "Rozložení panelů obnoveno",
    "Reference Library...": "Knihovna referencí...",
    "Set Annotated Projects Folder...": "Nastavit složku vyhodnocených projektů...",
    "Add Current Spectrum to Reference Library": "Přidat aktuální spektrum do knihovny referencí",
    "Auto-add Saved Projects to Reference Library": (
        "Ukládané projekty automaticky přidávat do knihovny referencí"
    ),
    "Batch Import References...": "Hromadný import referencí...",
    "Batch Export PDF Reports...": "Hromadný export PDF reportů...",
    "Batch Generate Projects...": "Hromadné vytvoření projektů...",
    "Batch Export Project PDFs...": "Hromadný export PDF z projektů...",
    "Batch Import References": "Hromadný import referencí",
    "Batch Export PDF Reports": "Hromadný export PDF reportů",
    "Batch Generate Projects": "Hromadné vytvoření projektů",
    "Batch Export Project PDFs": "Hromadný export PDF z projektů",
    "Open a second workspace so another spectrum or project can stay open alongside this one": (
        "Otevře druhé okno, takže vedle tohoto může zůstat otevřené další spektrum nebo projekt"
    ),
    "Save to the project file already open; asks for a name the first time": (
        "Uloží do otevřeného souboru projektu; na název se zeptá jen poprvé"
    ),
    "Folder of previously analysed .irproj files used by 'Apply assignments from match'": (
        "Složka dříve vyhodnocených souborů .irproj, ze které čerpá „Použít přiřazení ze shody“"
    ),
    "Make the loaded spectrum searchable by Match Spectrum without copying its file "
    "into the reference library folder": (
        "Zpřístupní načtené spektrum pro porovnání, aniž by se jeho soubor kopíroval "
        "do složky knihovny referencí"
    ),
    "On Save Project, also store the spectrum in the reference library so the next "
    "similar sample matches it": (
        "Při uložení projektu uloží spektrum i do knihovny referencí, takže se s ním "
        "příští podobný vzorek porovná"
    ),
    # ── Toolbar ─────────────────────────────────────────────────────────────
    "Main Toolbar": "Hlavní lišta",
    "Open": "Otevřít",
    "Save": "Uložit",
    "Undo": "Zpět",
    "Redo": "Znovu",
    "Select": "Výběr",
    "Zoom": "Lupa",
    "Pan": "Posun",
    "Add Peak": "Přidat pík",
    "Detect Peaks": "Najít píky",
    "Sensitivity": "Citlivost",
    "Arrange Labels": "Rozmístit popisky",
    "Clear Peaks": "Smazat píky",
    "Correct Baseline": "Korekce baseline",
    "Match Spectrum": "Porovnat s knihovnou",
    "Export": "Export",
    "Open a spectrum file (Ctrl+O)": "Otevřít soubor se spektrem (Ctrl+O)",
    "Save the project to its file (Ctrl+S)": "Uložit projekt do jeho souboru (Ctrl+S)",
    "Undo the last step (Ctrl+Z)": "Vrátit poslední krok (Ctrl+Z)",
    "Redo the step just undone (Ctrl+Y)": "Zopakovat vrácený krok (Ctrl+Y)",
    "Select — click a peak or its label to select it (S)": (
        "Výběr — kliknutím na pík nebo jeho popisek ho vyberete (S)"
    ),
    "Zoom — drag a rectangle to zoom in (Z)": "Lupa — tažením obdélníku přiblížíte (Z)",
    "Pan — drag to move the view, wheel to zoom (P)": (
        "Posun — tažením posunete zobrazení, kolečkem přiblížíte (P)"
    ),
    "Add Peak — click any point of the spectrum to label it "
    "(hold Ctrl to snap to the apex of the band under the pointer) (A)": (
        "Přidat pík — kliknutím označíte libovolný bod spektra "
        "(s klávesou Ctrl se pík přichytí na vrchol pásu pod kurzorem) (A)"
    ),
    "Find peaks automatically at the sensitivity set beside this button.\n"
    "Peaks that already carry an assignment are kept.": (
        "Automaticky najde píky s citlivostí nastavenou vedle tlačítka.\n"
        "Píky, které už mají přiřazení, zůstanou zachované."
    ),
    "Detection sensitivity: 1 marks only the dominant bands, "
    "10 also the faintest ones.\n"
    "After Detect Peaks, moving the slider re-detects straight away.": (
        "Citlivost detekce: 1 označí jen nejvýraznější pásy, 10 i ty nejslabší.\n"
        "Po stisku Najít píky se při posunutí píky ihned přepočítají."
    ),
    "Stagger overlapping peak labels": "Rozmístí překrývající se popisky píků",
    "Remove every peak (Ctrl+Z brings them back)": "Odstraní všechny píky (Ctrl+Z je vrátí)",
    "Remove a rubber-band baseline (Ctrl+Z to undo)": (
        "Odstraní základní linii metodou rubber-band (Ctrl+Z vrátí zpět)"
    ),
    "Compare the spectrum with the reference library (Ctrl+M)": (
        "Porovná spektrum s knihovnou referencí (Ctrl+M)"
    ),
    "Export a PDF report, CSV or Excel file (Ctrl+E)": (
        "Export PDF reportu, CSV nebo souboru Excel (Ctrl+E)"
    ),
    # ── Docks ───────────────────────────────────────────────────────────────
    "Vibration Presets": "Vibrace",
    "Peaks": "Píky",
    "Metadata": "Údaje",
    "Match Results": "Shody",
    "Functional Groups": "Funkční skupiny",
    "Consensus": "Souhrn",
    "Structure": "Struktura",
    # ── Welcome page ────────────────────────────────────────────────────────
    "Drop a spectrum here": "Přetáhněte sem spektrum",
    "OMNIC .spa, JCAMP-DX .jdx / .dx, or a saved .irproj project": (
        "OMNIC .spa, JCAMP-DX .jdx / .dx nebo uložený projekt .irproj"
    ),
    "Open Spectrum…": "Otevřít spektrum…",
    "Open Project…": "Otevřít projekt…",
    "Recent files": "Naposledy otevřené",
    # ── Spectrum viewer ─────────────────────────────────────────────────────
    "Wavenumber (cm⁻¹)": "Vlnočet (cm⁻¹)",
    "Absorbance": "Absorbance",
    "Transmittance": "Transmitance",
    "Reflectance": "Reflektance",
    "Single Beam": "Jednopaprskové spektrum",
    "Baseline Corrected": "Po korekci baseline",
    "baseline corrected": "po korekci baseline",
    "as loaded": "původní",
    "Range:": "Rozsah:",
    "Full": "Celé",
    "Show the whole spectrum": "Zobrazí celé spektrum",
    "Show {window} cm⁻¹ with the intensity axis fitted to it": (
        "Zobrazí {window} cm⁻¹ a osu intenzity přizpůsobí tomuto výřezu"
    ),
    "Split view": "Dělený pohled",
    "Show fingerprint region (400–2000 cm⁻¹) expanded": (
        "Zobrazí oblast otisku prstu (400–2000 cm⁻¹) roztaženě"
    ),
    "Show as:": "Jednotka:",
    "Redraw the spectrum in another intensity unit.\n"
    "The loaded data is not changed; overlays follow the same unit.": (
        "Překreslí spektrum v jiné jednotce intenzity.\n"
        "Načtená data se nemění; překrytá reference se zobrazí ve stejné jednotce."
    ),
    "Display": "Zobrazení",
    "Reading aids for the plot": "Pomůcky pro čtení grafu",
    "Tidy labels": "Uklidit popisky",
    "Hide the labels of weaker peaks where labels would overlap.\n"
    "They come back as you zoom in; selected and assigned peaks always stay.": (
        "Skryje popisky slabších píků tam, kde by se popisky překrývaly.\n"
        "Při přiblížení se vrátí; vybrané a přiřazené píky zůstávají vždy."
    ),
    "Crosshair": "Nitkový kříž",
    "Follow the pointer with a hairline and show the values of the curve under it": (
        "Sleduje kurzor svislou linkou a ukazuje hodnoty křivky pod ním"
    ),
    "Reference overlay:": "Překrytá reference:",
    "Opacity:": "Krytí:",
    "Reference spectrum opacity": "Krytí referenčního spektra",
    "Clear": "Skrýt",
    "Remove the reference overlay from the plot": "Odstraní překrytou referenci z grafu",
    "band found": "pás nalezen",
    "band expected, weak or absent": "pás očekávaný, slabý nebo chybí",
    "required band missing": "povinný pás chybí",
    "range of the selected vibration": "rozsah vybrané vibrace",
    # ── Status bar ──────────────────────────────────────────────────────────
    "Ready": "Připraveno",
    "Baseline corrected": "Po korekci baseline",
    "{count} labels hidden": "{count} popisků skryto",
    "Labels of weaker peaks are hidden where they would overlap. Zoom in to see them.": (
        "Popisky slabších píků jsou skryté tam, kde by se překrývaly. Přiblížením se zobrazí."
    ),
    "No peaks": "Žádné píky",
    "{total} peaks · {assigned} assigned": "{total} píků · {assigned} přiřazeno",
    "No project loaded": "Není načtený žádný projekt",
    "No spectrum loaded": "Není načtené žádné spektrum",
    "Project loaded: {name}": "Projekt načten: {name}",
    "Project saved: {name}": "Projekt uložen: {name}",
    "Sensitivity {level} — press Detect Peaks to apply it": (
        "Citlivost {level} — použije se po stisku Najít píky"
    ),
    "Detected {count} peaks at sensitivity {level}": (
        "Nalezeno {count} píků při citlivosti {level}"
    ),
    "({count} assigned kept)": "({count} přiřazených ponecháno)",
    "Baseline corrected (Ctrl+Z to undo)": "Baseline zkorigována (Ctrl+Z vrátí zpět)",
    "PDF exported: {name}": "PDF exportováno: {name}",
    "CSV exported: {name}": "CSV exportováno: {name}",
    "Excel exported: {name}": "Excel exportován: {name}",
    "Peak: {position} cm⁻¹  |  {intensity}": "Pík: {position} cm⁻¹  |  {intensity}",
    'Assigned "{name}" to peak at {position} cm⁻¹': (
        "Vibrace „{name}“ přiřazena píku {position} cm⁻¹"
    ),
    'Removed "{name}" from peak at {position} cm⁻¹': (
        "Vibrace „{name}“ odebrána z píku {position} cm⁻¹"
    ),
    'Assigned suggested vibration "{name}" to {position} cm⁻¹': (
        "Navržená vibrace „{name}“ přiřazena píku {position} cm⁻¹"
    ),
    "Updated vibration text for {position} cm⁻¹": "Text vibrace u píku {position} cm⁻¹ upraven",
    "Cleared vibration text for {position} cm⁻¹": "Text vibrace u píku {position} cm⁻¹ smazán",
    "Deleted peak at {position} cm⁻¹": "Pík {position} cm⁻¹ smazán",
    "Deleted {count} peaks": "Smazáno {count} píků",
    "Peaks cleared": "Píky smazány",
    "No peaks available to arrange": "Nejsou žádné píky k rozmístění",
    "No peak labels available to arrange": "Nejsou žádné popisky k rozmístění",
    "Peak labels are already arranged": "Popisky píků už jsou rozmístěné",
    "Peak labels arranged": "Popisky píků rozmístěny",
    "Select a peak first, then double-click a vibration to assign it.": (
        "Nejdřív vyberte pík, potom dvojklikem přiřaďte vibraci."
    ),
    "Select a peak first, then double-click a preset.": (
        "Nejdřív vyberte pík, potom dvojklikem zvolte vibraci."
    ),
    "Select a peak first, then double-click a suggestion.": (
        "Nejdřív vyberte pík, potom dvojklikem zvolte návrh."
    ),
    "Selected peak is outside the suggested vibration range.": (
        "Vybraný pík leží mimo rozsah navržené vibrace."
    ),
    "No matching vibration preset found for this suggestion.": (
        "K tomuto návrhu se nenašla odpovídající vibrace."
    ),
    "Proposed structure updated": "Navržená struktura upravena",
    "Reference search is already running": "Porovnávání s knihovnou už běží",
    "Matching spectrum against reference library…": "Porovnávám spektrum s knihovnou referencí…",
    "Matching failed": "Porovnání se nezdařilo",
    "Matching failed:": "Porovnání se nezdařilo:",
    "Matching result ignored because the project or filter changed.": (
        "Výsledek porovnání byl zahozen, protože se mezitím změnil projekt nebo filtr."
    ),
    "Choose a reference library folder first in Database -> Reference Library.": (
        "Nejdřív zvolte složku knihovny referencí: Databáze → Knihovna referencí."
    ),
    "No reference spectra available. Sync or import the selected library first.": (
        "Nejsou k dispozici žádná referenční spektra. Nejdřív knihovnu "
        "synchronizujte nebo naimportujte."
    ),
    "Matched against {count} references": "Porovnáno s {count} referencemi",
    "Saved projects are added to the reference library": (
        "Ukládané projekty se přidávají do knihovny referencí"
    ),
    "Saved projects are no longer added to the reference library": (
        "Ukládané projekty se už do knihovny referencí nepřidávají"
    ),
    "Annotated projects folder: {name}": "Složka vyhodnocených projektů: {name}",
    "Reference imported: {name}": "Reference naimportována: {name}",
    "Functional-group analysis unavailable: {error}": (
        "Analýza funkčních skupin není dostupná: {error}"
    ),
    "Could not add to reference library: {error}": (
        "Nepodařilo se přidat do knihovny referencí: {error}"
    ),
    # ── Messages and file dialogs ───────────────────────────────────────────
    "Unsaved Changes": "Neuložené změny",
    "The current project has unsaved changes. Save them before continuing?": (
        "Aktuální projekt obsahuje neuložené změny. Uložit je před pokračováním?"
    ),
    "Open Error": "Chyba při otevírání",
    "Save Error": "Chyba při ukládání",
    "Export Error": "Chyba při exportu",
    "Match Error": "Chyba při porovnání",
    "Import Error": "Chyba při importu",
    "Apply Error": "Chyba při přenosu přiřazení",
    "Operation in Progress": "Operace probíhá",
    "Reference matching is still running. Please wait for it to finish before closing.": (
        "Porovnávání s knihovnou ještě běží. Před zavřením prosím počkejte na dokončení."
    ),
    "Failed to open recent file:": "Soubor se nepodařilo otevřít:",
    "Failed to save project:": "Projekt se nepodařilo uložit:",
    "Failed to open project:": "Projekt se nepodařilo otevřít:",
    "Failed to load spectrum:": "Spektrum se nepodařilo načíst:",
    "Failed to export PDF:": "PDF se nepodařilo exportovat:",
    "Failed to export CSV:": "CSV se nepodařilo exportovat:",
    "Failed to export Excel:": "Excel se nepodařilo exportovat:",
    "Failed to import reference:": "Referenci se nepodařilo naimportovat:",
    "Open IR Spectrum": "Otevřít IR spektrum",
    "Open IR Project": "Otevřít IR projekt",
    "Save IR Project": "Uložit IR projekt",
    "Export PDF Report": "Export PDF reportu",
    "Export CSV": "Export CSV",
    "Export Excel": "Export do Excelu",
    "Import Reference Spectrum": "Import referenčního spektra",
    # ── Peak table ──────────────────────────────────────────────────────────
    "Position (cm⁻¹)": "Poloha (cm⁻¹)",
    "Intensity": "Intenzita",
    "Rel.": "Rel.",
    "Vibration": "Vibrace",
    "Copy all": "Kopírovat vše",
    "Copy entire peak table to clipboard (TSV)": "Zkopíruje celou tabulku píků do schránky (TSV)",
    "Relative band strength: w = weak, m = medium, s = strong, vs = very strong": (
        "Relativní intenzita pásu: w = slabý, m = střední, s = silný, vs = velmi silný"
    ),
    "Double-click to edit the vibration text": "Dvojklikem upravíte text vibrace",
    # ── Vibration panel ─────────────────────────────────────────────────────
    "All functional groups": "Všechny funkční skupiny",
    "Show only vibrations diagnostic for one functional group "
    "(e.g. when you already know the molecule contains an acid)": (
        "Zobrazí jen vibrace charakteristické pro jednu funkční skupinu "
        "(např. když už víte, že molekula obsahuje kyselinu)"
    ),
    "Filter vibrations…": "Hledat vibraci…",
    "Grouped by type": "Seskupeno podle typu",
    "Sorted by wavenumber": "Seřazeno podle vlnočtu",
    "How the list is arranged: in sections by vibration type, with the "
    "vibrations that fit the selected peak on top, or as one list "
    "ordered by wavenumber.": (
        "Uspořádání seznamu: v sekcích podle typu vibrace, s vibracemi odpovídajícími "
        "vybranému píku nahoře, nebo jako jeden seznam seřazený podle vlnočtu."
    ),
    "Click a vibration to see its range in the spectrum": (
        "Kliknutím na vibraci zobrazíte její rozsah ve spektru"
    ),
    "Active peak: {position} cm⁻¹ · double-click to assign": (
        "Vybraný pík: {position} cm⁻¹ · dvojklikem přiřadíte"
    ),
    "Fits peak {position} cm⁻¹": "Odpovídá píku {position} cm⁻¹",
    "Custom vibrations": "Vlastní vibrace",
    "Stretching ν": "Valenční ν",
    "Bending δ": "Deformační δ",
    "Out-of-plane γ": "Mimorovinné γ",
    "Rocking and wagging": "Kývavé a vějířové",
    "Overtones and combinations": "Svrchní tóny a kombinace",
    "Protecting groups": "Chránicí skupiny",
    "Other": "Ostatní",
    "Click to fold or unfold this section": "Kliknutím sekci sbalíte nebo rozbalíte",
    "Assign to selected peak": "Přiřadit vybranému píku",
    "Assign to peak {position} cm⁻¹": "Přiřadit píku {position} cm⁻¹",
    "Assign the highlighted vibration to the selected peak.\n"
    "Double-clicking the vibration or pressing Enter does the same.": (
        "Přiřadí označenou vibraci vybranému píku.\n"
        "Totéž udělá dvojklik na vibraci nebo klávesa Enter."
    ),
    "Show vibration range in spectrum": "Zobrazovat rozsah vibrace ve spektru",
    "Outline the wavenumber window a clicked vibration can occupy. "
    "Turn off to keep the spectrum clear.": (
        "Vyznačí oblast vlnočtů, ve které se kliknutá vibrace může objevit. "
        "Vypnutím zůstane spektrum čisté."
    ),
    "Add custom vibration…": "Přidat vlastní vibraci…",
    "Add a permanent custom vibration entry": "Přidá trvalou vlastní vibraci",
    "Add Custom Vibration": "Přidat vlastní vibraci",
    "Label:": "Popis:",
    "Range min:": "Rozsah od:",
    "Range max:": "Rozsah do:",
    "Edit Peak Vibration": "Upravit vibraci píku",
    "Vibration:": "Vibrace:",
    "Insert Greek letters": "Vložit řecká písmena",
    "Convert the selection, or previous character, to subscript": (
        "Převede výběr nebo předchozí znak na dolní index"
    ),
    "Convert the selection, or previous character, to superscript": (
        "Převede výběr nebo předchozí znak na horní index"
    ),
    # ── Match results ───────────────────────────────────────────────────────
    "No results": "Žádné výsledky",
    "{total} candidates ({saved} saved)": "{total} kandidátů ({saved} s uloženým projektem)",
    "{saved} of {total} candidates saved": "{saved} z {total} kandidátů má uložený projekt",
    "No saved project among {total} candidates": ("Žádný z {total} kandidátů nemá uložený projekt"),
    "No annotated projects folder set": "Není nastavená složka vyhodnocených projektů",
    "Similarity score is an internal spectral metric "
    "(coarse cosine search + fine rerank). Not equivalent to OMNIC HQI.": (
        "Skóre podobnosti je vlastní spektrální metrika "
        "(hrubé kosinové hledání + jemné přeřazení). Neodpovídá hodnotě HQI z OMNICu."
    ),
    "Import Reference...": "Importovat referenci...",
    "Name filter:": "Filtr názvu:",
    "e.g. NIT — limits Match Spectrum, empty = all": ("např. NIT — omezí porovnání, prázdné = vše"),
    "Only matches with a saved project (.irproj)": "Jen shody s uloženým projektem (.irproj)",
    "Show only matches that have a saved .irproj in the annotated projects "
    "folder — those are the ones you can apply assignments from": (
        "Zobrazí jen shody, které mají ve složce vyhodnocených projektů uložený .irproj — "
        "z těch lze převzít přiřazení"
    ),
    "Reference": "Reference",
    "Match": "Shoda",
    "Skeleton": "Skelet",
    "Similarity over the skeleton region 400–1600 cm⁻¹ only. "
    "▲ marks a skeleton score at least 10 points above the overall one — "
    "typically the same skeleton carrying a different substituent.": (
        "Podobnost jen v oblasti skeletu 400–1600 cm⁻¹. "
        "▲ označuje skóre skeletu alespoň o 10 bodů vyšší než celkové — "
        "typicky stejný skelet s jiným substituentem."
    ),
    "Bands with no counterpart within 8 cm⁻¹ in the other spectrum, strongest first": (
        "Pásy, které v druhém spektru nemají protějšek do 8 cm⁻¹, od nejsilnějšího"
    ),
    "Apply assignments from match": "Použít přiřazení ze shody",
    "Copy vibration assignments and structure from the selected match's "
    "saved project onto the current spectrum (nearest peaks, blanks only)": (
        "Zkopíruje přiřazení vibrací a strukturu z uloženého projektu vybrané shody "
        "na aktuální spektrum (nejbližší píky, jen dosud nepřiřazené)"
    ),
    # ── Metadata ────────────────────────────────────────────────────────────
    "Sample:": "Vzorek:",
    "File:": "Soubor:",
    "Operator:": "Operátor:",
    "Instrument:": "Přístroj:",
    "Acquired:": "Změřeno:",
    "Client:": "Zadavatel:",
    "Order:": "Zakázka:",
    "Comment:": "Poznámka:",
    "sample designation, e.g. LF_647": "označení vzorku, např. LF_647",
    "file identifier, defaults to the file name": "označení souboru, výchozí je název souboru",
    "e.g. Nicolet iS 50": "např. Nicolet iS 50",
    # ── Functional groups / consensus ───────────────────────────────────────
    "No functional-group analysis": "Analýza funkčních skupin není k dispozici",
    "{count} functional groups ranked": "{count} funkčních skupin seřazeno",
    "Show highlighted regions in spectrum": "Zobrazovat vyznačené oblasti ve spektru",
    "Select a functional group to inspect its evidence.": (
        "Vyberte funkční skupinu a zobrazí se, o co se opírá."
    ),
    "Select a peak to see assignment suggestions for it.": (
        "Vyberte pík a zobrazí se pro něj návrhy přiřazení."
    ),
    "Diagnostic vibrations": "Diagnostické vibrace",
    "Suggested vibrations and evidence": "Navrhované vibrace a důkazy",
    "Suggestions for active peak {wavenumber} cm⁻¹": ("Návrhy pro aktivní pík {wavenumber} cm⁻¹"),
    "Confidence score is a heuristic ranking from diagnostic IR bands. "
    "It is not a statistically calibrated probability.": (
        "Skóre je heuristické pořadí podle diagnostických IR pásů. "
        "Není to statisticky kalibrovaná pravděpodobnost."
    ),
    "No consensus analysis": "Souhrn není k dispozici",
    "Interpretation confidence {score}%": "Jistota interpretace {score} %",
    "Run matching or inspect functional groups to build consensus.": (
        "Spusťte porovnání nebo si projděte funkční skupiny, souhrn se pak sestaví."
    ),
    "Confirmed, uncertain, and conflicting evidence will appear here.": (
        "Zde se zobrazí potvrzené, nejisté a protichůdné poznatky."
    ),
    "Top hypotheses": "Nejpravděpodobnější hypotézy",
    "Top spectral matches": "Nejlepší shody v knihovně",
    "Select a hypothesis to inspect its evidence.": (
        "Vyberte hypotézu a zobrazí se, o co se opírá."
    ),
    "Consensus combines functional-group evidence, library matches, and assigned "
    "peaks. It is an interpretation aid, not a definitive identification.": (
        "Souhrn spojuje poznatky o funkčních skupinách, shody v knihovně a přiřazené píky. "
        "Je to pomůcka pro interpretaci, ne definitivní identifikace."
    ),
    "Delete “{name}”": "Smazat „{name}“",
    "Remove from peak {wavenumber} cm⁻¹": "Odebrat z píku {wavenumber} cm⁻¹",
    # ── Structure ───────────────────────────────────────────────────────────
    "No structure assigned": "Struktura není přiřazena",
    "Invalid structure": "Neplatná struktura",
    "Edit Structure...": "Upravit strukturu...",
    # ── Export dialog ───────────────────────────────────────────────────────
    "PDF Report": "PDF report",
    "CSV (peaks table)": "CSV (tabulka píků)",
    "Excel (.xlsx)": "Excel (.xlsx)",
    "Include peaks without assignment": "Zahrnout píky bez přiřazení",
    "Preset:": "Předvolba:",
    "Current defaults": "Aktuální výchozí",
    "Custom": "Vlastní",
    "Save Preset...": "Uložit předvolbu...",
    "Delete Preset": "Smazat předvolbu",
    "Include metadata": "Zahrnout údaje o měření",
    "Include peak table": "Zahrnout tabulku píků",
    "Include structures": "Zahrnout struktury",
    "First page:": "První strana:",
    "Spectrum across the whole page + structure and sample name in the plot": (
        "Spektrum přes celou stranu + struktura a název vzorku v grafu"
    ),
    "Spectrum inside page margins": "Spektrum uvnitř okrajů strany",
    "Split X-axis at 2000 cm⁻¹": "Dělená osa X na 2000 cm⁻¹",
    "OK": "OK",
    "Cancel": "Zrušit",
    "Close": "Zavřít",
    # ── Reference library dialog ────────────────────────────────────────────
    "Reference Library": "Knihovna referencí",
    "Filters": "Filtry",
    "Name contains:": "Název obsahuje:",
    "Y unit:": "Jednotka Y:",
    "Imported:": "Importováno:",
    "All": "Vše",
    "All time": "Kdykoliv",
    "Last 7 days": "Posledních 7 dní",
    "Last 30 days": "Posledních 30 dní",
    "Last 3 months": "Poslední 3 měsíce",
    "Last 6 months": "Posledních 6 měsíců",
    "Last year": "Poslední rok",
    "Custom range…": "Vlastní období…",
    "From:": "Od:",
    "To:": "Do:",
    "e.g. PAR or KLH": "např. PAR nebo KLH",
    "Show current spectrum": "Zobrazit aktuální spektrum",
    "Select a row to preview": "Vyberte řádek pro náhled",
    "Reference library folder: not selected": "Složka knihovny referencí: nevybrána",
    "Similarity search: choose a reference folder first": (
        "Hledání podobných: nejdřív zvolte složku referencí"
    ),
    "Library is empty — use Import File… or Choose Folder… to add references.": (
        "Knihovna je prázdná — reference přidáte přes Importovat soubor… nebo Zvolit složku…"
    ),
    "Library": "Knihovna",
    "Selected reference": "Vybraná reference",
    "Similarity search": "Hledání podobných",
    "Choose Folder...": "Zvolit složku...",
    "Sync Folder": "Synchronizovat složku",
    "Import File...": "Importovat soubor...",
    "Import Web Reference...": "Importovat z webu...",
    "Rename": "Přejmenovat",
    "Delete": "Smazat",
    "Clear Library": "Vyprázdnit knihovnu",
    "Find Similar to Current": "Najít podobné aktuálnímu",
    "Find Similar to Selected": "Najít podobné vybranému",
    "Open in Main Window": "Otevřít v hlavním okně",
    "Show All": "Zobrazit vše",
    "Rename the selected reference (F2)": "Přejmenuje vybranou referenci (F2)",
    "Delete the selected reference(s) (Delete)": "Smaže vybrané reference (Delete)",
    "Remove every reference spectrum, so you can re-import a folder from scratch": (
        "Odstraní všechna referenční spektra, aby šla složka naimportovat znovu od začátku"
    ),
    "Rank the library by similarity to the active spectrum": (
        "Seřadí knihovnu podle podobnosti s aktuálním spektrem"
    ),
    "Rank the library by similarity to the selected reference": (
        "Seřadí knihovnu podle podobnosti s vybranou referencí"
    ),
    "Load the selected reference's source file into the main spectrum viewer (Enter)": (
        "Načte zdrojový soubor vybrané reference do hlavního okna (Enter)"
    ),
    "Name": "Název",
    "Similarity": "Podobnost",
    "Quality": "Kvalita",
    "Description": "Popis",
    "Imported": "Importováno",
    "Created At": "Importováno",
    "Source": "Zdroj",
    "Y Unit": "Jednotka Y",
    "Excellent": "Vynikající",
    "Strong": "Silná",
    "Possible": "Možná",
    "Weak": "Slabá",
    "fp = skeleton region 400–1600 cm⁻¹ only. ▲ marks a skeleton score at least "
    "10 points above the overall one — typically the same skeleton carrying a "
    "different substituent.": (
        "fp = jen oblast skeletu 400–1600 cm⁻¹. ▲ označuje skóre skeletu alespoň "
        "o 10 bodů vyšší než celkové — typicky stejný skelet s jiným substituentem."
    ),
    "Saved .irproj found — assignments can be applied from this match": (
        "Nalezen uložený .irproj — z této shody lze převzít přiřazení"
    ),
    "Current spectrum": "Aktuální spektrum",
    "Reference library folder: {path}": "Složka knihovny referencí: {path}",
    "Reference library folder: syncing…": "Složka knihovny referencí: synchronizuji…",
    "Similarity search: not run yet": "Hledání podobných: zatím nespuštěno",
    "Similarity search: running…": "Hledání podobných: probíhá…",
    "Similarity search: load a spectrum to rank the library": (
        "Hledání podobných: nejdřív načtěte spektrum"
    ),
    "Similarity search: ranked {count} library spectra": (
        "Hledání podobných: seřazeno {count} spekter knihovny"
    ),
    "Imported {imported} references and matched against {count} spectra": (
        "Naimportováno {imported} referencí, porovnáno s {count} spektry"
    ),
    # ── Batch dialogs ───────────────────────────────────────────────────────
    "Folder:": "Složka:",
    "Input:": "Vstup:",
    "Output:": "Výstup:",
    "Browse...": "Procházet...",
    "Browse Input...": "Vybrat vstup...",
    "Browse Output...": "Vybrat výstup...",
    "Import": "Importovat",
    "Generate": "Vytvořit",
    "Export...": "Exportovat...",
    "Status": "Stav",
    "Reason": "Důvod",
    "Peak Count": "Počet píků",
    "Reference Name": "Název reference",
    "Output PDF": "Výstupní PDF",
    "Output Project": "Výstupní projekt",
    "When output exists:": "Když výstup už existuje:",
    "Skip existing": "Přeskočit existující",
    "Overwrite existing": "Přepsat existující",
    "Rename automatically": "Automaticky přejmenovat",
    "Auto-detect peaks": "Automaticky najít píky",
    "Detect peaks for import report": "Najít píky pro přehled importu",
    "Show a detected-peak count for each imported spectrum; matching still uses full spectra.": (
        "U každého importovaného spektra ukáže počet nalezených píků; "
        "porovnání dál pracuje s celými spektry."
    ),
    "Skip unchanged files already imported from the same path": (
        "Přeskočit nezměněné soubory, které už byly z téže cesty naimportovány"
    ),
    "Files with the same display name in different folders are still imported.": (
        "Soubory se stejným názvem v různých složkách se naimportují."
    ),
    "Select a folder and click Import.": "Vyberte složku a klikněte na Importovat.",
    "Choose input and output folders, then click Export.": (
        "Zvolte vstupní a výstupní složku a klikněte na Export."
    ),
    "Choose input and output folders, then click Generate.": (
        "Zvolte vstupní a výstupní složku a klikněte na Vytvořit."
    ),
    "Choose a folder containing .irproj files": "Zvolte složku se soubory .irproj",
    "Choose a folder containing .spa files": "Zvolte složku se soubory .spa",
    "Choose a folder containing SPA or JCAMP files": "Zvolte složku se soubory SPA nebo JCAMP",
    "Choose a folder for exported PDFs": "Zvolte složku pro exportovaná PDF",
    "Choose a folder for generated projects": "Zvolte složku pro vytvořené projekty",
    # ── About ───────────────────────────────────────────────────────────────
    "About": "O aplikaci",
    "About IR Spectra Analyzer": "O aplikaci IR Spectra Analyzer",
    "Professional IR spectrum analysis tool": "Profesionální nástroj pro analýzu IR spekter",
    # ── Vibration editor ────────────────────────────────────────────────────
    "Edit Vibration": "Upravit vibraci",
    "Edit \u201c{name}\u201d\u2026": "Upravit \u201e{name}\u201c\u2026",
    "Reset built-in vibrations to defaults\u2026": "Obnovit výchozí vestavěné vibrace\u2026",
    "Delete Vibration": "Smazat vibraci",
    "Delete \u201c{name}\u201d from the list?": "Smazat \u201e{name}\u201c ze seznamu?",
    "It can be brought back with \u201cReset built-in vibrations to defaults\u201d.": (
        "Lze ji vrátit volbou \u201eObnovit výchozí vestavěné vibrace\u201c."
    ),
    "A custom vibration cannot be brought back.": "Vlastní vibraci už nelze vrátit.",
    "Peaks that already carry it keep their assignment.": (
        "Píky, které ji už mají přiřazenou, si přiřazení ponechají."
    ),
    "Reset Built-in Vibrations": "Obnovit vestavěné vibrace",
    "Restore every built-in vibration to its original name, range and "
    "category, and bring back the ones that were deleted?\n\n"
    "Custom vibrations are not changed.": (
        "Vrátit všem vestavěným vibracím původní název, rozsah a kategorii "
        "a obnovit ty smazané?\n\nVlastní vibrace zůstanou beze změny."
    ),
    "Category:": "Kategorie:",
    "Note:": "Poznámka:",
    "optional note, e.g. a literature source": "nepovinná poznámka, např. zdroj v literatuře",
    "Section of the vibration list the entry appears in when grouped by type": (
        "Sekce seznamu vibrací, ve které se položka zobrazí při seskupení podle typu"
    ),
    "Built-in vibration, originally \u201c{name}\u201d": (
        "Vestavěná vibrace, původně \u201e{name}\u201c"
    ),
    "Rocking \u03c1": "Kývavé \u03c1",
    "Wagging \u03c9": "Vějířové \u03c9",
    # ── Export options ──────────────────────────────────────────────────────
    "CSV (text table)": "CSV (textová tabulka)",
    "Contents:": "Obsah:",
    "Whole analysis: metadata, peaks and spectrum": "Celá analýza: údaje, píky a spektrum",
    "Peak table only": "Jen tabulka píků",
    "Spectrum data only (wavenumber, intensity)": "Jen data spektra (vlnočet, intenzita)",
    "Numbers:": "Čísla:",
    "Decimal point (1.5)": "Desetinná tečka (1.5)",
    "Decimal comma (1,5)": "Desetinná čárka (1,5)",
    "Use the decimal comma for a Czech Excel, the decimal point for other software": (
        "Desetinnou čárku použijte pro český Excel, tečku pro ostatní programy"
    ),
    "Include spectrum chart in Excel": "Přidat do Excelu graf spektra",
    "Adds a chart of the spectrum to the Spectrum sheet, wavenumbers from 4000 to 400": (
        "Přidá na list Spectrum graf spektra s vlnočty od 4000 do 400"
    ),
    # ── Report options ──────────────────────────────────────────────────────
    "Single page: spectrum, metadata, structure and peaks": (
        "Jedna strana: spektrum, údaje, struktura a píky"
    ),
    "List every peak in the report's peak table, not only the assigned ones": (
        "Uvede v tabulce píků reportu všechny píky, nejen přiřazené"
    ),
    # ── IR text and spectrum image ──────────────────────────────────────────
    "Copy IR text": "Kopírovat zápis IR",
    "Copy the peak list as written in a protocol or paper, e.g.\n"
    "IR (cm\u207b\u00b9): 3340 (s, \u03bd(OH)), 1715 (vs, \u03bd(C=O)).\n"
    "Assigned peaks only; when none is assigned yet, all peaks.": (
        "Zkopíruje seznam píků tak, jak se píše do protokolu nebo publikace, např.\n"
        "IR (cm\u207b\u00b9): 3340 (s, \u03bd(OH)), 1715 (vs, \u03bd(C=O)).\n"
        "Jen přiřazené píky; dokud žádný přiřazený není, všechny."
    ),
    "IR text copied: {text}": "Zápis IR zkopírován: {text}",
    "No peaks to write as IR text": "Nejsou žádné píky pro zápis IR",
    "Copy Spectrum &Image": "Kopírovat &obrázek spektra",
    "Copy IR &Text": "Kopírovat &zápis IR",
    "Copy the spectrum, as drawn in the report, to paste into a protocol or slides": (
        "Zkopíruje spektrum tak, jak je v reportu, pro vložení do protokolu nebo prezentace"
    ),
    "Spectrum image copied to the clipboard": "Obrázek spektra zkopírován do schránky",
    "Copy Error": "Chyba při kopírování",
    "Failed to draw the spectrum:": "Spektrum se nepodařilo vykreslit:",
    "Spectrum image (PNG 300 dpi or SVG)": "Obrázek spektra (PNG 300 dpi nebo SVG)",
    "The spectrum alone, drawn as in the report, for a protocol, poster or slides": (
        "Samotné spektrum vykreslené jako v reportu, pro protokol, poster nebo prezentaci"
    ),
    "Export Spectrum Image": "Export obrázku spektra",
    "PNG image, 300 dpi (*.png)": "Obrázek PNG, 300 dpi (*.png)",
    "SVG vector image (*.svg)": "Vektorový obrázek SVG (*.svg)",
    "Failed to export image:": "Obrázek se nepodařilo exportovat:",
    "Image exported: {name}": "Obrázek exportován: {name}",
    "Double-click to assign\u2026": "Dvojklikem přiřadíte\u2026",
    "Double-click to edit the chemical structure": "Dvojklikem upravíte chemickou strukturu",
    "Double-click to draw or paste a structure": "Dvojklikem nakreslíte nebo vložíte strukturu",
    "Acquisition & file details": "Podrobnosti měření a souboru",
    # ── Molecule editor ─────────────────────────────────────────────────────
    "Edit Molecular Structure": "Úprava chemické struktury",
    "Draw": "Kreslení",
    "SMILES": "SMILES",
    "Enter SMILES (e.g. CCO)": "Zadejte SMILES (např. CCO)",
    "Enter SMILES to preview": "Zadejte SMILES pro náhled",
    "Preview": "Náhled",
    "Valid": "Platný",
    "Invalid SMILES": "Neplatný SMILES",
    "RDKit not installed": "RDKit není nainstalován",
    "Select / Move": "Výběr / přesun",
    "Erase": "Mazání",
    "Single Bond": "Jednoduchá vazba",
    "Double Bond": "Dvojná vazba",
    "Triple Bond": "Trojná vazba",
    "Wedge Up": "Klínová vazba (k divákovi)",
    "Hash Down": "Šrafovaná vazba (od diváka)",
    "Carbon Chain": "Uhlíkový řetězec",
    "Clean 2D": "Uspořádat 2D",
    "Fit View": "Přizpůsobit zobrazení",
    "Rings": "Kruhy",
    "IR Groups": "IR skupiny",
    "Elements": "Prvky",
    "Charge": "Náboj",
    "PT…": "PSP…",
    "Periodic table": "Periodická soustava prvků",
    "Periodic Table": "Periodická soustava prvků",
    "Click an element to use it in the drawing.": "Kliknutím vyberete prvek pro kreslení.",
    "Increase charge (+)": "Zvýšit náboj (+)",
    "Decrease charge (−)": "Snížit náboj (−)",
    "Attach {group} to an atom": "Připojit {group} k atomu",
    "Draw {element} atoms": "Kreslit atomy {element}",
    "Formula: {formula}": "Vzorec: {formula}",
    "MW: {mw}": "Mr: {mw}",
    "Cyclopropane": "Cyklopropan",
    "Cyclobutane": "Cyklobutan",
    "Cyclopentane": "Cyklopentan",
    "Cyclohexane": "Cyklohexan",
    "Cycloheptane": "Cykloheptan",
    "Benzene": "Benzen",
    "Naphthalene": "Naftalen",
    "Pyridine": "Pyridin",
    "Furan": "Furan",
    "Thiophene": "Thiofen",
    "Pyrrole": "Pyrrol",
    "Click to draw a bond, pick a ring or paste SMILES (Ctrl+V)": (
        "Kliknutím nakreslíte vazbu, vyberte kruh nebo vložte SMILES (Ctrl+V)"
    ),
    "Drag atoms to move them, drag empty space to select": (
        "Tažením atomů je přesunete, tažením v prázdném místě vyberete"
    ),
    "Click an atom or bond to delete it": "Kliknutím na atom nebo vazbu je smažete",
    "Click or drag to draw double bonds": "Kliknutím nebo tažením kreslíte dvojné vazby",
    "Click or drag to draw triple bonds": "Kliknutím nebo tažením kreslíte trojné vazby",
    "Wedge bond (towards viewer); click again to flip": (
        "Klínová vazba (k divákovi); dalším kliknutím ji otočíte"
    ),
    "Hashed bond (away from viewer); click again to flip": (
        "Šrafovaná vazba (od diváka); dalším kliknutím ji otočíte"
    ),
    "Drag to draw a carbon chain": "Tažením nakreslíte uhlíkový řetězec",
    "Click to place {symbol} or replace an atom": "Kliknutím umístíte {symbol} nebo nahradíte atom",
    "Click empty space, an atom or a bond to add the ring": (
        "Kruh přidáte kliknutím do prázdna, na atom nebo na vazbu"
    ),
    # ── Molecule editor: professional features ──────────────────────────────
    "Atom: type C, O, N, S, P, F, I, H, B, L (Cl), R (Br); +/− charge; "
    "Enter = label or group; Del removes": (
        "Atom: napište C, O, N, S, P, F, I, H, B, L (Cl), R (Br); +/− náboj; "
        "Enter = popisek nebo skupina; Del smaže"
    ),
    "Abbreviation, condensed formula or SMILES; * marks where it attaches.": (
        "Zkratka, zkrácený vzorec nebo SMILES; * označuje místo připojení."
    ),
    "Atom Properties": "Vlastnosti atomu",
    "Atom properties…": "Vlastnosti atomu…",
    "Atom {n} ({symbol})": "Atom {n} ({symbol})",
    "Attach to the atom you click next": "Připojí se k atomu, na který kliknete",
    "Bond": "Vazba",
    "Charge: {charge}": "Náboj: {charge}",
    "Click to place {name}; Esc cancels": "Kliknutím umístíte {name}; Esc zruší",
    "Click, then click in the drawing to add a counter-ion or solvent.": (
        "Klikněte a pak klikněte do kresby — přidá se protiion nebo rozpouštědlo."
    ),
    "Copy": "Kopírovat",
    "Copy InChI": "Kopírovat InChI",
    "Copy InChIKey": "Kopírovat InChIKey",
    "Copy MOL block": "Kopírovat MOL",
    "Copy SMILES": "Kopírovat SMILES",
    "Copy as image": "Kopírovat jako obrázek",
    "Copy structure": "Kopírovat strukturu",
    "Cut": "Vyjmout",
    "DBE: {dbe}": "DBE: {dbe}",
    "Delete atom": "Smazat atom",
    "Delete bond": "Smazat vazbu",
    "Delete selection": "Smazat výběr",
    "Double bond equivalents: rings + π bonds": "Stupeň nenasycenosti: kruhy + π vazby",
    "Duplicate": "Duplikovat",
    "Edit label…": "Upravit popisek…",
    "Element": "Prvek",
    "Exact mass: {mass}": "Přesná hmotnost: {mass}",
    "Export, import and hydrogens": "Export, import a vodíky",
    "Flip horizontally": "Překlopit vodorovně",
    "Flip vertically": "Překlopit svisle",
    "Hide explicit hydrogens": "Skrýt explicitní vodíky",
    "Hydrogens": "Vodíky",
    "Isotope (mass number)": "Izotop (nukleonové číslo)",
    "Keep this group in the list below": "Uloží skupinu do seznamu níže",
    "MOL / SDF files (*.mol *.sdf *.sd);;All files (*)": (
        "Soubory MOL / SDF (*.mol *.sdf *.sd);;Všechny soubory (*)"
    ),
    "MOL files (*.mol)": "Soubory MOL (*.mol)",
    "More": "Další",
    "Name of the group:": "Název skupiny:",
    "Not recognised": "Nerozpoznáno",
    "Open MOL/SDF file…": "Otevřít soubor MOL/SDF…",
    "Open Structure": "Otevřít strukturu",
    "Paste": "Vložit",
    "Place": "Umístit",
    "Radical": "Radikál",
    "Remove": "Odebrat",
    "Rotate left 15°": "Otočit doleva o 15°",
    "Rotate right 15°": "Otočit doprava o 15°",
    "Salts": "Soli",
    "Save Custom Group": "Uložit vlastní skupinu",
    "Save MOL file…": "Uložit soubor MOL…",
    "Save Structure": "Uložit strukturu",
    "Save as custom group…": "Uložit jako vlastní skupinu…",
    "Saved groups": "Uložené skupiny",
    "Save…": "Uložit…",
    "Select all": "Vybrat vše",
    "Selection ({count} atoms)": "Výběr ({count} atomů)",
    "Show R/S and E/Z labels": "Zobrazit označení R/S a E/Z",
    "Show all hydrogens": "Zobrazit všechny vodíky",
    "Show atom numbers": "Zobrazit čísla atomů",
    "Show hydrogens as atoms": "Zobrazit vodíky jako atomy",
    "Templates": "Šablony",
    "The clipboard holds no structure": "Ve schránce není žádná struktura",
    "The file could not be read": "Soubor se nepodařilo přečíst",
    "The file could not be saved": "Soubor se nepodařilo uložit",
    "The file holds no readable structure": "Soubor neobsahuje čitelnou strukturu",
    "The group could not be saved": "Skupinu se nepodařilo uložit",
    "Tip: select atoms, right-click and choose Save as custom group.": (
        "Tip: vyberte atomy, klikněte pravým tlačítkem a zvolte Uložit jako vlastní skupinu."
    ),
    "Type an element, group (OMe, CO2Et, NHBoc) or SMILES with *; Enter applies": (
        "Napište prvek, skupinu (OMe, CO2Et, NHBoc) nebo SMILES s *; Enter potvrdí"
    ),
    "Unknown label: {text}": "Neznámý popisek: {text}",
    "automatic": "automaticky",
    "divalent ••": "dvojmocný ••",
    "monovalent •": "jednomocný •",
    "natural": "přirozený",
    "none": "žádný",
    "{count} to check": "{count} ke kontrole",
    "{where}: too many bonds for this element": "{where}: příliš mnoho vazeb pro tento prvek",
    "{where}: unpaired electron (radical)": "{where}: nepárový elektron (radikál)",
    # ── Molecule editor: bonds, rings and sugars ────────────────────────────
    "1,4-Dioxane": "1,4-Dioxan",
    "Cyclohexane chair": "Cyklohexan – židličková konformace",
    "Longer bond": "Delší vazba",
    "Morpholine": "Morfolin",
    "O/N rings, chairs and sugars": "Kruhy s O/N, židličky a cukry",
    "Piperazine": "Piperazin",
    "Piperidine": "Piperidin",
    "Pyranose chair (oxane)": "Pyranosa – židličková konformace (oxan)",
    "Shorter bond": "Kratší vazba",
    "Standard length": "Standardní délka",
    "Tetrahydrofuran (oxolane)": "Tetrahydrofuran (oxolan)",
    "Tetrahydropyran (oxane)": "Tetrahydropyran (oxan)",
    "α-D-Glucopyranose (click an OH or atom to make a glycoside)": (
        "α-D-glukopyranosa (klik na OH nebo atom vytvoří glykosid)"
    ),
    "β-D-Glucopyranose (click an OH or atom to make a glycoside)": (
        "β-D-glukopyranosa (klik na OH nebo atom vytvoří glykosid)"
    ),
    "β-D-Ribofuranose (click an OH or atom to make a glycoside)": (
        "β-D-ribofuranosa (klik na OH nebo atom vytvoří glykosid)"
    ),
    # ── Molecule editor: bold bonds and free drawing ───────────────────────
    "Bold Bond": "Tučná vazba",
    "Bold bond": "Tučná vazba",
    "Bold bond (front edge of a chair or perspective drawing); "
    "click a bond to make it bold or thin": (
        "Tučná vazba (přední hrana židličky nebo perspektivy); klik na vazbu ji zesílí nebo zúží"
    ),
    "Bond: 1/2/3 order, W wedge, H hash, U wavy, B bold, +/− length, Del removes": (
        "Vazba: 1/2/3 násobnost, W klín, H šrafy, U vlnitá, B tučná, +/− délka, Del smaže"
    ),
    "Click or drag to draw bonds (Shift = longer, Alt = any angle); "
    "click a bond: single → double → triple → wedge → reversed wedge": (
        "Kreslete kliknutím nebo tažením (Shift = delší, Alt = libovolný úhel); "
        "klik na vazbu: jednoduchá → dvojná → trojná → klín → obrácený klín"
    ),
    "Pyrimidine": "Pyrimidin",
    "Imidazole": "Imidazol",
    "Indole": "Indol",
    "Quinoline": "Chinolin",
    "Wavy Bond": "Vlnitá vazba",
    "Wavy bond (unknown stereo)": "Vlnitá vazba (neurčená stereochemie)",
    "Wavy bond (unspecified or racemic stereochemistry)": (
        "Vlnitá vazba (neurčená nebo racemická stereochemie)"
    ),
    "Click an atom to attach {group}; drag from it to choose the direction": (
        "Kliknutím na atom připojíte {group}; tažením z atomu určíte směr vazby"
    ),
    "Click an atom to attach {name} (drag from it to choose the direction), "
    "or empty space to place it; Esc ends": (
        "Kliknutím na atom připojíte {name} (tažením z atomu určíte směr vazby), "
        "kliknutím do prázdna ji umístíte samostatně; Esc ukončí"
    ),
}
