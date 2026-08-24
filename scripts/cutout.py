#!/usr/bin/env python3
"""
cutout.py - drop a plain sky/wall background out of a photo, writing RGBA PNG.

    python scripts/cutout.py assets/photo.jpg -o assets/photo-cut.png

Why this exists: dotify's --equalize measures the histogram of whatever it is
given. Hand it a photo that is two-thirds bright sky and the subject stays
crushed into a silhouette no matter what you set. Remove the sky first and the
same flags recover the face, because the histogram is then the subject's own.

The alpha channel also carries through to the SVG - no dots are drawn outside
the subject, so the portrait sits on the README background instead of inside a
blue rectangle.

How it works, in order:
  1. score every pixel for "blueness" (B above the larger of R and G)
  2. keep the blue regions that touch the image border - that is the sky, as
     opposed to anything blue the subject happens to be wearing
  3. grow that region into neighbouring pale low-saturation pixels, which is
     what clouds are, and what a blue-only test always misses
  4. fill holes, keep the largest remaining blob as the subject
  5. feather the edge so the dot grid does not end on a staircase

Requires Pillow, numpy and scipy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageOps
    from scipy import ndimage as ndi
except ImportError as e:  # pragma: no cover
    sys.exit(f"missing dependency ({e}). python -m pip install Pillow numpy scipy")


def blueness(rgb: np.ndarray) -> np.ndarray:
    """How much more blue a pixel is than its strongest other channel.

    Sky scores 40-90. Skin, black cloth and white cloth all score near zero or
    negative, which is the whole point - it separates on hue, not brightness.
    """
    r, g, b = (rgb[..., i].astype(np.int16) for i in range(3))
    return b - np.maximum(r, g)


def border_seeded(mask: np.ndarray, margin: int = 2) -> np.ndarray:
    """Keep only the components of `mask` that touch the image border.

    A blue T-shirt in the middle of the frame is blue but is not background.
    """
    lab, n = ndi.label(mask)
    if n == 0:
        return np.zeros_like(mask)
    edge = np.zeros_like(mask)
    edge[:margin, :] = edge[-margin:, :] = True
    edge[:, :margin] = edge[:, -margin:] = True
    keep = set(np.unique(lab[edge & mask])) - {0}
    return np.isin(lab, list(keep))


def grow_into_pale(bg: np.ndarray, rgb: np.ndarray, rounds: int,
                   min_value: int, max_sat: int) -> np.ndarray:
    """Dilate `bg` into adjacent pale, washed-out pixels - i.e. cloud.

    Restricted to pale pixels so the growth stops at the subject's edge rather
    than eating into it. Runs a fixed number of rounds instead of to
    convergence: a white mundu is also pale, and if the two ever touch, an
    unbounded flood would swallow it.
    """
    mx = rgb.max(axis=2).astype(np.int16)
    mn = rgb.min(axis=2).astype(np.int16)
    pale = (mx >= min_value) & ((mx - mn) <= max_sat)
    for _ in range(rounds):
        grown = ndi.binary_dilation(bg, structure=np.ones((3, 3), bool)) & pale
        if (grown == bg).all():
            break
        bg = grown | bg
    return bg


def largest_blob(mask: np.ndarray) -> np.ndarray:
    lab, n = ndi.label(mask)
    if n <= 1:
        return mask
    sizes = ndi.sum(mask, lab, range(1, n + 1))
    return lab == (int(np.argmax(sizes)) + 1)


def cut(path: Path, threshold: int, grow: int, feather: float,
        min_value: int, max_sat: int, keep_largest: bool):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    rgb = np.asarray(img)

    bg = border_seeded(blueness(rgb) > threshold)
    if not bg.any():
        sys.exit(f"nothing scored above --threshold {threshold} at the border. "
                 f"Is the background actually sky? Try a lower threshold, or "
                 f"skip the cutout and run dotify on the photo directly.")

    bg = grow_into_pale(bg, rgb, grow, min_value, max_sat)

    subject = ndi.binary_fill_holes(~bg)
    if keep_largest:
        subject = largest_blob(subject)

    # A hard alpha edge makes the outermost ring of dots pop to full size and
    # look like a cut-out sticker. Blurring the mask ramps them down instead.
    alpha = ndi.gaussian_filter(subject.astype(np.float32), feather) if feather > 0 \
        else subject.astype(np.float32)
    alpha = np.clip(alpha, 0, 1)

    # Blank the RGB under fully transparent pixels. It is invisible either way,
    # but a flat region compresses far better - on this photo it takes the PNG
    # from 810 KB to 455 KB, and the file is committed.
    a8 = (alpha * 255).round().astype(np.uint8)
    rgb = np.where(a8[..., None] == 0, 0, rgb).astype(np.uint8)

    out = np.dstack([rgb, a8])
    return Image.fromarray(out, "RGBA"), float(subject.mean())


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("image", type=Path)
    p.add_argument("-o", "--out", type=Path, default=Path("assets/photo-cut.png"))
    p.add_argument("--threshold", type=int, default=18,
                   help="blueness above which a pixel counts as sky (default 18); "
                        "raise it if the cutout eats the subject, lower it if "
                        "sky survives")
    p.add_argument("--grow", type=int, default=40,
                   help="dilation rounds into pale pixels, for cloud (default 40)")
    p.add_argument("--min-value", type=int, default=170,
                   help="how bright a pixel must be to count as cloud")
    p.add_argument("--max-sat", type=int, default=45,
                   help="how colourless a pixel must be to count as cloud")
    p.add_argument("--feather", type=float, default=1.4,
                   help="gaussian blur on the alpha edge, in pixels")
    p.add_argument("--no-largest", dest="keep_largest", action="store_false",
                   help="keep every subject blob, not just the biggest one")
    a = p.parse_args(argv)

    if not a.image.exists():
        sys.exit(f"no such image: {a.image}")

    img, frac = cut(a.image, a.threshold, a.grow, a.feather,
                    a.min_value, a.max_sat, a.keep_largest)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(a.out, optimize=True)
    print(f"wrote {a.out}  (subject is {frac * 100:.1f}% of the frame)")
    if frac > 0.75:
        print("  ! that is most of the frame - the sky probably was not removed",
              file=sys.stderr)
    elif frac < 0.08:
        print("  ! that is almost nothing - --threshold is probably too low",
              file=sys.stderr)


if __name__ == "__main__":
    main()
