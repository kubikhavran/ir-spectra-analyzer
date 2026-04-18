"""Headless probe: verify JSME round-trips molecules with non-sidebar elements.

Loads a SMILES with a sodium atom into JSME, then reads back:
  - jsmeApplet.smiles()
  - jsmeApplet.molFile()
Succeeds if the Na atom survives the round-trip.

Not part of the regular pytest run (starts a real QApplication + QtWebEngine).
Run manually: python tests/jsme_custom_element_probe.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Bootstrap so app-level imports work when running this script directly
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.dialogs.molecule_editor_dialog import MoleculeEditorDialog  # noqa: E402

TEST_SMILES = "[Na]Cl"  # sodium chloride — Na is NOT on the JSME sidebar


def _run_js(view, js: str, timeout_ms: int = 2000) -> str:
    """Evaluate JS in the web view and block until the result arrives."""
    loop = QEventLoop()
    result: list = []

    def _done(value: object) -> None:
        result.append(value)
        loop.quit()

    view.page().runJavaScript(js, 0, _done)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return str(result[0]) if result else ""


def _wait_for_jsme(view, timeout_ms: int = 15000) -> bool:
    """Poll until `jsmeApplet` is non-null."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        ready = _run_js(view, "jsmeApplet ? 'yes' : 'no'", timeout_ms=500)
        if ready == "yes":
            return True
        # Spin the Qt event loop briefly
        loop = QEventLoop()
        QTimer.singleShot(250, loop.quit)
        loop.exec()
    return False


