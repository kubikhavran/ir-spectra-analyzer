"""Generate the IR Spectra Analyzer app icon.

Renders a minimalist IR-spectrum glyph (bold white trace with three absorption
peaks on a deep indigo rounded-square background) at 1024x1024, then downscales
with high-quality filtering to produce a multi-resolution Windows .ico file.

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


def export_all() -> None:
    """Write master PNG + multi-res .ico into assets/."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    master = build_master(1024)
    master_path = ASSETS_DIR / "icon.png"
    master.save(master_path, optimize=True)

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = ASSETS_DIR / "icon.ico"
    master.save(ico_path, format="ICO", sizes=ico_sizes)

    # macOS .icns is optional (for dev convenience on Mac, not used by Windows build)
    print(f"Wrote {master_path} ({master.size[0]}x{master.size[1]})")
    print(f"Wrote {ico_path} with sizes {ico_sizes}")


if __name__ == "__main__":
    export_all()
