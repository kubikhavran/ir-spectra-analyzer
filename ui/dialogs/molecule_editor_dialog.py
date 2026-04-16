"""
MoleculeEditorDialog — Dialog for editing molecular structures.

Provides two tabs:
  - Draw: JSME visual structure editor (downloaded once to local cache)
  - SMILES: text-based input with live RDKit preview
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# JSME local cache helpers
# ---------------------------------------------------------------------------

_JSME_CACHE_DIR = Path.home() / ".ir-spectra-analyzer" / "jsme"
# Correct filename is lowercase jsme.nocache.js (unpkg.com/jsme-editor package, v2024.04.29)
_JSME_JS = _JSME_CACHE_DIR / "jsme.nocache.js"
_JSME_BASE_URL = "https://unpkg.com/jsme-editor"

_JSME_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; background: #ffffff; }}
  #jsme_container {{ width: 100%; }}
</style>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="jsme.nocache.js"></script>
</head>
<body>
<div id="jsme_container"></div>
<script>
var jsmeApplet = null;
var pyBridge = null;

new QWebChannel(qt.webChannelTransport, function(channel) {{
    pyBridge = channel.objects.pyBridge;
}});

function jsmeOnLoad() {{
    jsmeApplet = new JSApplet.JSME("jsme_container", "100%", "480px", {{
        "options": "query,autoez,zoomrestricted,nopastemolfile"
    }});
    jsmeApplet.setCallBack("AfterStructureModified", function() {{
        sendSMILES();
    }});
}}

function loadSMILES(smiles) {{
    if (jsmeApplet && smiles) {{
        jsmeApplet.readMolecule(smiles);
    }}
}}

function getSMILES() {{
    if (!jsmeApplet) return "";
    return jsmeApplet.smiles();
}}

function sendSMILES() {{
    if (pyBridge && jsmeApplet) {{
        pyBridge.receive_smiles(jsmeApplet.smiles());
    }}
}}

function sendCanvasPNG() {{
    if (!pyBridge) return;
    var svgs = document.querySelectorAll('#jsme_container svg');
    var svg = null;
    var maxArea = 0;
    for (var i = 0; i < svgs.length; i++) {{
        var box = svgs[i].getBoundingClientRect();
        var area = box.width * box.height;
        if (area > maxArea) {{
            maxArea = area;
            svg = svgs[i];
        }}
    }}
    if (!svg) {{
        var canvas = document.querySelector('#jsme_container canvas');
        if (canvas) {{
            pyBridge.receive_png(canvas.toDataURL('image/png'));
        }} else {{
            pyBridge.receive_png('');
        }}
        return;
    }}
    try {{
        var svgData = new XMLSerializer().serializeToString(svg);
        if (svgData.indexOf('xmlns="http://www.w3.org/2000/svg"') === -1) {{
            svgData = svgData.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
        }}
        var DOMURL = window.URL || window.webkitURL || window;
        var img = new Image();
        var svgBlob = new Blob([svgData], {{type: 'image/svg+xml;charset=utf-8'}});
        var url = DOMURL.createObjectURL(svgBlob);
        img.onload = function () {{
            try {{
                var canvas = document.createElement('canvas');
                var bbox = svg.getBoundingClientRect();
                canvas.width = bbox.width || 400;
                canvas.height = bbox.height || 400;
                var ctx = canvas.getContext('2d');
                ctx.fillStyle = '#ffffff';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                ctx.drawImage(img, 0, 0);
                DOMURL.revokeObjectURL(url);
                pyBridge.receive_png(canvas.toDataURL('image/png'));
            }} catch (e) {{
                pyBridge.receive_png('');
            }}
        }};
        img.onerror = function () {{
            pyBridge.receive_png('');
        }};
        img.src = url;
    }} catch (e) {{
        pyBridge.receive_png('');
    }}
}}

function sendMolFile() {{
    if (!pyBridge) return;
    var mol = "";
    if (jsmeApplet) {{
        try {{ mol = jsmeApplet.molFile() || ""; }} catch(e) {{ mol = ""; }}
    }}
    pyBridge.receive_mol_block(mol);
}}
</script>
</body>
</html>
"""


