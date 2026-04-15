"""
QA script: manually test the JSME molecule editor.

Launches the MoleculeEditorDialog, waits for JSME to load, then injects
several SMILES strings (simple ring, polycyclic, with substituents) via JS,
takes screenshots, and reports the round-trip SMILES back from JS.

Usage:
    source .venv/bin/activate
    python tests/qa_jsme_editor.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use real display on macOS
if sys.platform == "darwin":
    os.environ.pop("QT_QPA_PLATFORM", None)
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.runtime_imports import install_project_imports  # noqa: E402

install_project_imports()

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

SHOT_DIR = PROJECT_ROOT / "tests" / "qa_screenshots"
SHOT_DIR.mkdir(exist_ok=True)

TEST_MOLECULES = [
    ("benzene", "c1ccccc1"),
    ("naphthalene", "c1ccc2ccccc2c1"),
    ("anthracene", "c1ccc2cc3ccccc3cc2c1"),
    ("caffeine_poly", "Cn1cnc2c1c(=O)n(C)c(=O)n2C"),
    ("ibuprofen", "CC(C)Cc1ccc(cc1)C(C)C(=O)O"),
]

RESULTS: list[tuple[str, str]] = []


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def run() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog  # noqa: PLC0415

    print("\n=== JSME Editor QA ===\n")

    dlg = MoleculeEditorDialog(initial_smiles="")
    dlg.resize(700, 600)
    dlg.show()
    app.processEvents()

    # Wait for page to load (up to 5 s)
    if dlg._web_view is None:
        print("[WARN] web_view is None — JSME not available, abort")
        return

    # Poll until jsmeApplet AND pyBridge are both ready (up to 10 s)
    print("Waiting for JSME + QWebChannel bridge...", end="", flush=True)
    ready = False
    for tick in range(100):
        state: list[dict] = []

        def _got_state(r: object, _s: list = state) -> None:
            _s.append(r)

        dlg._web_view.page().runJavaScript(
            "JSON.stringify({jsme: jsmeApplet !== null, bridge: pyBridge !== null})",
            _got_state,
        )
        wait(100)
        if state and isinstance(state[0], str):
            import json as _json  # noqa: PLC0415

            try:
                info = _json.loads(state[0])
                if info.get("jsme") and info.get("bridge"):
                    ready = True
                    break
            except Exception:  # noqa: BLE001
                pass
        if tick % 10 == 9:
            print(".", end="", flush=True)

    if not ready:
        # Report last known state
        print(f" TIMEOUT (last state: {state})")
    else:
        print(f" ready after {(tick + 1) * 100} ms")

    # Screenshot: empty editor
    pix = dlg.grab()
    pix.save(str(SHOT_DIR / "jsme_01_empty.png"))
    print("  screenshot: jsme_01_empty.png")

    for idx, (name, smiles) in enumerate(TEST_MOLECULES, start=2):
        print(f"\n[{idx}] Loading {name} ({smiles})")

        # Inject SMILES into JSME via JS
        dlg._web_view.page().runJavaScript(f"loadSMILES({smiles!r})")
        wait(1000)  # give JSME time to render + trigger AfterStructureModified

        # Read SMILES back (the AfterStructureModified callback should have
        # already updated _draw_smiles; we also try a fresh sendSMILES flush)
        received: list[str] = []

        def _got(s: str, _r: list = received) -> None:
            _r.append(s)

        dlg._js_bridge.smiles_received.connect(_got)
        dlg._web_view.page().runJavaScript("sendSMILES()")
        wait(600)
        dlg._js_bridge.smiles_received.disconnect(_got)

        cached = dlg._draw_smiles  # set by AfterStructureModified callback
        roundtrip = received[0] if received else cached if cached else "(no response)"

        # Screenshot
        fname = f"jsme_{idx:02d}_{name}.png"
        pix = dlg.grab()
        pix.save(str(SHOT_DIR / fname))
        print(f"  in:       {smiles}")
        print(f"  cached:   {cached!r}")
        print(f"  roundtrip:{roundtrip!r}")
        print(f"  screenshot: {fname}")

        ok = bool(roundtrip and roundtrip.strip() and roundtrip != "(no response)")
        RESULTS.append((name, "PASS" if ok else "FAIL"))

    # Final: leave caffeine loaded and keep window open briefly
    print("\n--- Results ---")
    for name, status in RESULTS:
        icon = "✅" if status == "PASS" else "❌"
        print(f"  {icon}  {name}")

    print(f"\nScreenshots saved to: {SHOT_DIR}")
    print("Closing in 3 s...")
    QTimer.singleShot(3000, app.quit)
    app.exec()


if __name__ == "__main__":
    run()
