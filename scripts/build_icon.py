"""Generate the IR Spectra Analyzer app icon.

Renders the Outlined %T IR Monogram logo — a glowing hollow geometric "IR"
monogram transitioning seamlessly from the top of the "R" into downward
transmittance (%T) infrared absorption peaks, colored with an infrared
coral-to-cyan gradient on a deep midnight-obsidian squircle.

Outputs produced in ``assets/``:

  - assets/icon.png        — 1024×1024 master PNG (RGBA, transparent corners)
  - assets/icon.ico        — Windows multi-resolution icon (16–256 px)
  - assets/icon.iconset/   — macOS iconset directory (named per Apple spec)
  - assets/icon.icns       — macOS icon (via ``iconutil`` on macOS, or built
                             with a pure-Python PNG-container fallback on other
                             platforms so the committed bundle stays in sync)

Run from the project root:

    python scripts/build_icon.py
"""

from __future__ import annotations

import io
import math
import struct
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"

# Horizontal base gradient: coral-red (I) -> sky blue (R) -> cyan-teal (%T peaks).
# Keeping coral->magenta->blue avoids muddy beige/grey midtones; a dedicated
# warm amber highlight is blended onto the upper-left bar of the "R".
_GRADIENT_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0.00, (255, 86, 98)),
    (0.16, (255, 96, 96)),
    (0.28, (186, 118, 224)),
    (0.42, (28, 166, 250)),
    (0.66, (30, 212, 206)),
    (1.00, (44, 228, 220)),
]


def _lerp_color(
    c1: tuple[int, int, int], c2: tuple[int, int, int], t: float
) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(round(c1[0] + (c2[0] - c1[0]) * t)),
        int(round(c1[1] + (c2[1] - c1[1]) * t)),
        int(round(c1[2] + (c2[2] - c1[2]) * t)),
    )


def _sample_gradient(t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    for i in range(len(_GRADIENT_STOPS) - 1):
        t0, c0 = _GRADIENT_STOPS[i]
        t1, c1 = _GRADIENT_STOPS[i + 1]
        if t <= t1:
            local_t = (t - t0) / max(t1 - t0, 1e-9)
            return _lerp_color(c0, c1, local_t)
    return _GRADIENT_STOPS[-1][1]


def _cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 48,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        mt = 1.0 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _stroke_polyline(
    draw: ImageDraw.ImageDraw,
    pts: list[tuple[float, float]],
    width: float,
    fill: int = 255,
    closed: bool = False,
) -> None:
    """Draw a smooth constant-width stroke along ``pts`` with rounded joins."""
    if len(pts) < 2:
        return
    r = width / 2.0
    seq = [*pts, pts[0]] if closed else pts
    for i in range(len(seq) - 1):
        x0, y0 = seq[i]
        x1, y1 = seq[i + 1]
        dist = math.hypot(x1 - x0, y1 - y0)
        steps = max(1, int(math.ceil(dist / max(width * 0.12, 1.0))))
        for s in range(steps + 1):
            t = s / steps
            cx = x0 + (x1 - x0) * t
            cy = y0 + (y1 - y0) * t
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)


def _rounded_squircle_bg(size: int, radius_ratio: float = 0.225) -> Image.Image:
    """Deep midnight-obsidian rounded square with subtle glass rim and ambient glow."""
    small = 256
    grad_small = Image.new("RGBA", (small, small))
    px = grad_small.load()
    assert px is not None
    tl = (26, 35, 58)
    mid = (14, 21, 41)
    br = (7, 11, 22)
    for y in range(small):
        ny = y / (small - 1)
        for x in range(small):
            nx = x / (small - 1)
            t = 0.45 * nx + 0.55 * ny
            if t < 0.45:
                c = _lerp_color(tl, mid, t / 0.45)
            else:
                c = _lerp_color(mid, br, (t - 0.45) / 0.55)
            dx = nx - 0.5
            dy = ny - 0.5
            dist2 = dx * dx + dy * dy
            if dist2 < 0.24:
                boost = (1.0 - dist2 / 0.24) * 9.0
                c = (
                    min(255, int(c[0] + boost * 0.4)),
                    min(255, int(c[1] + boost * 0.7)),
                    min(255, int(c[2] + boost * 1.4)),
                )
            px[x, y] = (*c, 255)
    gradient = grad_small.resize((size, size), Image.BICUBIC)

    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    radius = int(size * radius_ratio)
    mdraw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)

    base = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base.paste(gradient, (0, 0), mask)

    # Subtle directional glass rim highlight (brighter on top, darker below)
    rim_mask = Image.new("L", (size, size), 0)
    rdraw = ImageDraw.Draw(rim_mask)
    rim_w = max(int(size * 0.009), 2)
    inset = max(int(size * 0.005), 1)
    rdraw.rounded_rectangle(
        (inset, inset, size - 1 - inset, size - 1 - inset),
        radius=max(1, radius - inset),
        outline=255,
        width=rim_w,
    )
    rim_grad = Image.new("RGBA", (size, size))
    rg_small = Image.new("RGBA", (4, 256))
    rg_px = rg_small.load()
    assert rg_px is not None
    for y in range(256):
        alpha = int(84 - 48 * (y / 255.0))
        col = _lerp_color((148, 168, 214), (72, 86, 128), y / 255.0)
        for x in range(4):
            rg_px[x, y] = (*col, alpha)
    rim_grad = rg_small.resize((size, size), Image.BICUBIC)
    rim_alpha = ImageChops.multiply(rim_mask, mask)
    rim_grad.putalpha(ImageChops.multiply(rim_grad.split()[3], rim_alpha))
    base.alpha_composite(rim_grad)
    return base