def _ensure_jsme_cached() -> Path | None:
    """Download JSME.nocache.js + companion .cache.js files to local cache.

    Parses the nocache loader to find the two GWT permutation hashes and
    downloads those .cache.js files alongside the loader. All files land in
    _JSME_CACHE_DIR so the HTML can reference them with relative paths.

    Returns the path to jsme.nocache.js, or None on any failure.
    """
    import re  # noqa: PLC0415

    if _JSME_JS.exists():
        return _JSME_JS
    try:
        _JSME_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # 1. Download the nocache loader
        loader_url = f"{_JSME_BASE_URL}/jsme.nocache.js"
        with urllib.request.urlopen(loader_url, timeout=10) as resp:  # noqa: S310
            loader_bytes = resp.read()
        _JSME_JS.write_bytes(loader_bytes)

        # 2. Find companion .cache.js hashes embedded in the loader
        loader_text = loader_bytes.decode("utf-8", errors="replace")
        hashes = re.findall(r"'([0-9A-F]{32})'", loader_text)
        unique_hashes = list(dict.fromkeys(hashes))  # deduplicate, preserve order

        # 3. Download each companion cache file
        for h in unique_hashes:
            cache_url = f"{_JSME_BASE_URL}/{h}.cache.js"
            dest = _JSME_CACHE_DIR / f"{h}.cache.js"
            if dest.exists():
                continue
            try:
                with urllib.request.urlopen(cache_url, timeout=15) as resp:  # noqa: S310
                    dest.write_bytes(resp.read())
            except Exception:  # noqa: BLE001
                pass  # non-fatal: the loader will skip unavailable permutations

        return _JSME_JS
    except Exception:  # noqa: BLE001
        return None


def _write_jsme_html() -> Path | None:
    """Write editor.html into _JSME_CACHE_DIR (same dir as the JS files).

    The HTML uses relative src="jsme.nocache.js" so it works via file:// URL.
    Returns the html path or None on failure.
    """
    try:
        _JSME_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        html_path = _JSME_CACHE_DIR / "editor.html"
        html_path.write_text(_JSME_HTML_TEMPLATE.format(), encoding="utf-8")
        return html_path
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# JS ↔ Python bridge
# ---------------------------------------------------------------------------


class _JSBridge(QObject):
    """Receives SMILES, PNG, and MOL block from JavaScript via QWebChannel."""

    smiles_received = Signal(str)
    png_received = Signal(str)
    mol_block_received = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._last_smiles: str = ""

    @Slot(str)
    def receive_smiles(self, smiles: str) -> None:
        self._last_smiles = smiles
        self.smiles_received.emit(smiles)

    @Slot(str)
    def receive_png(self, b64_str: str) -> None:
        self.png_received.emit(b64_str)

    @Slot(str)
    def receive_mol_block(self, mol_block: str) -> None:
        self.mol_block_received.emit(mol_block)

    @property
    def last_smiles(self) -> str:
        return self._last_smiles


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


