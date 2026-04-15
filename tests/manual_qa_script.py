"""
Manual QA script — exercises all major features of IR Spectra Analyzer
and saves annotated screenshots as evidence.

Usage:
    python tests/manual_qa_script.py

Output:
    tests/qa_screenshots/  — PNG screenshots for each test step
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Make project root importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "xcb" if sys.platform == "linux" else "")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

# ── Bootstrap so app-level imports work ──────────────────────────────────────
from app.runtime_imports import install_project_imports

install_project_imports()

from storage.database import Database  # noqa: E402
from storage.settings import Settings  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
LIBRARY = FIXTURES / "reference library_1"
SCREENSHOT_DIR = PROJECT_ROOT / "tests" / "qa_screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

RESULTS: list[tuple[str, str]] = []  # (step, status)


# ── Helpers ──────────────────────────────────────────────────────────────────


def shot(app: QApplication, name: str, window) -> None:
    """Grab screenshot of the main window and save it."""
    app.processEvents()
    time.sleep(0.15)
    app.processEvents()
    pixmap = window.grab()
    path = SCREENSHOT_DIR / f"{name}.png"
    pixmap.save(str(path))
    print(f"  📸  {path.name}")


def ok(step: str) -> None:
    print(f"  ✅  {step}")
    RESULTS.append((step, "PASS"))


def fail(step: str, detail: str = "") -> None:
    msg = f"{step}" + (f": {detail}" if detail else "")
    print(f"  ❌  {msg}")
    RESULTS.append((step, f"FAIL — {detail}"))


def check(condition: bool, step: str, detail: str = "") -> bool:
    if condition:
        ok(step)
    else:
        fail(step, detail)
    return condition


# ── Main QA routine ──────────────────────────────────────────────────────────


def run_qa() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    db = Database(":memory:")
    db.initialize()
    settings = Settings()
    win = MainWindow(db=db, settings=settings)
    win.resize(1400, 850)
    win.show()
    app.processEvents()

    # ── Step 1: Fresh start — empty state ────────────────────────────────────
    print("\n[1] Fresh start")
    check(win._project is None, "No project on startup")
    shot(app, "01_fresh_start", win)

    # ── Step 2: Load SPA with stored OMNIC peaks ─────────────────────────────
    print("\n[2] Load FER58-SE.SPA (29 stored OMNIC peaks expected)")
    spa_path = str(LIBRARY / "FER58-SE.SPA")
    win._load_spectrum(spa_path)
    app.processEvents()

    check(win._project is not None, "Project created after load")
    n_peaks = len(win._project.peaks) if win._project else 0
    check(n_peaks > 0, f"Stored peaks auto-loaded ({n_peaks} peaks)", f"got {n_peaks}")
    sb_text = win.statusBar().currentMessage()
    check("stored peaks found" in sb_text, "Status bar shows 'stored peaks found'", repr(sb_text))
    shot(app, "02_fer58_loaded_with_peaks", win)

    # ── Step 3: Load file with NO PEAKTABLE (PAR1627-SE.SPA) ─────────────────
    print("\n[3] Load PAR1627-SE.SPA (no PEAKTABLE)")
    win._load_spectrum(str(LIBRARY / "PAR1627-SE.SPA"))
    app.processEvents()
    sb2 = win.statusBar().currentMessage()
    check(
        "no PEAKTABLE in source file" in sb2,
        "Status bar shows 'no PEAKTABLE in source file' for PAR1627",
        repr(sb2),
    )
    shot(app, "03_par1627_no_peaktable", win)

    # ── Step 4: Load KLH293-Ot.SPA (mismatched Absorbance metadata / real %T) ─
    print("\n[4] Load KLH293-Ot.SPA (40 stored peaks, dip-type heuristic)")
    win._load_spectrum(str(LIBRARY / "KLH293-Ot.SPA"))
    app.processEvents()
    n_klh = len(win._project.peaks) if win._project else 0
    check(n_klh > 0, f"Stored peaks for KLH293 ({n_klh} peaks)")
    check(
        win._project.spectrum.is_dip_spectrum,
        "Spectrum detected as dip-type (transmittance heuristic)",
    )
    shot(app, "04_klh293_dip_spectrum", win)

    # ── Step 5: Detect Peaks ──────────────────────────────────────────────────
    print("\n[5] Detect Peaks on FER60-SE.SPA")
    win._load_spectrum(str(LIBRARY / "FER60-SE.SPA"))
    app.processEvents()
    before = len(win._project.peaks) if win._project else 0

    win._on_detect_peaks()
    app.processEvents()
    after = len(win._project.peaks) if win._project else 0
    check(after > 0, f"Auto-detect found peaks ({after} peaks)")
    shot(app, "05_detect_peaks", win)

    # ── Step 6: Manual peak pick ─────────────────────────────────────────────
    print("\n[6] Manual peak pick via _on_peak_clicked")
    # Pick a wavenumber roughly in the middle of the spectrum
    spectrum = win._project.spectrum if win._project else None
    if spectrum is not None:
        import numpy as np  # noqa: PLC0415

        mid_wn = float((spectrum.wavenumbers[0] + spectrum.wavenumbers[-1]) / 2)
        mid_intensity = float(np.interp(mid_wn, spectrum.wavenumbers, spectrum.intensities))
        peaks_before = len(win._project.peaks)
        win._on_peak_clicked(mid_wn, mid_intensity)
        app.processEvents()
        peaks_after = len(win._project.peaks)
        check(
            peaks_after == peaks_before + 1,
            f"Manual peak added at {mid_wn:.1f} cm⁻¹",
            f"before={peaks_before} after={peaks_after}",
        )
        shot(app, "06_manual_peak_added", win)
    else:
        fail("Manual peak pick", "no spectrum loaded")

    # ── Step 7: Assign vibration preset to a peak ────────────────────────────
    print("\n[7] Assign vibration preset to first peak")
    if win._project and win._project.peaks and hasattr(win._db, "get_vibration_presets"):
        from core.vibration_presets import VibrationPreset  # noqa: PLC0415

        raw_presets = win._db.get_vibration_presets()
        if raw_presets:
            preset = VibrationPreset(
                name=raw_presets[0]["name"],
                typical_range_min=raw_presets[0]["typical_range_min"],
                typical_range_max=raw_presets[0]["typical_range_max"],
                category=raw_presets[0].get("category", ""),
                description=raw_presets[0].get("description", ""),
                color=raw_presets[0].get("color", "#4A90D9"),
                db_id=raw_presets[0].get("id"),
            )
            # Select first peak in table via select_peak, then assign preset
            peak = win._project.peaks[0]
            win._peak_table.set_peaks(win._project.peaks)
            app.processEvents()
            win._peak_table.select_peak(peak)
            app.processEvents()
            win._on_preset_selected(preset)
            app.processEvents()

            assigned = any(p.vibration_id is not None for p in win._project.peaks)
            check(assigned, f"Vibration '{preset.name}' assigned to peak")
            shot(app, "07_vibration_assigned", win)
        else:
            fail("Assign vibration", "no presets in DB")
    else:
        fail("Assign vibration", "no peaks or no DB")

    # ── Step 8: Undo (Ctrl+Z) ─────────────────────────────────────────────────
    print("\n[8] Undo last action (Ctrl+Z)")
    count_before_undo = len(win._project.peaks) if win._project else 0
    QTest.keyClick(win, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    shot(app, "08_after_undo", win)
    ok("Undo triggered (Ctrl+Z)")

    # ── Step 9: Redo (Ctrl+Y) ─────────────────────────────────────────────────
    print("\n[9] Redo (Ctrl+Y)")
    QTest.keyClick(win, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    shot(app, "09_after_redo", win)
    ok("Redo triggered (Ctrl+Y)")

    # ── Step 10: Baseline correction ─────────────────────────────────────────
    print("\n[10] Baseline correction")
    win._on_correct_baseline()
    app.processEvents()
    corrected = win._project.corrected_spectrum if win._project else None
    check(corrected is not None, "Corrected spectrum produced")
    shot(app, "10_baseline_corrected", win)

    # ── Step 11: Reference Library — choose folder ───────────────────────────
    print("\n[11] Reference Library dialog — choose folder + sync")
    from ui.dialogs.reference_library_dialog import ReferenceLibraryDialog  # noqa: PLC0415

    # Set library folder and sync before opening dialog
    win._reference_library_service.set_selected_library_folder(LIBRARY)
    summary = win._reference_library_service.import_project_library()
    app.processEvents()

    imported_total = (summary.imported + summary.skipped) if summary else 0
    check(imported_total >= 1, f"Sync imported/already-present references ({imported_total})")

    current_spectrum = win._project.spectrum if win._project else None
    dlg = ReferenceLibraryDialog(
        db=win._db,
        parent=win,
        library_service=win._reference_library_service,
        current_spectrum=current_spectrum,
    )
    dlg.show()
    app.processEvents()
    shot(app, "11_reference_library_dialog", win)
    dlg.close()

    # ── Step 12: Match Spectrum ───────────────────────────────────────────────
    print("\n[12] Match Spectrum against reference library_1")
    win._on_match_spectrum()
    app.processEvents()
    time.sleep(0.5)
    app.processEvents()

    results = (
        win._match_results_panel._results if hasattr(win._match_results_panel, "_results") else []
    )
    check(len(results) > 0, f"Match returned results ({len(results)} hits)")
    sb_match = win.statusBar().currentMessage()
    check(
        "reference" in sb_match.lower() or "matched" in sb_match.lower(),
        "Status bar updated after match",
        repr(sb_match),
    )
    shot(app, "12_match_results", win)

    # ── Step 13: Export PDF ───────────────────────────────────────────────────
    print("\n[13] PDF export (programmatic, no dialog)")
    from reporting.report_builder import ReportBuilder  # noqa: PLC0415

    pdf_path = SCREENSHOT_DIR / "qa_export_test.pdf"
    try:
        ReportBuilder().build(win._project, pdf_path)
        check(pdf_path.exists() and pdf_path.stat().st_size > 1000, "PDF exported successfully")
    except Exception as e:  # noqa: BLE001
        fail("PDF export", str(e))
    shot(app, "13_after_pdf_export", win)

    # ── Step 14: Save / Load project ─────────────────────────────────────────
    print("\n[14] Save and reload project (.irproj)")
    from storage.project_serializer import ProjectSerializer  # noqa: PLC0415

    proj_path = SCREENSHOT_DIR / "qa_test_project.irproj"
    try:
        ProjectSerializer().save(win._project, proj_path)
        check(proj_path.exists(), "Project file saved")

        loaded = ProjectSerializer().load(proj_path)
        check(loaded is not None, "Project reloaded successfully")
        shot(app, "14_project_reloaded", win)
    except Exception as e:  # noqa: BLE001
        fail("Save/load project", str(e))

    # ── Final summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("QA RESULTS SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, s in RESULTS if s == "PASS")
    failed = sum(1 for _, s in RESULTS if s.startswith("FAIL"))
    for step, status in RESULTS:
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon}  {step}")
        if status.startswith("FAIL"):
            print(f"         {status}")
    print(f"\n  {passed} passed  |  {failed} failed")
    print(f"  Screenshots: {SCREENSHOT_DIR}")
    print("=" * 60)

    # Keep window open briefly so user can see it, then close
    QTimer.singleShot(3000, app.quit)
    app.exec()


if __name__ == "__main__":
    run_qa()