def _build_emblem_mask(size: int) -> Image.Image:
    """Build crisp white-on-black mask of the outlined 'IR' + downward %T peaks."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    stroke = size * 0.0175
    top_y = size * 0.312
    bot_y = size * 0.688

    # 1. Letter "I" — hollow rounded vertical bar
    i_pts = [
        (size * 0.184, top_y),
        (size * 0.252, top_y),
        (size * 0.252, bot_y),
        (size * 0.184, bot_y),
    ]
    _stroke_polyline(draw, i_pts, stroke, closed=True)

    # 2. Letter "R" — outer contour
    r_stem_l = size * 0.304
    r_stem_r = size * 0.372
    bowl_mid_y = size * 0.542

    r_outer: list[tuple[float, float]] = [
        (r_stem_l, bot_y),
        (r_stem_l, top_y),
        (size * 0.438, top_y),
    ]
    r_outer.extend(
        _cubic_bezier(
            (size * 0.438, top_y),
            (size * 0.542, top_y),
            (size * 0.548, size * 0.418),
            (size * 0.548, size * 0.422),
            steps=32,
        )
    )
    r_outer.extend(
        _cubic_bezier(
            (size * 0.548, size * 0.422),
            (size * 0.548, size * 0.475),
            (size * 0.514, size * 0.528),
            (size * 0.452, bowl_mid_y),
            steps=32,
        )
    )
    r_outer.extend(
        [
            (size * 0.558, bot_y),
            (size * 0.480, bot_y),
            (size * 0.388, bowl_mid_y + size * 0.008),
            (r_stem_r, bowl_mid_y + size * 0.008),
            (r_stem_r, bot_y),
        ]
    )
    _stroke_polyline(draw, r_outer, stroke, closed=True)

    # Inner "D" counter of R
    c_left = r_stem_r
    c_top = size * 0.368
    c_bot = size * 0.484
    r_inner: list[tuple[float, float]] = [
        (c_left, c_bot),
        (c_left, c_top),
        (size * 0.424, c_top),
    ]
    r_inner.extend(
        _cubic_bezier(
            (size * 0.424, c_top),
            (size * 0.484, c_top),
            (size * 0.484, c_bot),
            (size * 0.424, c_bot),
            steps=36,
        )
    )
    _stroke_polyline(draw, r_inner, stroke, closed=True)

    # 3. Seamless %T downward absorption spectrum continuing from top of "R"
    spec_pts: list[tuple[float, float]] = [(size * 0.438, top_y), (size * 0.542, top_y)]
    spec_pts.extend(
        _cubic_bezier(
            (size * 0.542, top_y),
            (size * 0.574, top_y),
            (size * 0.584, size * 0.485),
            (size * 0.600, size * 0.530),
            steps=28,
        )
    )
    spec_pts.extend(
        _cubic_bezier(
            (size * 0.600, size * 0.530),
            (size * 0.614, size * 0.455),
            (size * 0.624, size * 0.372),
            (size * 0.636, size * 0.372),
            steps=24,
        )
    )
    spec_pts.extend(
        _cubic_bezier(
            (size * 0.636, size * 0.372),
            (size * 0.650, size * 0.372),
            (size * 0.662, bot_y),
            (size * 0.674, bot_y),
            steps=36,
        )
    )
    spec_pts.extend(
        _cubic_bezier(
            (size * 0.674, bot_y),
            (size * 0.686, bot_y),
            (size * 0.698, size * 0.360),
            (size * 0.712, size * 0.360),
            steps=36,
        )
    )
    spec_pts.extend(
        _cubic_bezier(
            (size * 0.712, size * 0.360),
            (size * 0.724, size * 0.360),
            (size * 0.734, size * 0.545),
            (size * 0.746, size * 0.545),
            steps=28,
        )
    )
    spec_pts.extend(
        _cubic_bezier(
            (size * 0.746, size * 0.545),
            (size * 0.762, size * 0.545),
            (size * 0.772, top_y),
            (size * 0.804, top_y),
            steps=32,
        )
    )
    spec_pts.append((size * 0.822, top_y))
    _stroke_polyline(draw, spec_pts, stroke, closed=False)

    return mask


def _colorize_gradient(size: int) -> Image.Image:
    """Create the IR coral -> sky blue -> cyan gradient with warm amber on upper R."""
    small = 256
    grad_small = Image.new("RGB", (small, small))
    px = grad_small.load()
    assert px is not None
    x_min, x_max = 0.180, 0.822
    amber = (255, 148, 44)
    for y in range(small):
        ny = y / (small - 1)
        for x in range(small):
            fx = x / (small - 1)
            nx = (fx - x_min) / (x_max - x_min)
            base_c = _sample_gradient(nx)

            # Warm amber-orange radial highlight on the upper-left bar of "R"
            dx = (fx - 0.365) / 0.145
            dy = (ny - 0.315) / 0.135
            dist2 = dx * dx + dy * dy
            if dist2 < 1.0:
                weight = 0.92 * (1.0 - dist2) ** 1.6
                base_c = _lerp_color(base_c, amber, weight)

            px[x, y] = base_c
    return grad_small.resize((size, size), Image.BICUBIC)


def _draw_emblem(canvas: Image.Image) -> None:
    """Composite soft neon glow layers + crisp gradient emblem onto ``canvas``."""
    size = canvas.width
    emblem_mask = _build_emblem_mask(size)
    color_map = _colorize_gradient(size)

    def _layer_from_mask(m: Image.Image, alpha_scale: float) -> Image.Image:
        layer = color_map.convert("RGBA")
        if alpha_scale < 1.0:
            m = m.point(lambda v: int(v * alpha_scale))
        layer.putalpha(m)
        return layer

    # Outer ambient neon bloom
    glow_wide = emblem_mask.filter(ImageFilter.GaussianBlur(radius=size * 0.024))
    glow_tight = emblem_mask.filter(ImageFilter.GaussianBlur(radius=size * 0.008))

    canvas.alpha_composite(_layer_from_mask(glow_wide, 0.42))
    canvas.alpha_composite(_layer_from_mask(glow_tight, 0.55))
    canvas.alpha_composite(_layer_from_mask(emblem_mask, 1.0))

    # Subtle bright inner highlight along stroke center for crispness at small sizes
    core_mask = emblem_mask.filter(ImageFilter.MinFilter(size=max(3, int(size * 0.005) | 1)))
    core_soft = core_mask.filter(ImageFilter.GaussianBlur(radius=size * 0.0015))
    white_core = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    white_core.putalpha(core_soft.point(lambda v: int(v * 0.22)))
    canvas.alpha_composite(white_core)


def build_master(size: int = 1024) -> Image.Image:
    """Render the master icon at the supplied (large) size."""
    ss = 2  # supersample 2x then downscale with LANCZOS for crisp anti-aliased lines
    large = size * ss
    canvas = _rounded_squircle_bg(large)
    _draw_emblem(canvas)
    return canvas.resize((size, size), Image.LANCZOS)


def _write_icns_fallback(iconset_dir: Path, icns_path: Path) -> None:
    """Pack PNG iconset entries into an Apple .icns container without iconutil."""
    # Standard Apple ICNS PNG chunk types mapped to iconset filenames
    chunk_specs = [
        (b"ic11", "icon_16x16@2x.png"),  # 32x32
        (b"ic12", "icon_32x32@2x.png"),  # 64x64
        (b"ic07", "icon_128x128.png"),  # 128x128
        (b"ic13", "icon_128x128@2x.png"),  # 256x256
        (b"ic08", "icon_256x256.png"),  # 256x256
        (b"ic14", "icon_256x256@2x.png"),  # 512x512
        (b"ic09", "icon_512x512.png"),  # 512x512
        (b"ic10", "icon_512x512@2x.png"),  # 1024x1024
    ]
    buf = io.BytesIO()
    for tag, fname in chunk_specs:
        png_bytes = (iconset_dir / fname).read_bytes()
        buf.write(tag)
        buf.write(struct.pack(">I", 8 + len(png_bytes)))
        buf.write(png_bytes)
    payload = buf.getvalue()
    with icns_path.open("wb") as f:
        f.write(b"icns")
        f.write(struct.pack(">I", 8 + len(payload)))
        f.write(payload)


def export_icns(master: Image.Image) -> None:
    """Build assets/icon.iconset/ + assets/icon.icns."""
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
            return
        print(f"iconutil failed ({result.stderr.strip()}), using fallback packer.")

    _write_icns_fallback(iconset_dir, icns_path)
    print(f"Wrote {icns_path} (PNG-packed ICNS)")


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