class MoleculeEditorDialog(QDialog):
    """Dialog for editing a molecular structure.

    Tab 1 — Draw: JSME web-based editor (downloaded once to local cache).
    Tab 2 — SMILES: text input with live RDKit preview.
    """

    def __init__(self, initial_smiles: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Molecular Structure")
        self.resize(620, 560)

        self._initial_smiles = initial_smiles
        self._draw_smiles: str = initial_smiles  # updated by JS bridge
        self._accepted_smiles: str = ""
        self._canvas_png_bytes: bytes = b""
        self._canvas_mol_block: str = ""
        self._web_view: QWebEngineView | None = None

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        self._tabs.addTab(self._build_draw_tab(), "Draw")
        self._tabs.addTab(self._build_smiles_tab(), "SMILES")

        # Button box
        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton("OK", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        clear_btn = buttons.addButton("Clear", QDialogButtonBox.ButtonRole.ResetRole)

        ok_btn.clicked.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        clear_btn.clicked.connect(self._on_clear)

        layout.addWidget(buttons)

    def _build_draw_tab(self) -> QWidget:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)

        jsme_path = _ensure_jsme_cached()
        if jsme_path is None:
            # No JSME available — show fallback label, auto-switch to SMILES tab
            fallback = QLabel(
                "Could not load JSME editor. Check your internet connection and try "
                "reopening this dialog. You can use the SMILES tab in the meantime."
            )
            fallback.setWordWrap(True)
            fallback.setAlignment(Qt.AlignmentFlag.AlignTop)
            fallback.setObjectName("jsme_fallback_label")
            vbox.addWidget(fallback)
            vbox.addStretch()
            # Switch to SMILES tab after construction finishes
            QTimer.singleShot(0, lambda: self._tabs.setCurrentIndex(1))
            return container

        html_path = _write_jsme_html()
        if html_path is None:
            fallback = QLabel(
                "Could not write JSME HTML file. You can use the SMILES tab in the meantime."
            )
            fallback.setWordWrap(True)
            fallback.setAlignment(Qt.AlignmentFlag.AlignTop)
            fallback.setObjectName("jsme_fallback_label")
            vbox.addWidget(fallback)
            vbox.addStretch()
            QTimer.singleShot(0, lambda: self._tabs.setCurrentIndex(1))
            return container

        # Web view
        self._web_view = QWebEngineView()
        self._web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Allow local file to load qrc:// WebChannel resource
        settings = self._web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        # Set up web channel
        self._channel = QWebChannel()
        self._js_bridge = _JSBridge(self)
        self._channel.registerObject("pyBridge", self._js_bridge)
        self._web_view.page().setWebChannel(self._channel)

        # Load the JSME HTML from local disk via file:// URL
        self._web_view.load(QUrl.fromLocalFile(str(html_path)))
        self._web_view.loadFinished.connect(self._on_load_finished)

        vbox.addWidget(self._web_view)

        info = QLabel(
            "Draw a structure above. If the editor does not load, switch to the SMILES tab."
        )
        info.setWordWrap(True)
        vbox.addWidget(info)

        return container

    def _build_smiles_tab(self) -> QWidget:
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)

        # Input row
        input_row = QHBoxLayout()
        self._smiles_input = QLineEdit()
        self._smiles_input.setPlaceholderText("Enter SMILES (e.g. CCO)")
        if self._initial_smiles:
            self._smiles_input.setText(self._initial_smiles)
        self._preview_btn = QPushButton("Preview")
        input_row.addWidget(self._smiles_input)
        input_row.addWidget(self._preview_btn)
        vbox.addLayout(input_row)

        # Status label
        self._smiles_status = QLabel("")
        vbox.addWidget(self._smiles_status)

        # Preview image
        self._smiles_preview = QLabel("Enter SMILES to preview")
        self._smiles_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._smiles_preview.setMinimumSize(300, 300)
        self._smiles_preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._smiles_preview.setStyleSheet("background: white; border: 1px solid #ccc;")
        vbox.addWidget(self._smiles_preview)

        # Trigger initial preview if SMILES provided
        if self._initial_smiles:
            self._update_smiles_preview(self._initial_smiles)

        return container

    # ------------------------------------------------------------------
    # Signal connections
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        if self._web_view is not None:
            self._js_bridge.smiles_received.connect(self._on_draw_smiles_updated)
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        self._smiles_input.returnPressed.connect(self._on_preview_clicked)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_load_finished(self, ok: bool) -> None:  # noqa: FBT001
        """Load initial SMILES into JSME after page is ready."""
        if ok and self._initial_smiles and self._web_view is not None:
            js = f"loadSMILES({json.dumps(self._initial_smiles)})"
            self._web_view.page().runJavaScript(js)

    def _on_draw_smiles_updated(self, smiles: str) -> None:
        self._draw_smiles = smiles

    def _on_preview_clicked(self) -> None:
        smiles = self._smiles_input.text().strip()
        self._update_smiles_preview(smiles)

    def _update_smiles_preview(self, smiles: str) -> None:
        if not smiles:
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText("Enter SMILES to preview")
            self._smiles_status.setText("")
            return

        try:
            from chemistry.structure_renderer import render_smiles_to_png  # noqa: PLC0415

            png_bytes = render_smiles_to_png(smiles, (300, 300))
        except Exception:  # noqa: BLE001
            png_bytes = None
            self._smiles_status.setText("RDKit not installed")
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText("Enter SMILES to preview")
            return

        if png_bytes is None:
            self._smiles_status.setText("Invalid SMILES")
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText("Enter SMILES to preview")
        else:
            self._smiles_status.setText("Valid")
            image = QImage.fromData(png_bytes)
            pixmap = QPixmap.fromImage(image)
            self._smiles_preview.setPixmap(
                pixmap.scaled(
                    self._smiles_preview.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _on_ok(self) -> None:
        """Collect SMILES from the active tab and accept the dialog."""
        active = self._tabs.currentIndex()
        if active == 0 and self._web_view is not None:
            # Draw tab — flush JS bridge synchronously, then read.
            # _flush_canvas_png() is no longer called: PDF rendering uses
            # RDKit SVG, so the canvas screenshot is not needed.
            self._flush_draw_smiles()
            self._flush_mol_block()
            self._accepted_smiles = self._draw_smiles
        else:
            self._accepted_smiles = self._smiles_input.text().strip()
        self.accept()

    def _flush_mol_block(self) -> None:
        """Trigger JS to send current MOL block and wait for response.

        Tries the QWebChannel bridge first; falls back to direct JS evaluation
        if the bridge is not yet ready (QWebChannel init is asynchronous).
        """
        if self._web_view is None:
            return

        # --- Bridge path ---
        loop = QEventLoop()
        received: list[str] = []

        def _on_received(s: str) -> None:
            received.append(s)
            loop.quit()

        self._js_bridge.mol_block_received.connect(_on_received)
        self._web_view.page().runJavaScript("sendMolFile()")
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        self._js_bridge.mol_block_received.disconnect(_on_received)
        if received and received[0]:
            self._canvas_mol_block = received[0]
            return

        # --- Direct JS eval fallback (bridge not ready yet) ---
        loop2 = QEventLoop()
        direct: list[str] = []

        def _got_mol(s: object) -> None:
            direct.append(str(s) if s else "")
            loop2.quit()

        self._web_view.page().runJavaScript(
            "(jsmeApplet ? (jsmeApplet.molFile() || '') : '')", 0, _got_mol
        )
        QTimer.singleShot(500, loop2.quit)
        loop2.exec()
        if direct and direct[0]:
            self._canvas_mol_block = direct[0]

    def _flush_draw_smiles(self) -> None:
        """Trigger JS to send current SMILES and process events so bridge fires.

        Tries the QWebChannel bridge first; falls back to direct JS evaluation
        if the bridge is not yet ready (QWebChannel init is asynchronous).
        """
        if self._web_view is None:
            return

        # --- Bridge path ---
        loop = QEventLoop()
        received: list[str] = []

        def _on_received(s: str) -> None:
            received.append(s)
            loop.quit()

        self._js_bridge.smiles_received.connect(_on_received)
        self._web_view.page().runJavaScript("sendSMILES()")
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        self._js_bridge.smiles_received.disconnect(_on_received)
        if received and received[0]:
            self._draw_smiles = received[0]
            return

        # --- Direct JS eval fallback (bridge not ready yet) ---
        loop2 = QEventLoop()
        direct: list[str] = []

        def _got_smiles(s: object) -> None:
            direct.append(str(s) if s else "")
            loop2.quit()

        self._web_view.page().runJavaScript("getSMILES()", 0, _got_smiles)
        QTimer.singleShot(500, loop2.quit)
        loop2.exec()
        if direct and direct[0]:
            self._draw_smiles = direct[0]

    def _on_clear(self) -> None:
        """Clear the SMILES in the active tab."""
        active = self._tabs.currentIndex()
        if active == 0 and self._web_view is not None:
            self._web_view.page().runJavaScript("if(jsmeApplet) jsmeApplet.reset();")
            self._draw_smiles = ""
        else:
            self._smiles_input.clear()
            self._smiles_preview.setText("Enter SMILES to preview")
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_status.setText("")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def smiles(self) -> str:
        """Return the SMILES from whichever tab is currently active.

        After the dialog has been accepted, returns the value committed on OK.
        """
        return self._accepted_smiles

    def png_bytes(self) -> bytes:
        """Return the canvas PNG captured from the Draw tab (empty bytes if not available)."""
        return self._canvas_png_bytes

    def mol_block(self) -> str:
        """Return the MOL V2000 block captured from the Draw tab (empty if unavailable)."""
        return self._canvas_mol_block