def main() -> int:
    _app = QApplication.instance() or QApplication(sys.argv)

    dlg = MoleculeEditorDialog(initial_smiles=TEST_SMILES)
    dlg.show()

    view = dlg._web_view
    if view is None:
        print("FAIL: JSME web view was not created (cache download failed?)")
        return 2

    # Wait for the page to load and JSME to initialize
    load_loop = QEventLoop()
    view.loadFinished.connect(lambda _ok: load_loop.quit())
    QTimer.singleShot(10000, load_loop.quit)
    load_loop.exec()

    if not _wait_for_jsme(view):
        print("FAIL: jsmeApplet never became ready")
        return 3

    # Give the _on_load_finished handler a beat to run the fix path:
    # SMILES → RDKit MOL block → jsmeApplet.readMolFile
    idle = QEventLoop()
    QTimer.singleShot(1500, idle.quit)
    idle.exec()

    initial_smiles_rendered = _run_js(view, "jsmeApplet.smiles()")
    initial_mol_rendered = _run_js(view, "jsmeApplet.molFile() || ''")
    print()
    print("=== FIX VERIFICATION: initial_smiles='[Na]Cl' through _on_load_finished ===")
    print(f"jsme.smiles() after initial load : {initial_smiles_rendered!r}")
    print(f"MOL after initial load has Na    : {'Na' in initial_mol_rendered}")
    fix_ok = "Na" in initial_mol_rendered or "Na" in initial_smiles_rendered
    print(f"FIX OK                           : {fix_ok}")
    print()

    # ----------------------------------------------------------------
    # Baseline: ensure readMolecule works at all on plain SMILES.
    # ----------------------------------------------------------------
    _run_js(view, "jsmeApplet.reset(); jsmeApplet.readMolecule('CCO');")
    idle0 = QEventLoop()
    QTimer.singleShot(500, idle0.quit)
    idle0.exec()
    ethanol_smiles = _run_js(view, "jsmeApplet.smiles()")
    print(f"Ethanol 'CCO' roundtrip : {ethanol_smiles!r}")

    # ----------------------------------------------------------------
    # Custom-element test: reading SMILES with [Na]
    # ----------------------------------------------------------------
    _run_js(view, "jsmeApplet.reset(); jsmeApplet.readMolecule('[Na]Cl');")
    idle1 = QEventLoop()
    QTimer.singleShot(500, idle1.quit)
    idle1.exec()

    smiles_back = _run_js(view, "jsmeApplet.smiles()")
    mol_back = _run_js(view, "jsmeApplet.molFile() || ''")

    print(f"Input SMILES  : {TEST_SMILES!r}")
    print(f"jsme.smiles() : {smiles_back!r}")
    print("jsme.molFile():")
    for line in mol_back.splitlines()[:20]:
        print(f"  {line}")

    # The SMILES may be canonicalized; accept either "[Na]" / "Na" substring.
    smiles_ok = "Na" in smiles_back
    mol_ok = "Na" in mol_back
    print()
    print(f"SMILES contains Na   : {smiles_ok}")
    print(f"MOL block contains Na: {mol_ok}")

    # ----------------------------------------------------------------
    # Alternative API: readGenericMolecularInput handles multiple formats.
    # ----------------------------------------------------------------
    _run_js(view, "jsmeApplet.reset();")
    has_generic = _run_js(
        view, "typeof jsmeApplet.readGenericMolecularInput === 'function' ? 'yes' : 'no'"
    )
    print(f"readGenericMolecularInput available: {has_generic}")
    if has_generic == "yes":
        _run_js(view, "jsmeApplet.readGenericMolecularInput('[Na]Cl');")
        idle_g = QEventLoop()
        QTimer.singleShot(500, idle_g.quit)
        idle_g.exec()
        gen_smiles = _run_js(view, "jsmeApplet.smiles()")
        print(f"readGeneric [Na]Cl → smiles: {gen_smiles!r}")

    # Inspect what functions the applet exposes so we know the real API surface.
    fn_list = _run_js(
        view,
        """
        (function() {
            var names = [];
            for (var k in jsmeApplet) {
                if (typeof jsmeApplet[k] === 'function') names.push(k);
            }
            return names.sort().join(',');
        })()
        """,
    )
    names = fn_list.split(",")
    print(f"JSME method count: {len(names)}")
    # print names matching read/smiles/set/load
    interesting = [
        n
        for n in names
        if any(kw in n.lower() for kw in ("read", "smiles", "set", "load", "paste", "input", "mol"))
    ]
    print("Interesting methods:")
    for n in interesting:
        print(f"  {n}")

    # Try alternative entry points
    print()
    print("--- Trying readGenericMolecularInput with explicit format ---")
    _run_js(view, "jsmeApplet.reset();")
    r1 = _run_js(
        view, "try{jsmeApplet.readGenericMolecularInput('[Na]Cl','smi');}catch(e){e.toString();}"
    )
    print(f"  call result     : {r1!r}")
    idle_r = QEventLoop()
    QTimer.singleShot(500, idle_r.quit)
    idle_r.exec()
    print(f"  smiles after    : {_run_js(view, 'jsmeApplet.smiles()')!r}")

    print()
    print("--- Trying readMolFile directly ---")
    mol_input = (
        "\\n  Custom\\n\\n  2  0  0  0  0  0  0  0  0  0999 V2000\\n"
        "    0.0000    0.0000    0.0000 Na  0  0  0  0  0  0  0  0  0  0  0  0\\n"
        "    1.5000    0.0000    0.0000 Cl  0  0  0  0  0  0  0  0  0  0  0  0\\n"
        "M  END\\n"
    )
    r2 = _run_js(view, f"try{{jsmeApplet.readMolFile('{mol_input}');}}catch(e){{e.toString();}}")
    print(f"  call result     : {r2!r}")
    idle_r2 = QEventLoop()
    QTimer.singleShot(500, idle_r2.quit)
    idle_r2.exec()
    print(f"  smiles after    : {_run_js(view, 'jsmeApplet.smiles()')!r}")
    mol_after = _run_js(view, "jsmeApplet.molFile() || ''")
    for line in mol_after.splitlines()[:10]:
        print(f"    {line}")

    # Now try the xatom keyboard workflow: switch JSME into xatom mode and
    # feed the symbol 'K' — this simulates what happens when the user
    # clicks the X button and types K on the keyboard.
    _run_js(
        view,
        """
        // JSME internal: state 32 = xatom keyboard-entry mode.
        // The xatom symbol buffer lives on the applet; the public API to set
        // it is jsmeApplet.setAction('x') followed by typed keys, but we can
        // shortcut by calling the internal 'setAtomAction' or by using
        // readMolecule on a crafted mol block. Simplest confirmation: check
        // that JSME exposes the keyboard mode state-machine.
        (function() {
            try {
                return typeof JSApplet !== 'undefined'
                    && typeof jsmeApplet !== 'undefined'
                    && typeof jsmeApplet.readMolecule === 'function';
            } catch (e) { return false; }
        })()
        """,
    )

    # Validate by reading a different custom-element molecule: iron chloride.
    _run_js(view, "jsmeApplet.readMolecule('[Fe](Cl)(Cl)Cl')")
    idle2 = QEventLoop()
    QTimer.singleShot(500, idle2.quit)
    idle2.exec()
    fe_smiles = _run_js(view, "jsmeApplet.smiles()")
    fe_mol = _run_js(view, "jsmeApplet.molFile() || ''")
    print()
    print("FeCl3 input   : '[Fe](Cl)(Cl)Cl'")
    print(f"jsme.smiles() : {fe_smiles!r}")
    print(f"MOL has Fe    : {'Fe' in fe_mol}")

    dlg.close()

    all_ok = fix_ok and "Fe" in fe_mol
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
