#!/usr/bin/env python3
"""
radar.py - draw a radar / spider chart as an SVG. Stdlib only.

Two sources:

    # hand-authored, from a JSON file you edit
    python scripts/radar.py --data assets/skills.json -o assets/radar

    # live, from real language byte counts across a user's public repos
    python scripts/radar.py --github Am4l-babu -o assets/radar-langs \
        --limit 7 --values --exclude "makefile,batchfile,cmake"

Writes <out>-dark.svg and <out>-light.svg so the README can swap them with
<picture> + prefers-color-scheme.

skills.json shape:
    {"title": "Skill Radar", "axes": [{"label": "Python", "value": 82}, ...]}
Values are 0-100. Five to eight axes reads best; past that the labels collide.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = {"User-Agent": "radar.py"}

THEMES = {
    "dark": {
        "grid": "#30363d", "axis": "#484f58", "label": "#c9d1d9",
        "value": "#8b949e", "title": "#00f0ff",
        "stroke": "#00f0ff", "fill": "#00f0ff", "fill_op": "0.18",
        "dot": "#00f0ff",
    },
    "light": {
        "grid": "#d0d7de", "axis": "#afb8c1", "label": "#1f2328",
        "value": "#57606a", "title": "#0e7490",
        "stroke": "#0e7490", "fill": "#0e7490", "fill_op": "0.16",
        "dot": "#0e7490",
    },
}

FONT = "ui-sans-serif,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


def esc(s: str) -> str:
    """XML-escape a label. "C/C++" is fine; "IoT & Protocols" is not."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


# The canvas is wider than it is tall and the web sits low in it, because the
# labels hang outside the outer ring and the longest of them ("IoT & Protocols",
# "Jupyter Notebook") run off the side of a square box long before they run off
# the bottom. Title sits in the headroom this leaves at the top.
W, H = 650, 500
CX, CY = W / 2, H / 2 + 13
R = 165             # radius of the outermost ring
RINGS = 4
LABEL_GAP = 24      # how far past the outer ring the labels sit

# The side gutters are sized for the worst case: a label on the near-horizontal
# axis, where the full label radius plus the whole string has to fit. At 13px
# semibold that is about 7.8 units a character, so 17 characters needs
# 189 + 133 = 322 either side of centre - hence the 650 width.
MAX_LABEL = 17


# --------------------------------------------------------------------------- #
# data sources
# --------------------------------------------------------------------------- #

def from_file(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    axes = [(a["label"], float(a["value"])) for a in data["axes"]]
    return data.get("title", "Skill Radar"), axes


def _get(url: str, token: str | None, tries: int = 3):
    """GET and parse JSON, retrying transient failures.

    The API drops the occasional connection mid-run, and one dropped socket
    forty repos into the language sweep should not lose the whole chart.
    HTTP errors are NOT retried - a 404 or a 403 rate-limit will not fix itself.
    """
    req = urllib.request.Request(url, headers=dict(UA))
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, OSError) as e:
            if attempt == tries:
                raise
            print(f"  . {type(e).__name__}, retry {attempt}/{tries - 1}",
                  file=sys.stderr)
            time.sleep(2 * attempt)


def from_github(user: str, limit: int, exclude: set[str], token: str | None):
    """Aggregate language bytes over the user's non-fork public repos.

    Scaled so the largest language sits at 100 - the chart is about relative
    weight, and an absolute byte count on a 0-100 axis means nothing.
    """
    totals: dict[str, int] = {}
    skipped = 0
    page = 1
    while page <= 4:                      # 400 repos is plenty
        repos = _get(f"https://api.github.com/users/{user}/repos"
                     f"?per_page=100&page={page}&type=owner", token)
        if not repos:
            break
        for repo in repos:
            if repo.get("fork") or repo.get("archived"):
                continue
            try:
                langs = _get(repo["languages_url"], token)
            except (urllib.error.HTTPError, OSError) as e:   # gone, or gave up
                print(f"  ! {repo['name']}: {e}", file=sys.stderr)
                skipped += 1
                continue
            for name, count in langs.items():
                if name.lower() in exclude:
                    continue
                totals[name] = totals.get(name, 0) + count
        if len(repos) < 100:
            break
        page += 1

    if not totals:
        sys.exit("no language data came back - is the username right?")
    if skipped:
        # Anonymous callers get 60 requests an hour and this needs one per repo,
        # so a partial chart here almost always means "set GITHUB_TOKEN".
        print(f"  ! {skipped} repo(s) skipped - this chart is INCOMPLETE. "
              f"Set GITHUB_TOKEN and rerun.", file=sys.stderr)

    top = sorted(totals.items(), key=lambda kv: -kv[1])[:limit]
    peak = top[0][1]
    return "Languages by bytes", [(n, 100.0 * c / peak) for n, c in top]


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #

def point(i: int, n: int, radius: float):
    """Vertex i of an n-gon, starting at 12 o'clock, going clockwise."""
    ang = -math.pi / 2 + 2 * math.pi * i / n
    return CX + radius * math.cos(ang), CY + radius * math.sin(ang)


def polygon(n: int, radius: float):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in
                    (point(i, n, radius) for i in range(n)))


