"""dmgbuild configuration for IR Spectra Analyzer.

Used by the CI step:
    dmgbuild -s packaging/dmg_settings.py "IR Spectra Analyzer" <output.dmg>

Produces a drag-to-Applications DMG: the .app on the left, an Applications
symlink on the right, a clean background, and a 128-px icon size.
"""

from __future__ import annotations

from pathlib import Path

# dmgbuild injects 'defines' for -D KEY=VALUE substitutions. We use the
# injected 'app' and 'arch' keys if present, with sensible defaults.
_defines = defines  # noqa: F821 — injected by dmgbuild at runtime
_version = _defines.get("version", "0.0.0")
_arch = _defines.get("arch", "arm64")

# dmgbuild exec()s this file, so __file__ is not available; use cwd (repo root).
_root = Path.cwd()
_app_src = _root / "dist" / "IR Spectra Analyzer.app"

# ── dmgbuild settings ──────────────────────────────────────────────────────

application = str(_app_src)
appname = "IR Spectra Analyzer"

# Output DMG attributes
format = "UDBZ"  # bzip2 compressed — good size/speed tradeoff
size = "500M"

# Items placed inside the DMG
files = [str(_app_src)]
symlinks = {"Applications": "/Applications"}

# Icon displayed for the DMG itself in Finder
icon = str(_root / "assets" / "icon.icns")

# No custom background — clean white (easiest, no extra asset needed)
background = None

# Window geometry (origin-x, origin-y, width, height)
window_rect = ((200, 120), (540, 360))
icon_size = 128
text_size = 14

# Item positions inside the window
icon_locations = {
    "IR Spectra Analyzer.app": (150, 170),
    "Applications": (390, 170),
}
