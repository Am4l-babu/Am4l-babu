#!/usr/bin/env python3
"""
dotify.py - turn a photo into a dot-matrix / halftone portrait as an SVG.

    python scripts/dotify.py assets/photo.jpg -o assets/portrait --color \
        --cols 100 --equalize --detail 0.5

Why an SVG and not the JPG itself: a photo on a profile README reads as a
profile picture. A dot grid reads as a graphic. It also stays sharp at any
width and weighs a fraction of the source.

Output
------
  --color      one theme-neutral <out>.svg (dots take the photo's own colours,
               so a light and a dark render would be byte-identical)
  otherwise    <out>-dark.svg and <out>-light.svg, for <picture> +
               prefers-color-scheme in the README
  ascii /
  braille      <out>.txt, to paste inside a fenced code block

Requires Pillow:  python -m pip install Pillow
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required:  python -m pip install Pillow")


# --------------------------------------------------------------------------- #
# palette
# --------------------------------------------------------------------------- #

# (bright, dim) per theme. Cyan to match the portfolio at itzmeaml.in.
THEMES = {
    "dark":  ("#00f0ff", "#0e4f5c"),
    "light": ("#0e7490", "#a5f3fc"),
}

ASCII_RAMP = "@%#*+=-:. "          # dark -> light
BRAILLE_BASE = 0x2800
BRAILLE_BITS = [[0x01, 0x08], [0x02, 0x10], [0x04, 0x20], [0x40, 0x80]]


# --------------------------------------------------------------------------- #
# image prep
# --------------------------------------------------------------------------- #

def square_crop(img, fx: float, fy: float):
    """Crop to 1:1 around a focus point given in 0..1 image coordinates.

    The window is clamped to the image, so a focus near an edge just slides
    flush against it instead of producing a band of nothing.
    """
    w, h = img.size
    side = min(w, h)
    left = min(max(fx * w - side / 2, 0), w - side)
    top = min(max(fy * h - side / 2, 0), h - side)
    return img.crop((round(left), round(top), round(left) + side, round(top) + side))


def load_grid(path, cols: int, contrast: float, gamma: float,
              cell_aspect: float, square: bool, focus: tuple[float, float],
              equalize: bool, detail: float):
    """Return (cols, rows, lum[y][x] in 0..1, rgb[y][x]).

    `path` is a file to open, or an already-loaded PIL image - looks.py passes
    images it has already treated rather than round-tripping them through disk.
    """
    img = (path.copy() if isinstance(path, Image.Image)
           else ImageOps.exif_transpose(Image.open(path)))

    # An alpha channel is treated as a subject cutout: flatten onto black but
    # keep the mask, so nothing is drawn outside the subject and --equalize
    # measures the subject's histogram rather than a huge empty background.
    mask = None
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        if img.split()[3].getextrema()[0] < 250:
            mask = img.split()[3]
        flat = Image.new("RGBA", img.size, (0, 0, 0, 255))
        flat.alpha_composite(img)
        img = flat
    img = img.convert("RGB")

    if square:
        img = square_crop(img, *focus)
        if mask is not None:
            mask = square_crop(mask, *focus)

    gray = img.convert("L")

    # A face lit by hard sun against dark hair spans a far wider range than the
    # ~10 tones a dot ramp can show. Equalising buys the shadow detail back;
    # the unsharp pass puts local facial structure on top of the flattened
    # result, which otherwise looks like a silhouette.
    if equalize:
        binmask = mask.point(lambda v: 255 if v > 127 else 0) if mask else None
        gray = ImageOps.equalize(gray, mask=binmask)
    if detail > 0:
        radius = max(2, round(min(img.size) / 52))
        gray = gray.filter(ImageFilter.UnsharpMask(
            radius=radius, percent=round(detail * 100), threshold=0))
    if contrast != 1.0:
        gray = ImageEnhance.Contrast(gray).enhance(contrast)
        img = ImageEnhance.Contrast(img).enhance(contrast)

    w, h = img.size
    # cell_aspect is cell width / cell height: 1.0 for square dot cells,
    # ~0.5 for monospace glyphs, which are about twice as tall as they are wide
    rows = max(1, round(cols * (h / w) * cell_aspect))

    small_g = gray.resize((cols, rows), Image.Resampling.LANCZOS)
    if mask is not None:
        small_g = ImageChops.multiply(
            small_g, mask.resize((cols, rows), Image.Resampling.LANCZOS))
    small_c = img.resize((cols, rows), Image.Resampling.LANCZOS)

    gp, cp = small_g.load(), small_c.load()
    lum, rgb = [], []
    for y in range(rows):
        lum_row, rgb_row = [], []
        for x in range(cols):
            rgb_row.append(cp[x, y])
            lum_row.append(min(1.0, max(0.0, (gp[x, y] / 255.0) ** gamma)))
        lum.append(lum_row)
        rgb.append(rgb_row)
    return cols, rows, lum, rgb


def circle_falloff(x, y, cols, rows, feather=0.06):
    """1 inside the inscribed circle, fading to 0 just outside it."""
    nx = (x + 0.5) / cols * 2 - 1
    ny = (y + 0.5) / rows * 2 - 1
    d = math.hypot(nx, ny)
    if d <= 1 - feather:
        return 1.0
    if d >= 1 + feather:
        return 0.0
    return (1 + feather - d) / (2 * feather)


# --------------------------------------------------------------------------- #
# svg
# --------------------------------------------------------------------------- #

def svg_open(w, h, rows, o):
    css = []
    if o.animate:
        css.append("@keyframes dp{0%,100%{opacity:.5}50%{opacity:1}}")
        css.append(f".d{{animation:dp {o.duration}s ease-in-out infinite}}")
        css += [f".l{i}{{animation-delay:{i / o.lanes * o.duration:.2f}s}}"
                for i in range(o.lanes)]
    if o.reveal:
        # The fade goes on a <g> wrapping each row rather than on the dots:
        # group opacity MULTIPLIES with the children's own, so binary mode
        # keeps its per-glyph tone, and it is one class per row not per dot.
        step = o.reveal_time / max(rows - 1, 1)
        css.append("@keyframes rv{from{opacity:0}to{opacity:1}}")
        css.append(f".rw{{animation:rv {o.reveal_fade}s ease-out both}}")
        css += [f".r{y}{{animation-delay:"
                f"{(rows - 1 - y if o.reveal_dir == 'up' else y) * step:.3f}s}}"
                for y in range(rows)]

    style = f"<style>{''.join(css)}</style>" if css else ""
    bg = f'<rect width="100%" height="100%" fill="{o.bg}"/>' if o.bg else ""
    p = o.pad
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {w + 2 * p} {h + 2 * p}" '
            f'width="{w + 2 * p}" height="{h + 2 * p}" role="img" '
            f'aria-label="dot-matrix portrait">{style}{bg}'
            f'<g transform="translate({p},{p})">')


def _value(x, y, lum, cols, rows, o):
    v = lum[y][x]
    if o.invert:
        v = 1 - v
    if o.circle:
        v *= circle_falloff(x, y, cols, rows)
    return v


def build_dots(cols, rows, lum, rgb, theme, o):
    fg, dim = THEMES[theme]
    cell, max_r = o.cell, o.cell * 0.5 * o.dot_scale
    out = []
    for y in range(rows):
        row = []
        for x in range(cols):
            v = _value(x, y, lum, cols, rows, o)
            if v < o.floor:
                continue
            r = max_r * (v ** 0.85)
            if r < 0.18:                       # invisible at render size
                continue
            if o.color:
                cr, cg, cb = rgb[y][x]
                fill = f"#{cr:02x}{cg:02x}{cb:02x}"
            else:
                fill = fg if v > 0.42 else dim
            cls = f' class="d l{x % o.lanes}"' if o.animate else ""
            row.append(f'<circle cx="{x * cell + cell / 2:.1f}" '
                       f'cy="{y * cell + cell / 2:.1f}" r="{r:.2f}" '
                       f'fill="{fill}"{cls}/>')
        if not row:
            continue
        out.append(f'<g class="rw r{y}">{"".join(row)}</g>' if o.reveal
                   else "".join(row))
    return "".join(out), cols * cell, rows * cell


def build_binary(cols, rows, lum, rgb, theme, o):
    fg, dim = THEMES[theme]
    cell = o.cell
    out = [f'<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" '
           f'font-size="{cell * 0.92:.2f}" text-anchor="middle">']
    for y in range(rows):
        row = []
        for x in range(cols):
            v = _value(x, y, lum, cols, rows, o)
            if v < o.floor:
                continue
            # deterministic-but-scattered bit, seeded by position and value
            bit = "1" if ((x * 7 + y * 13 + int(v * 37)) % 3) else "0"
            if v > 0.62:
                bit = "1"
            if o.color:
                cr, cg, cb = rgb[y][x]
                fill = f"#{cr:02x}{cg:02x}{cb:02x}"
            else:
                fill = fg if v > 0.42 else dim
            cls = f' class="d l{x % o.lanes}"' if o.animate else ""
            row.append(f'<text x="{x * cell + cell / 2:.1f}" '
                       f'y="{y * cell + cell * 0.82:.1f}" fill="{fill}" '
                       f'opacity="{0.25 + 0.75 * v:.2f}"{cls}>{bit}</text>')
        if not row:
            continue
        out.append(f'<g class="rw r{y}">{"".join(row)}</g>' if o.reveal
                   else "".join(row))
    out.append("</g>")
    return "".join(out), cols * cell, rows * cell


def build_ascii(cols, rows, lum, o):
    n = len(ASCII_RAMP) - 1
    lines = []
    for y in range(rows):
        lines.append("".join(
            ASCII_RAMP[n - min(n, int(_value(x, y, lum, cols, rows, o) * n + 0.5))]
            for x in range(cols)).rstrip())
    return "\n".join(lines)


def build_braille(cols, rows, lum, o):
    lines = []
    for by in range(0, rows - 3, 4):
        row = []
        for bx in range(0, cols - 1, 2):
            bits = 0
            for dy in range(4):
                for dx in range(2):
                    if _value(bx + dx, by + dy, lum, cols, rows, o) > o.threshold:
                        bits |= BRAILLE_BITS[dy][dx]
            row.append(chr(BRAILLE_BASE + bits))
        lines.append("".join(row).rstrip())
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=Path, help="source photo (jpg/png/webp)")
    p.add_argument("-o", "--out", type=Path, default=Path("assets/portrait"),
                   help="output path WITHOUT extension")
    p.add_argument("--mode", choices=("dots", "binary", "ascii", "braille"),
                   default="dots")
    p.add_argument("--cols", type=int, default=88, help="dots across")
    p.add_argument("--cell", type=float, default=10.0, help="SVG units per cell")
    p.add_argument("--dot-scale", type=float, default=0.92,
                   help="max dot diameter as a fraction of the cell")
    p.add_argument("--gamma", type=float, default=1.0,
                   help="<1 brightens midtones, >1 darkens them")
    p.add_argument("--contrast", type=float, default=1.25)
    p.add_argument("--equalize", action="store_true",
                   help="equalise against the subject's own histogram - the fix "
                        "for a sunlit face against dark hair losing all detail")
    p.add_argument("--detail", type=float, default=0.0, metavar="N",
                   help="local-contrast boost 0-1.5; puts facial structure back "
                        "after --equalize flattens it. 0.5 is a good start")
    p.add_argument("--floor", type=float, default=0.06,
                   help="drop cells dimmer than this (keeps the file small)")
    p.add_argument("--threshold", type=float, default=0.45,
                   help="on/off cutoff for braille mode")
    p.add_argument("--cell-aspect", type=float, default=1.0,
                   help="cell width/height; 0.5 for ascii")
    p.add_argument("--square", action="store_true", help="crop to 1:1 first")
    p.add_argument("--focus", default="0.5,0.5", metavar="X,Y",
                   help="focus point for --square as fractions of width,height "
                        "(e.g. 0.55,0.30 for a face high and right of centre)")
    p.add_argument("--invert", action="store_true",
                   help="big dots on DARK areas instead of light ones")
    p.add_argument("--circle", action="store_true", help="mask to a circle")
    p.add_argument("--color", action="store_true",
                   help="tint each dot with the source pixel colour")
    p.add_argument("--animate", action="store_true",
                   help="slow shimmer sweeping across the columns")
    p.add_argument("--lanes", type=int, default=14, help="shimmer stagger groups")
    p.add_argument("--duration", type=float, default=4.0, help="shimmer seconds")
    p.add_argument("--reveal", action="store_true",
                   help="draw in row by row on load, like a slow scan")
    p.add_argument("--reveal-time", type=float, default=2.5, metavar="SEC")
    p.add_argument("--reveal-fade", type=float, default=0.45, metavar="SEC")
    p.add_argument("--reveal-dir", choices=("down", "up"), default="down")
    p.add_argument("--pad", type=float, default=8.0)
    p.add_argument("--bg", default="", help="optional background colour")
    a = p.parse_args(argv)

    if a.mode == "ascii" and a.cell_aspect == 1.0:
        a.cell_aspect = 0.5

    if not a.image.exists():
        sys.exit(f"no such image: {a.image}")
    try:
        fx, fy = (float(v) for v in a.focus.split(","))
    except ValueError:
        sys.exit(f"--focus wants two numbers like 0.55,0.30 (got {a.focus!r})")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    cols, rows, lum, rgb = load_grid(a.image, a.cols, a.contrast, a.gamma,
                                     a.cell_aspect, a.square, (fx, fy),
                                     a.equalize, a.detail)

    if a.mode in ("ascii", "braille"):
        text = (build_ascii if a.mode == "ascii" else build_braille)(
            cols, rows, lum, a)
        dest = a.out.with_suffix(".txt")
        dest.write_text(text, encoding="utf-8")
        print(f"wrote {dest}  ({cols}x{rows} cells)")
        return

    builder = build_dots if a.mode == "dots" else build_binary
    for theme in (("dark",) if a.color else ("dark", "light")):
        body, w, h = builder(cols, rows, lum, rgb, theme, a)
        svg = svg_open(w, h, rows, a) + body + "</g></svg>"
        stem = a.out.name if a.color else f"{a.out.name}-{theme}"
        dest = a.out.with_name(f"{stem}.svg")
        dest.write_text(svg, encoding="utf-8")
        print(f"wrote {dest}  ({len(svg) / 1024:.0f} KB, {cols}x{rows} cells)")


if __name__ == "__main__":
    main()
