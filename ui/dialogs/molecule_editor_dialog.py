"""
MoleculeEditorDialog — Dialog for editing molecular structures.

Provides two tabs:
  - Draw: JSME visual structure editor (downloaded once to local cache)
  - SMILES: text-based input with live RDKit preview
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
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

_JSME_VERSION = "2024.4.29"
_JSME_CACHE_DIR = Path.home() / ".ir-spectra-analyzer" / "jsme" / _JSME_VERSION
# Correct filename is lowercase jsme.nocache.js.
_JSME_JS = _JSME_CACHE_DIR / "jsme.nocache.js"
_JSME_BASE_URL = f"https://unpkg.com/jsme-editor@{_JSME_VERSION}"
_JSME_LOADER_SHA256 = "ab4e6d3a74f6539332f894351af64413f8c2ceab1513bab3e25758866c1ad7ff"
_JSME_MAX_FILE_BYTES = 16 * 1024 * 1024

# GWT companion stylesheets loaded by the nocache bootstrap. Without these
# files on disk next to the JS, JSME's element-picker dialog (the popup that
# opens when the user clicks the "X" button in the side bar to choose
# elements other than the default C/N/O/S/F/Cl/Br/I/P) renders as an
# unstyled, effectively invisible GWT DialogBox.
_JSME_CSS_REFS: tuple[str, ...] = (
    "jsa.css",
    "gwt/chrome/chrome.css",
    "gwt/chrome/mosaic.css",
)

_JSME_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; width: 100%; background: #ffffff; }}
  #jsme_container {{ width: 100%; }}
  /* Allow GWT popup panels (element picker, context menus) to overflow their
     parent jsa-resetDiv containers which default to overflow:hidden. Without
     this the periodic-table dialog that opens when the user clicks X is
     clipped and never becomes visible. */
  .jsa-resetDiv {{ overflow: visible !important; }}
  /* Ensure GWT popups sit above all JSME overlay divs. */
  .gwt-PopupPanel,
  .gwt-DecoratedPopupPanel,
  .gwt-DialogBox {{ z-index: 99999 !important; }}
</style>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="jsme.nocache.js"></script>
</head>
<body>
<div id="jsme_container"></div>
<script>
var jsmeApplet = null;
var pyBridge = null;
// Structures requested before JSME finished its async GWT bootstrap are
// queued here and applied inside jsmeOnLoad. Qt's loadFinished fires before
// jsmeOnLoad, so without this queue the initial structure is silently lost
// and re-opening the editor always shows an empty canvas.
var pendingMolBlock = null;
var pendingSmiles = null;

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
    if (pendingMolBlock) {{
        jsmeApplet.readMolFile(pendingMolBlock);
        pendingMolBlock = null;
        pendingSmiles = null;
    }} else if (pendingSmiles) {{
        jsmeApplet.readMolecule(pendingSmiles);
        pendingSmiles = null;
    }}
}}

function loadSMILES(smiles) {{
    // Fallback only — the SMILES path goes through loadMolBlock (see
    // _on_load_finished) because jsmeApplet.readMolecule() silently fails in
    // the packaged JSME build. Kept as a last-resort escape hatch.
    if (!smiles) return;
    if (jsmeApplet) {{
        jsmeApplet.readMolecule(smiles);
    }} else {{
        pendingSmiles = smiles;
    }}
}}

function loadMolBlock(mol) {{
    if (!mol) return;
    if (jsmeApplet) {{
        jsmeApplet.readMolFile(mol);
    }} else {{
        pendingMolBlock = mol;
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


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write one cache asset completely before exposing its final filename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                # Preserve the error that prevented the atomic replacement.
                # A leftover uniquely named temp file is harmless and can be
                # cleaned by the user/OS later.
                pass


def _validate_jsme_asset_url(url: str) -> None:
    parsed = urlparse(url)
    expected_prefix = f"/jsme-editor@{_JSME_VERSION}/"
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Unexpected JSME download URL") from exc
    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != "unpkg.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not decoded_path.startswith(expected_prefix)
        or any(part in {".", ".."} for part in decoded_path.split("/"))
    ):
        raise ValueError("Unexpected JSME download redirect")


class _JSMERedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject an untrusted redirect before urllib contacts its destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_jsme_asset_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_jsme_asset(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
) -> bytes:
    """Download one pinned JSME asset with a size guard and atomic cache write."""
    _validate_jsme_asset_url(url)
    opener = urllib.request.build_opener(_JSMERedirectHandler())
    with opener.open(url, timeout=15) as response:  # noqa: S310
        _validate_jsme_asset_url(response.geturl())
        declared = response.headers.get("Content-Length")
        if declared:
            try:
                declared_size = int(declared)
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > _JSME_MAX_FILE_BYTES:
                raise ValueError("JSME asset is too large")
        payload = bytes(response.read(_JSME_MAX_FILE_BYTES + 1))
    if not payload or len(payload) > _JSME_MAX_FILE_BYTES:
        raise ValueError("JSME asset is empty or too large")
    if expected_sha256 and hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("JSME loader checksum mismatch")
    _atomic_write_bytes(destination, payload)
    return payload


def _read_cached_asset(path: Path, *, expected_sha256: str | None = None) -> bytes | None:
    if not path.exists():
        return None
    size = path.stat().st_size
    if size <= 0 or size > _JSME_MAX_FILE_BYTES:
        return None
    payload = path.read_bytes()
    if expected_sha256 and hashlib.sha256(payload).hexdigest() != expected_sha256:
        return None
    return payload


def _ensure_jsme_cached() -> Path | None:
    """Download JSME.nocache.js + companion .cache.js and GWT css files.

    Parses the nocache loader to find the two GWT permutation hashes and
    downloads those .cache.js files alongside the loader. Also downloads the
    GWT stylesheets (jsa.css + gwt/chrome/*.css) that the nocache loader
    injects at runtime — those are required for the element-picker dialog to
    render. All files land in _JSME_CACHE_DIR so the HTML can reference them
    with relative paths.

    Returns the path to jsme.nocache.js, or None on any failure.
    """
    import re  # noqa: PLC0415

    try:
        _JSME_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        loader_bytes = _read_cached_asset(
            _JSME_JS,
            expected_sha256=_JSME_LOADER_SHA256,
        )
        if loader_bytes is None:
            # 1. Download the nocache loader
            loader_url = f"{_JSME_BASE_URL}/jsme.nocache.js"
            loader_bytes = _download_jsme_asset(
                loader_url,
                _JSME_JS,
                expected_sha256=_JSME_LOADER_SHA256,
            )

        # 2. Find companion .cache.js hashes embedded in the loader
        loader_text = loader_bytes.decode("utf-8", errors="replace")
        hashes = re.findall(r"'([0-9A-F]{32})'", loader_text)
        unique_hashes = list(dict.fromkeys(hashes))  # deduplicate, preserve order

        # 3. Download each companion cache file
        for h in unique_hashes:
            cache_url = f"{_JSME_BASE_URL}/{h}.cache.js"
            dest = _JSME_CACHE_DIR / f"{h}.cache.js"
            if _read_cached_asset(dest) is not None:
                continue
            dest.unlink(missing_ok=True)
            try:
                _download_jsme_asset(cache_url, dest)
            except Exception:  # noqa: BLE001
                pass  # non-fatal: the loader will skip unavailable permutations

        # 4. Download GWT runAsync() deferred fragments. JSME uses code-splitting
        # for on-demand features — the periodic-table element picker that opens
        # when the user clicks "X" (or presses X on the keyboard) lives in one
        # of these fragments. Without them, GWT shows a "Loading JS code
        # failed." modal and the user cannot select elements like Na, K, Fe, ...
        # Fragments are at <base>/deferredjs/<HASH>/<N>.cache.js; N starts at 1
        # and is contiguous until we hit a 404.
        for h in unique_hashes:
            frag_dir = _JSME_CACHE_DIR / "deferredjs" / h
            frag_dir.mkdir(parents=True, exist_ok=True)
            n = 1
            while n < 64:  # sanity cap; JSME currently has 11 fragments
                dest = frag_dir / f"{n}.cache.js"
                if _read_cached_asset(dest) is not None:
                    n += 1
                    continue
                dest.unlink(missing_ok=True)
                frag_url = f"{_JSME_BASE_URL}/deferredjs/{h}/{n}.cache.js"
                try:
                    _download_jsme_asset(frag_url, dest)
                except urllib.error.HTTPError as e:
                    if e.code == 404:
                        break  # no more fragments for this permutation
                    n += 1  # other errors: skip this one, try next
                    continue
                except Exception:  # noqa: BLE001
                    break  # network failure — stop trying more fragments
                n += 1

        # 5. Download the GWT stylesheets (jsa.css, gwt/chrome/*.css) that the
        # nocache bootstrap injects at runtime. Without them the GWT DialogBox
        # that hosts the periodic-table element picker has no layout and the
        # popup is effectively invisible to the user.
        for rel in _JSME_CSS_REFS:
            dest = _JSME_CACHE_DIR / rel
            if _read_cached_asset(dest) is not None:
                continue
            dest.unlink(missing_ok=True)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                css_url = f"{_JSME_BASE_URL}/{rel}"
                _download_jsme_asset(css_url, dest)
            except Exception:  # noqa: BLE001
                pass  # non-fatal: JSME still loads, just without styled popups

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
        _atomic_write_bytes(html_path, _JSME_HTML_TEMPLATE.format().encode("utf-8"))
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


class _JSMERequestInterceptor(QWebEngineUrlRequestInterceptor):
    """Allow only bundled Qt resources and files inside the pinned JSME cache."""

    def __init__(self, cache_root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache_root = cache_root.resolve()

    def interceptRequest(self, info) -> None:  # noqa: N802
        url = info.requestUrl()
        scheme = url.scheme().casefold()
        if scheme == "file":
            try:
                candidate = Path(url.toLocalFile()).resolve()
                allowed = candidate == self._cache_root or self._cache_root in candidate.parents
            except OSError:
                allowed = False
            info.block(not allowed)
            return
        info.block(scheme not in {"qrc", "data", "blob", "about"})


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


class MoleculeEditorDialog(QDialog):
    """Dialog for editing a molecular structure.

    Tab 1 — Draw: JSME web-based editor (downloaded once to local cache).
    Tab 2 — SMILES: text input with live RDKit preview.
    """

    def __init__(self, initial_smiles: str = "", initial_mol_block: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Molecular Structure")
        self.resize(620, 680)

        self._initial_smiles = initial_smiles
        self._initial_mol_block = initial_mol_block
        self._draw_smiles: str = initial_smiles  # updated by JS bridge
        self._accepted_smiles: str = ""
        self._canvas_png_bytes: bytes = b""
        self._canvas_mol_block: str = ""
        self._web_view: QWebEngineView | None = None
        self._web_profile: QWebEngineProfile | None = None
        self._web_page: QWebEnginePage | None = None

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
        # A dedicated off-the-record profile keeps the cache-only request
        # policy local to this dialog instead of mutating Qt's shared default
        # profile (which may serve other web views).
        self._web_profile = QWebEngineProfile()
        self._web_page = QWebEnginePage(self._web_profile, self._web_view)
        self._web_view.setPage(self._web_page)
        # The non-default profile must outlive its page. Keep it unparented
        # (so widget teardown cannot delete it first) and queue its deletion
        # directly from the page's destroyed signal.
        self._web_page.destroyed.connect(self._web_profile.deleteLater)

        # Allow local file to load qrc:// WebChannel resource
        settings = self._web_view.settings()
        # JSME is a set of local GWT fragments, so local file access is required.
        # Scope it to the versioned cache and deny every remote request.
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self._request_interceptor = _JSMERequestInterceptor(_JSME_CACHE_DIR, self._web_profile)
        self._web_profile.setUrlRequestInterceptor(self._request_interceptor)

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
            "Draw a structure above. For elements not in the side bar (e.g. Na, K, Fe, Mg), "
            "click the <b>X</b> button, then type the element symbol on the keyboard and "
            "click the atom you want to replace. Use the SMILES tab if the editor does not load."
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
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
        """Load the initial structure into JSME after the page is ready.

        JSME's ``readMolecule(SMILES)`` silently drops the molecule in the
        packaged build — even trivial inputs like ``CCO`` fail to render. We
        convert SMILES → V2000 MOL via RDKit and feed JSME through
        ``readMolFile`` instead, which works for all elements including ones
        that are not on the default sidebar (Na, K, Fe, ...).
        """
        if not (ok and self._web_view is not None):
            return
        if not (self._initial_smiles or self._initial_mol_block):
            return

        # Prefer the stored MOL block: it preserves the exact 2D layout the
        # user drew last time, and it works without RDKit.
        mol_block: str | None = self._initial_mol_block
        if not mol_block and self._initial_smiles:
            from chemistry.structure_renderer import smiles_to_mol_block  # noqa: PLC0415

            mol_block = smiles_to_mol_block(self._initial_smiles)
        if mol_block:
            js = f"loadMolBlock({json.dumps(mol_block)})"
        else:
            # RDKit unavailable or parse failure — fall back to the raw-SMILES
            # path. It may still fail inside JSME, but that's no worse than
            # doing nothing.
            js = f"loadSMILES({json.dumps(self._initial_smiles)})"
        self._web_view.page().runJavaScript(js)

    def _on_draw_smiles_updated(self, smiles: str) -> None:
        self._draw_smiles = smiles

    def _on_preview_clicked(self) -> None:
        smiles = self._smiles_input.text().strip()
        self._update_smiles_preview(smiles)

    def _update_smiles_preview(self, smiles: str) -> bool:
        if not smiles:
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText("Enter SMILES to preview")
            self._smiles_status.setText("")
            return True

        try:
            from chemistry.structure_renderer import render_smiles_to_png  # noqa: PLC0415

            png_bytes = render_smiles_to_png(smiles, (300, 300))
        except Exception:  # noqa: BLE001
            png_bytes = None
            self._smiles_status.setText("RDKit not installed")
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText("Enter SMILES to preview")
            return False

        if png_bytes is None:
            self._smiles_status.setText("Invalid SMILES")
            self._smiles_preview.setPixmap(QPixmap())
            self._smiles_preview.setText("Enter SMILES to preview")
            return False
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
            return True

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
            # If the structure was not modified and JSME gave us nothing back
            # (e.g. editor failed to load), keep the stored layout instead of
            # silently wiping it.
            if not self._canvas_mol_block and self._draw_smiles == self._initial_smiles:
                self._canvas_mol_block = self._initial_mol_block
        else:
            candidate = self._smiles_input.text().strip()
            # The text may have changed since Preview was last clicked. Validate
            # the exact value that would be committed; an empty value remains a
            # valid request to clear the current structure.
            if not self._update_smiles_preview(candidate):
                self._tabs.setCurrentIndex(1)
                return
            self._accepted_smiles = candidate
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
