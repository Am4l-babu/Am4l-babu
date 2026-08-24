#!/usr/bin/env python3
"""
looks.py - render the photo as every combination of treatment x backdrop.

    python scripts/looks.py                          # the whole matrix
    python scripts/looks.py --only photo,duotone     # some treatments
    python scripts/looks.py --backdrops card-dark,circle

Two independent axes:

  TREATMENT - what happens to the pixels
    photo      untouched
    duotone    luminance mapped onto a navy -> cyan ramp
    dots       halftone grid, each dot the photo's own colour
    dots-mono  the same grid, every dot cyan

  BACKDROP - what is behind him
    sky        the original photograph, square corners
    sky-round  the original photograph, rounded corners
    bare       sky removed, transparent - floats on the reader's theme
    card-dark  sky removed, dark card with a cyan wash behind him
    card-light sky removed, pale card with a cyan wash behind him
    circle     head-and-shoulders crop in a disc with a cyan ring

Writes assets/options/<treatment>--<backdrop>.png at 2x the 300px the README
displays, plus two grid sheets (on a dark and a light page) to compare them.

Once you have picked one:

    copy assets\\options\\<name>.png assets\\portrait.png

then point the <img> at the top of README.md at assets/portrait.png.

Reads assets/photo.jpg and assets/photo-cut.png (from cutout.py).
Requires Pillow and numpy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
except ImportError as e:  # pragma: no cover
    sys.exit(f"missing dependency ({e}). python -m pip install Pillow numpy")

W = 600                       # 2x the 300px the README renders it at
CYAN = (0, 240, 255)
INK = (13, 17, 23)            # GitHub dark canvas
PAPER = (246, 248, 250)       # GitHub light canvas


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def fit(img: Image.Image, width: int = W) -> Image.Image:
    return img.resize((width, round(img.height * width / img.width)),
                      Image.Resampling.LANCZOS)


def rounded(img: Image.Image, radius: int) -> Image.Image:
    """Round the corners, keeping whatever alpha the image already carries."""
    img = img.convert("RGBA")
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, img.width - 1, img.height - 1],
                                        radius, fill=255)
    existing = img.getchannel("A")
    if existing.getextrema()[0] < 255:
        m = ImageChops.multiply(m, existing)
    img.putalpha(m)
    return img


def subject_bbox(cut: Image.Image) -> tuple[int, int, int, int]:
    """Tight box around the non-transparent pixels."""
    a = np.asarray(cut.getchannel("A"))
    ys, xs = np.where(a > 24)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def wash(size, centre, radius, colour, strength):
    """A soft radial glow, for putting light behind the subject."""
    g = Image.new("L", size, 0)
    cx, cy = centre
    ImageDraw.Draw(g).ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                              fill=int(255 * strength))
    return Image.new("RGB", size, colour), g.filter(
        ImageFilter.GaussianBlur(radius * 0.55))


# --------------------------------------------------------------------------- #
# treatments - RGBA in, RGBA out, alpha preserved
# --------------------------------------------------------------------------- #

def t_photo(src: Image.Image) -> Image.Image:
    return fit(src)


def t_duotone(src: Image.Image) -> Image.Image:
    """Map luminance onto a deep-navy -> cyan ramp, keeping the alpha."""
    src = fit(src)
    lum = ImageOps.autocontrast(src.convert("L"), cutoff=1)
    lo, hi = np.array([6, 18, 26], float), np.array([150, 240, 255], float)
    t = np.asarray(lum, float)[..., None] / 255.0
    rgb = (lo + (hi - lo) * t).round().astype(np.uint8)
    out = Image.fromarray(rgb, "RGB").convert("RGBA")
    out.putalpha(src.getchannel("A"))
    return out


def _halftone(src: Image.Image, cols: int = 100) -> Image.Image:
    """Shared by both dot treatments. Uses dotify's own image prep so the
    grid matches what dotify.py writes into the SVG."""
    sys.path.insert(0, str(Path(__file__).parent))
    import dotify

    # gamma 0.30 is load-bearing: he is in a near-black shirt, and dot radius
    # tracks brightness. At gamma 1.0 those dots shrink away and leave a
    # floating head above a bright mundu.
    c, r, lum, rgb = dotify.load_grid(src, cols, 1.1, 0.30, 1.0, False,
                                      (0.5, 0.5), True, 0.7)
    S = W / cols
    im = Image.new("RGBA", (round(c * S), round(r * S)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y in range(r):
        for x in range(c):
            v = lum[y][x]
            if v < 0.02:
                continue
            rad = S * 0.5 * (v ** 0.85)
            if rad < 0.2:
                continue
            cx, cy = x * S + S / 2, y * S + S / 2
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad],
                      fill=rgb[y][x] + (255,))
    return im


def t_dots(src: Image.Image) -> Image.Image:
    return _halftone(src)


def t_dots_mono(src: Image.Image) -> Image.Image:
    a = np.asarray(_halftone(src))
    lum = a[..., :3].max(axis=2, keepdims=True) / 255.0
    tint = (np.array(CYAN, float) * (0.35 + 0.65 * lum)).round().astype(np.uint8)
    return Image.fromarray(np.dstack([tint, a[..., 3]]), "RGBA")


TREATMENTS = {
    "photo": t_photo,
    "duotone": t_duotone,
    "dots": t_dots,
    "dots-mono": t_dots_mono,
}


# --------------------------------------------------------------------------- #
# backdrops - each says which source it wants, then composes
# --------------------------------------------------------------------------- #

def b_sky(treated, photo, cut):
    return treated.convert("RGBA")


def b_sky_round(treated, photo, cut):
    return rounded(treated, 28)


def b_bare(treated, photo, cut):
    return treated.convert("RGBA")


def _card(treated, bg, strength):
    inset = 30
    c = fit(treated, W - inset * 2)
    H = c.height + inset * 2 - 10
    card = Image.new("RGB", (W, H), bg)
    x0, y0, x1, y1 = subject_bbox(c)
    tint, mask = wash((W, H), ((x0 + x1) // 2 + inset, (y0 + y1) // 2 + inset),
                      int(c.width * 0.52), CYAN, strength)
    card.paste(tint, (0, 0), mask)
    card = card.convert("RGBA")
    card.alpha_composite(c, (inset, inset - 10))
    return rounded(card, 26)


def b_card_dark(treated, photo, cut):
    return _card(treated, INK, 0.42)


def b_card_light(treated, photo, cut):
    # A pale card needs a much gentler wash or the cyan turns to milk.
    return _card(treated, PAPER, 0.16)


def b_circle(treated, photo, cut):
    """Head-and-shoulders in a disc. The crop is measured on the cutout so it
    finds his actual head, but taken from the treated full frame so the disc
    is filled rather than showing sky-shaped holes."""
    x0, y0, x1, y1 = subject_bbox(cut)
    side = round((x1 - x0) * 1.12)
    cx = (x0 + x1) // 2
    cy = y0 + round(side * 0.46)                 # head sits high in the disc
    left = max(0, min(cx - side // 2, photo.width - side))
    top = max(0, min(cy - side // 2, photo.height - side))

    scale = treated.width / photo.width          # treated is already resized
    box = [round(v * scale) for v in
           (left, top, left + side, top + side)]
    crop = treated.convert("RGBA").crop(box).resize(
        (W, W), Image.Resampling.LANCZOS)

    ring = 7
    m = Image.new("L", (W, W), 0)
    ImageDraw.Draw(m).ellipse([ring, ring, W - ring - 1, W - ring - 1], fill=255)
    if (existing := crop.getchannel("A")).getextrema()[0] < 255:
        m = ImageChops.multiply(m, existing)
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    out.paste(crop, (0, 0), m)
    ImageDraw.Draw(out).ellipse(
        [ring // 2, ring // 2, W - ring // 2 - 1, W - ring // 2 - 1],
        outline=CYAN + (255,), width=ring)
    return out


# name -> (compose, which source the treatment runs on)
BACKDROPS = {
    "sky":        (b_sky,        "photo"),
    "sky-round":  (b_sky_round,  "photo"),
    "bare":       (b_bare,       "cut"),
    "card-dark":  (b_card_dark,  "cut"),
    "card-light": (b_card_light, "cut"),
    "circle":     (b_circle,     "photo"),
}


# --------------------------------------------------------------------------- #
# contact sheet
# --------------------------------------------------------------------------- #

def grid_sheet(cells, rows, cols, bg, out: Path, scale=0.30):
    """cells[(row, col)] -> image. Row and column headers down the side/top."""
    thumbs = {k: v.resize((round(v.width * scale), round(v.height * scale)),
                          Image.Resampling.LANCZOS) for k, v in cells.items()}
    cw = max(t.width for t in thumbs.values())
    ch = max(t.height for t in thumbs.values())
    gut, head, side = 16, 30, 96

    W_ = side + len(cols) * (cw + gut) + gut
    H_ = head + len(rows) * (ch + gut) + gut
    canvas = Image.new("RGBA", (W_, H_), bg + (255,))
    d = ImageDraw.Draw(canvas)
    fg = (205, 215, 225) if sum(bg) < 380 else (55, 65, 75)
    dim = (130, 145, 158)

    for j, col in enumerate(cols):
        x = side + j * (cw + gut) + cw // 2 - len(col) * 3
        d.text((x, head // 2 - 4), col, fill=fg)
    for i, row in enumerate(rows):
        y = head + i * (ch + gut) + ch // 2
        d.text((12, y), row, fill=fg)

    for i, row in enumerate(rows):
        for j, col in enumerate(cols):
            t = thumbs.get((row, col))
            if t is None:
                continue
            x = side + j * (cw + gut) + (cw - t.width) // 2
            y = head + i * (ch + gut) + (ch - t.height) // 2
            canvas.alpha_composite(t, (x, y))
            d.text((x, y + t.height + 2), f"{row}--{col}", fill=dim)

    canvas.convert("RGB").save(out)
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--photo", type=Path, default=Path("assets/photo.jpg"))
    p.add_argument("--cut", type=Path, default=Path("assets/photo-cut.png"))
    p.add_argument("--out", type=Path, default=Path("assets/options"))
    p.add_argument("--only", default="", help="comma-separated treatments")
    p.add_argument("--backdrops", default="", help="comma-separated backdrops")
    a = p.parse_args(argv)

    for f in (a.photo, a.cut):
        if not f.exists():
            sys.exit(f"missing {f} - run scripts/cutout.py first")

    photo = ImageOps.exif_transpose(Image.open(a.photo)).convert("RGBA")
    cut = Image.open(a.cut).convert("RGBA")
    sources = {"photo": photo, "cut": cut}

    treatments = [s.strip() for s in a.only.split(",") if s.strip()] or list(TREATMENTS)
    backdrops = [s.strip() for s in a.backdrops.split(",") if s.strip()] or list(BACKDROPS)
    for name, table in ((treatments, TREATMENTS), (backdrops, BACKDROPS)):
        bad = [n for n in name if n not in table]
        if bad:
            sys.exit(f"unknown: {', '.join(bad)}. Choose from: {', '.join(table)}")

    a.out.mkdir(parents=True, exist_ok=True)

    # Treat each source once - the halftone is the slow part and both the
    # sky and cut versions of it get reused across several backdrops.
    treated = {(t, s): TREATMENTS[t](sources[s])
               for t in treatments
               for s in {BACKDROPS[b][1] for b in backdrops}}

    cells, total = {}, 0
    for t in treatments:
        for b in backdrops:
            compose, want = BACKDROPS[b]
            img = compose(treated[(t, want)], photo, cut)
            dest = a.out / f"{t}--{b}.png"
            img.save(dest, optimize=True)
            cells[(t, b)] = img
            total += dest.stat().st_size
            print(f"wrote {dest}  ({img.width}x{img.height}, "
                  f"{dest.stat().st_size // 1024} KB)")

    print(f"\n{len(cells)} combinations, {total // 1024} KB total")
    print("wrote", grid_sheet(cells, treatments, backdrops, INK,
                              a.out / "_grid-dark.png"))
    print("wrote", grid_sheet(cells, treatments, backdrops, PAPER,
                              a.out / "_grid-light.png"))


if __name__ == "__main__":
    main()