def curved_path(pts, tension: float):
    """Closed Catmull-Rom through pts, emitted as cubic beziers.

    tension 0 gives straight segments (a plain polygon); ~0.4 rounds the
    corners enough to look drawn rather than plotted.
    """
    if tension <= 0:
        return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"
    n = len(pts)
    d = [f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(n):
        p0, p1 = pts[(i - 1) % n], pts[i]
        p2, p3 = pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) * tension / 3,
              p1[1] + (p2[1] - p0[1]) * tension / 3)
        c2 = (p2[0] - (p3[0] - p1[0]) * tension / 3,
              p2[1] - (p3[1] - p1[1]) * tension / 3)
        d.append(f"C{c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} "
                 f"{p2[0]:.1f} {p2[1]:.1f}")
    return "".join(d) + "Z"


def label_anchor(x: float):
    """Labels left of centre hang right-aligned, so nothing overlaps the web."""
    if x < CX - 12:
        return "end"
    if x > CX + 12:
        return "start"
    return "middle"


# --------------------------------------------------------------------------- #
# render
# --------------------------------------------------------------------------- #

def render(title: str, axes, theme: str, o) -> str:
    t = THEMES[theme]
    n = len(axes)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           f'width="{W}" height="{H}" role="img" '
           f'aria-label="{esc(title)}: ' +
           esc(", ".join(f"{lb} {v:.0f}" for lb, v in axes)) + '">']

    if o.animate:
        out.append('<style>@keyframes gr{from{transform:scale(.02)}'
                   'to{transform:scale(1)}}'
                   '.shape{transform-origin:center;animation:gr 1.1s '
                   'cubic-bezier(.2,.9,.3,1) both}</style>')

    if o.title:
        out.append(f'<text x="{CX}" y="26" text-anchor="middle" font-family="{FONT}" '
                   f'font-size="15" font-weight="600" fill="{t["title"]}">{esc(title)}</text>')

    # rings
    for ring in range(1, RINGS + 1):
        out.append(f'<polygon points="{polygon(n, R * ring / RINGS)}" fill="none" '
                   f'stroke="{t["grid"]}" stroke-width="1"/>')
    # spokes
    for i in range(n):
        x, y = point(i, n, R)
        out.append(f'<line x1="{CX}" y1="{CY}" x2="{x:.1f}" y2="{y:.1f}" '
                   f'stroke="{t["axis"]}" stroke-width="1"/>')

    # the shape itself
    pts = [point(i, n, R * max(0.0, min(100.0, v)) / 100) for i, (_, v) in enumerate(axes)]
    d = curved_path(pts, o.curve)
    cls = ' class="shape"' if o.animate else ""
    out.append(f'<g{cls}><path d="{d}" fill="{t["fill"]}" fill-opacity="{t["fill_op"]}" '
               f'stroke="{t["stroke"]}" stroke-width="2.5" stroke-linejoin="round"/>')
    for x, y in pts:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="{t["dot"]}"/>')
    out.append("</g>")

    # labels, pushed out past the outer ring
    for i, (label, v) in enumerate(axes):
        lx, ly = point(i, n, R + LABEL_GAP)
        anchor = label_anchor(lx)
        out.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                   f'dominant-baseline="middle" font-family="{FONT}" font-size="13" '
                   f'font-weight="600" fill="{t["label"]}">{esc(label)}</text>')
        if o.values:
            out.append(f'<text x="{lx:.1f}" y="{ly + 15:.1f}" text-anchor="{anchor}" '
                       f'dominant-baseline="middle" font-family="{MONO}" '
                       f'font-size="10.5" fill="{t["value"]}">{v:.0f}</text>')

    out.append("</svg>")
    return "".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", type=Path, help="skills.json to read")
    src.add_argument("--github", metavar="USER",
                     help="build the axes from that user's language bytes")
    p.add_argument("-o", "--out", type=Path, default=Path("assets/radar"),
                   help="output path WITHOUT extension")
    p.add_argument("--limit", type=int, default=7,
                   help="max axes in --github mode (default 7)")
    p.add_argument("--exclude", default="",
                   help="comma-separated languages to drop in --github mode")
    p.add_argument("--curve", type=float, default=0.0,
                   help="0 = straight polygon, ~0.4 = rounded")
    p.add_argument("--values", action="store_true",
                   help="print the number under each label")
    p.add_argument("--no-title", dest="title", action="store_false",
                   help="omit the title line")
    p.add_argument("--animate", action="store_true",
                   help="grow the shape out of the centre on load")
    a = p.parse_args(argv)

    if a.data:
        title, axes = from_file(a.data)
    else:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        exclude = {s.strip().lower() for s in a.exclude.split(",") if s.strip()}
        title, axes = from_github(a.github, a.limit, exclude, token)

    if len(axes) < 3:
        sys.exit(f"a radar needs at least 3 axes, got {len(axes)}")
    for label, _ in axes:
        if len(label) > MAX_LABEL:
            print(f"  ! \"{label}\" is {len(label)} chars and will run off the "
                  f"side; keep labels under {MAX_LABEL}", file=sys.stderr)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    for theme in ("dark", "light"):
        dest = a.out.with_name(f"{a.out.name}-{theme}.svg")
        dest.write_text(render(title, axes, theme, a), encoding="utf-8")
        print(f"wrote {dest}  ({len(axes)} axes)")


if __name__ == "__main__":
    main()
