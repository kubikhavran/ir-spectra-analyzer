"""Generate the IR Spectra Analyzer app icon.

Renders a minimalist IR-spectrum glyph (bold white trace with three absorption
peaks on a deep indigo rounded-square background) at 1024x1024, then downscales
with high-quality filtering to produce:

  - assets/icon.png        — 1024×1024 master PNG
  - assets/icon.ico        — Windows multi-resolution icon (16–256 px)
  - assets/icon.iconset/   — macOS iconset directory (named per Apple spec)
  - assets/icon.icns       — macOS icon (built from iconset via iconutil on macOS,
                             skipped silently on other platforms)

Run from the project root:

    python scripts/build_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"


def _rounded_rect_gradient(size: int, radius_ratio: float = 0.22) -> Image.Image:
    """Indigo rounded-square with a subtle top-to-bottom gradient."""
    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    gradient = Image.new("RGBA", (size, size))
    top = (30, 27, 75, 255)
    bottom = (49, 46, 129, 255)
    draw = ImageDraw.Draw(gradient)
    for y in range(size):
        t = y / max(size - 1, 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        draw.line([(0, y), (size, y)], fill=(r, g, b, 255))

    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    radius = int(size * radius_ratio)
    mdraw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    base.paste(gradient, (0, 0), mask)
    return base


def _spectrum_peak(x: float, center: float, width: float, height: float) -> float:
    """Gaussian-like peak contribution at position x."""
    import math

    return height * math.exp(-((x - center) ** 2) / (2 * width * width))


def _spectrum_curve_points(
    size: int, margin_x: float, baseline_y: float
) -> list[tuple[float, float]]:
    """Baseline with three absorption peaks — broad O-H, sharp C=O, medium fingerprint."""
    usable_w = size - 2 * margin_x
    peaks = [
        (0.25, 0.12, 0.55),  # broad left peak (O-H stretch region)
        (0.55, 0.035, 0.78),  # sharp tall peak (C=O stretch)
        (0.78, 0.06, 0.45),  # medium fingerprint peak
    ]
    pts: list[tuple[float, float]] = []
    n_samples = 400
    max_peak_px = size * 0.52
    for i in range(n_samples):
        t = i / (n_samples - 1)
        x = margin_x + t * usable_w
        total = 0.0
        for c, w, h in peaks:
            total += _spectrum_peak(t, c, w, h)
        y = baseline_y - total * max_peak_px
        pts.append((x, y))
    return pts


def _draw_spectrum(img: Image.Image) -> None:
    """Paint the white spectrum silhouette + subtle baseline.

    The trace is rendered as a filled polygon (closed from baseline along the
    curve back to baseline). This produces a crisp solid shape that scales
    down cleanly, unlike ImageDraw.line which leaves perpendicular artifacts
    when many tiny segments with rounded joints are rendered at high DPI.
    """
    size = img.width
    margin_x = size * 0.15
    baseline_y = size * 0.72

    pts = _spectrum_curve_points(size, margin_x, baseline_y)

    # Baseline first (sits under the silhouette)
    baseline_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    baseline_draw = ImageDraw.Draw(baseline_layer)
    baseline_stroke = max(int(size * 0.014), 2)
    baseline_color = (165, 180, 252, 230)
    baseline_draw.line(
        [(margin_x, baseline_y), (size - margin_x, baseline_y)],
        fill=baseline_color,
        width=baseline_stroke,
    )

    # Filled silhouette polygon: baseline → curve → baseline
    fill_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill_layer)
    polygon_pts = [(pts[0][0], baseline_y), *pts, (pts[-1][0], baseline_y)]
    fill_draw.polygon(polygon_pts, fill=(255, 255, 255, 255))

    # Subtle soft glow behind the silhouette for depth
    glow = fill_layer.filter(ImageFilter.GaussianBlur(radius=size * 0.018))
    glow_tinted = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_tinted.paste((199, 210, 254, 90), mask=glow.split()[3])

    img.alpha_composite(glow_tinted)
    img.alpha_composite(baseline_layer)
    img.alpha_composite(fill_layer)


def build_master(size: int = 1024) -> Image.Image:
    """Render the master icon at the supplied (large) size."""
    ss = 2  # supersample 2x then downscale for smooth curves
    large = size * ss
    canvas = _rounded_rect_gradient(large)
    _draw_spectrum(canvas)
    canvas = canvas.resize((size, size), Image.LANCZOS)
    return canvas


def export_icns(master: Image.Image) -> None:
    """Build assets/icon.iconset/ + assets/icon.icns.

    The iconset contains PNG files named per Apple's convention.  On macOS,
    ``iconutil -c icns`` converts the directory to a proper .icns file.
    On other platforms the iconutil call is silently skipped — the .iconset
    directory is still written and can be committed so CI can consume it.
    """
    import subprocess
    import sys

    # Apple iconset naming: icon_<logical>x<logical>[@2x].png
    # @2x entries are the same sizes at double pixel density.
    iconset_specs: list[tuple[str, int]] = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    iconset_dir = ASSETS_DIR / "icon.iconset"
    iconset_dir.mkdir(parents=True, exist_ok=True)
    for filename, px in iconset_specs:
        resized = master.resize((px, px), Image.LANCZOS)
        resized.save(iconset_dir / filename, format="PNG")
        print(f"  {filename} ({px}×{px})")

    icns_path = ASSETS_DIR / "icon.icns"
    if sys.platform == "darwin":
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"Wrote {icns_path} (via iconutil)")
        else:
            print(f"iconutil failed: {result.stderr.strip()}")
    else:
        print(f"Skipping .icns generation (not on macOS). Run on macOS to build {icns_path}.")


def export_all() -> None:
    """Write master PNG, .ico, .iconset, and .icns into assets/."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    master = build_master(1024)

    master_path = ASSETS_DIR / "icon.png"
    master.save(master_path, optimize=True)
    print(f"Wrote {master_path} ({master.size[0]}×{master.size[1]})")

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = ASSETS_DIR / "icon.ico"
    master.save(ico_path, format="ICO", sizes=ico_sizes)
    print(f"Wrote {ico_path}")

    print("Building macOS iconset:")
    export_icns(master)


if __name__ == "__main__":
    export_all()
