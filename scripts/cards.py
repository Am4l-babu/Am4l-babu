#!/usr/bin/env python3
"""
cards.py - render GitHub stat and repo cards as SVGs. Stdlib only.

    python scripts/cards.py --user Am4l-babu --out assets

Writes <out>/card-stats-{dark,light}.svg plus one card per repo listed in
assets/projects.json, as <out>/card-<repo>-{dark,light}.svg.

These deliberately replace github-readme-stats / streak-stats /
github-profile-trophy. Those are shared public instances that go down (503),
run out of quota (402), or time out - and when they do, the whole section of
the README turns into broken-image icons. These are files in your own repo, so
they render for as long as GitHub renders.

Stars, forks and language come from the live API on every run. Descriptions
come from projects.json when set, otherwise from the repo's own description.

A token in $GITHUB_TOKEN unlocks the contribution and streak tiles, which need
the GraphQL API. Without one the card still renders, just with fewer tiles.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = {"User-Agent": "cards.py"}

THEMES = {
    "dark": {
        "bg": "#0d1117", "border": "#30363d", "title": "#00f0ff",
        "text": "#c9d1d9", "muted": "#8b949e", "value": "#e6edf3",
        "accent": "#00f0ff",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "title": "#0e7490",
        "text": "#1f2328", "muted": "#57606a", "value": "#1f2328",
        "accent": "#0e7490",
    },
}

# GitHub linguist colours for the languages likely to show up here
LANG_COLOR = {
    "C": "#555555", "C++": "#f34b7d", "Python": "#3572A5", "HTML": "#e34c26",
    "CSS": "#563d7c", "JavaScript": "#f1e05a", "TypeScript": "#3178c6",
    "Jupyter Notebook": "#DA5B0B", "Dart": "#00B4AB", "Java": "#b07219",
    "Shell": "#89e051", "CMake": "#DA3434", "Makefile": "#427819",
    "Rust": "#dea584", "Go": "#00ADD8", "Kotlin": "#A97BFF", "Swift": "#F05138",
    "Vue": "#41b883", "Svelte": "#ff3e00", "SCSS": "#c6538c", "Lua": "#000080",
}

FONT = "ui-sans-serif,-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"

# Octicon outlines on a 16x16 grid. Paths rather than the characters U+2605 /
# U+2442, because those codepoints are missing from plenty of system fonts and
# fall back to a tofu box.
ICON_STAR = ("M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 "
             "2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 "
             "01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25z")
ICON_FORK = ("M5 5.372v.878c0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75v-.878a2.25 2.25 0 "
             "111.5 0v.878a2.25 2.25 0 01-2.25 2.25h-1.5v2.128a2.251 2.251 0 11-1.5 "
             "0V8.5h-1.5A2.25 2.25 0 013.5 6.25v-.878a2.25 2.25 0 111.5 0zM5 3.25a.75.75 0 "
             "10-1.5 0 .75.75 0 001.5 0zm6.75.75a.75.75 0 100-1.5.75.75 0 000 1.5zm-3 "
             "8.75a.75.75 0 100-1.5.75.75 0 000 1.5z")


def icon(path: str, x: float, y: float, size: float, fill: str) -> str:
    return (f'<path transform="translate({x:.1f},{y:.1f}) scale({size / 16:.3f})" '
            f'fill="{fill}" d="{path}"/>')


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def wrap(text: str, width: int, lines: int) -> list[str]:
    """Greedy wrap to `lines` lines of about `width` characters, ellipsising."""
    words, out, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            out.append(cur)
            cur = w
            if len(out) == lines:
                break
        else:
            cur = f"{cur} {w}".strip()
    if len(out) < lines and cur:
        out.append(cur)
    if len(" ".join(out)) < len(text.rstrip()):
        out[-1] = out[-1][:width - 1].rstrip() + "…"
    return out


# --------------------------------------------------------------------------- #
# api
# --------------------------------------------------------------------------- #

def rest(path: str, token: str | None, tries: int = 3):
    """GET and parse JSON, retrying transient failures.

    HTTP errors are NOT retried - a 404 or a 403 rate-limit will not fix
    itself, and the caller wants to see it. Dropped sockets will.
    """
    req = urllib.request.Request("https://api.github.com" + path, headers=dict(UA))
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


def graphql(query: str, variables: dict, token: str):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={**UA, "Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


CONTRIB_QUERY = """
query($login:String!){
  user(login:$login){
    contributionsCollection{
      contributionCalendar{
        totalContributions
        weeks{ contributionDays{ date contributionCount } }
      }
    }
  }
}
"""


def fetch_contributions(user: str, token: str | None):
    """(total, current_streak, longest_streak), or None without a token."""
    if not token:
        return None
    try:
        data = graphql(CONTRIB_QUERY, {"login": user}, token)
        cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    except (urllib.error.HTTPError, OSError, KeyError, TypeError) as e:
        print(f"  ! contributions unavailable ({e}) - skipping those tiles",
              file=sys.stderr)
        return None

    days = [d for w in cal["weeks"] for d in w["contributionDays"]]
    days.sort(key=lambda d: d["date"])
    today = dt.date.today().isoformat()
    days = [d for d in days if d["date"] <= today]

    longest = run = 0
    for d in days:
        run = run + 1 if d["contributionCount"] > 0 else 0
        longest = max(longest, run)

    # An empty today does not break a streak until the day is over, so start
    # from yesterday when today is still at zero.
    current = 0
    for d in reversed(days):
        if d["contributionCount"] > 0:
            current += 1
        elif d["date"] == today:
            continue
        else:
            break
    return cal["totalContributions"], current, longest


def fetch_stats(user: str, token: str | None):
    prof = rest(f"/users/{user}", token)
    stars = repos = 0
    langs: dict[str, int] = {}
    page = 1
    while page <= 4:
        batch = rest(f"/users/{user}/repos?per_page=100&page={page}&type=owner", token)
        if not batch:
            break
        for r in batch:
            if r.get("fork"):
                continue
            repos += 1
            stars += r.get("stargazers_count", 0)
            if r.get("language"):
                langs[r["language"]] = langs.get(r["language"], 0) + 1
        if len(batch) < 100:
            break
        page += 1
    top = max(langs, key=langs.get) if langs else "-"
    return {
        "name": prof.get("name") or user,
        "repos": repos,
        "stars": stars,
        "followers": prof.get("followers", 0),
        "top_lang": top,
        "since": prof["created_at"][:4],
    }


# --------------------------------------------------------------------------- #
# stat card
# --------------------------------------------------------------------------- #

W_STATS, TILE_H = 480, 62


def card_stats(user: str, s: dict, contrib, theme: str) -> str:
    t = THEMES[theme]
    tiles = [
        ("public repos", f"{s['repos']}"),
        ("stars earned", f"{s['stars']}"),
        ("followers", f"{s['followers']}"),
    ]
    if contrib:
        total, cur, longest = contrib
        tiles += [("contributions / yr", f"{total}"),
                  ("current streak", f"{cur}d"),
                  ("longest streak", f"{longest}d")]
    else:
        tiles += [("top language", s["top_lang"]),
                  ("on github since", s["since"])]

    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    head = 54
    h = head + rows * TILE_H + 16
    pad, gap = 18, 10
    tw = (W_STATS - 2 * pad - (cols - 1) * gap) / cols

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W_STATS} {h}" '
           f'width="{W_STATS}" height="{h}" role="img" '
           f'aria-label="GitHub statistics for {esc(user)}">',
           f'<rect x="0.5" y="0.5" width="{W_STATS - 1}" height="{h - 1}" rx="10" '
           f'fill="{t["bg"]}" stroke="{t["border"]}"/>',
           f'<text x="{pad}" y="32" font-family="{FONT}" font-size="15" '
           f'font-weight="700" fill="{t["title"]}">{esc(s["name"])}</text>',
           f'<text x="{W_STATS - pad}" y="32" text-anchor="end" font-family="{MONO}" '
           f'font-size="11.5" fill="{t["muted"]}">@{esc(user)}</text>',
           f'<line x1="{pad}" y1="42" x2="{W_STATS - pad}" y2="42" '
           f'stroke="{t["border"]}"/>']

    for i, (label, value) in enumerate(tiles):
        x = pad + (i % cols) * (tw + gap)
        y = head + (i // cols) * TILE_H
        out.append(f'<text x="{x + tw / 2:.1f}" y="{y + 26:.1f}" text-anchor="middle" '
                   f'font-family="{MONO}" font-size="22" font-weight="700" '
                   f'fill="{t["value"]}">{esc(value)}</text>')
        out.append(f'<text x="{x + tw / 2:.1f}" y="{y + 43:.1f}" text-anchor="middle" '
                   f'font-family="{FONT}" font-size="10.5" '
                   f'fill="{t["muted"]}">{esc(label)}</text>')

    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# repo card
# --------------------------------------------------------------------------- #

W_REPO, H_REPO = 420, 130


def card_repo(repo: dict, desc: str, theme: str) -> str:
    t = THEMES[theme]
    pad = 16
    lang = repo.get("language")
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W_REPO} {H_REPO}" '
           f'width="{W_REPO}" height="{H_REPO}" role="img" '
           f'aria-label="{esc(repo["name"])}: {esc(desc)}">',
           f'<rect x="0.5" y="0.5" width="{W_REPO - 1}" height="{H_REPO - 1}" rx="10" '
           f'fill="{t["bg"]}" stroke="{t["border"]}"/>',
           f'<text x="{pad}" y="30" font-family="{FONT}" font-size="15" '
           f'font-weight="700" fill="{t["title"]}">{esc(repo["name"])}</text>']

    for i, line in enumerate(wrap(desc or "No description yet.", 52, 3)):
        out.append(f'<text x="{pad}" y="{54 + i * 17}" font-family="{FONT}" '
                   f'font-size="12" fill="{t["text"]}">{esc(line)}</text>')

    fy = H_REPO - 18
    x = pad
    if lang:
        out.append(f'<circle cx="{x + 5}" cy="{fy - 4}" r="5" '
                   f'fill="{LANG_COLOR.get(lang, "#8b949e")}"/>')
        out.append(f'<text x="{x + 16}" y="{fy}" font-family="{FONT}" font-size="11.5" '
                   f'fill="{t["muted"]}">{esc(lang)}</text>')
        x += 26 + 7 * len(lang)

    out.append(icon(ICON_STAR, x, fy - 12, 13, t["muted"]))
    out.append(f'<text x="{x + 17}" y="{fy}" font-family="{MONO}" font-size="11.5" '
               f'fill="{t["muted"]}">{repo.get("stargazers_count", 0)}</text>')
    x += 48
    out.append(icon(ICON_FORK, x, fy - 12, 13, t["muted"]))
    out.append(f'<text x="{x + 17}" y="{fy}" font-family="{MONO}" font-size="11.5" '
               f'fill="{t["muted"]}">{repo.get("forks_count", 0)}</text>')

    if repo.get("homepage"):
        out.append(f'<text x="{W_REPO - pad}" y="{fy}" text-anchor="end" '
                   f'font-family="{MONO}" font-size="11" '
                   f'fill="{t["accent"]}">live ↗</text>')

    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user", required=True)
    p.add_argument("--out", type=Path, default=Path("assets"))
    p.add_argument("--projects", type=Path, default=Path("assets/projects.json"),
                   help="featured repos and their description overrides")
    a = p.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    a.out.mkdir(parents=True, exist_ok=True)

    stats = fetch_stats(a.user, token)
    contrib = fetch_contributions(a.user, token)
    for theme in ("dark", "light"):
        dest = a.out / f"card-stats-{theme}.svg"
        dest.write_text(card_stats(a.user, stats, contrib, theme), encoding="utf-8")
        print(f"wrote {dest}")

    if not a.projects.exists():
        print(f"no {a.projects}, skipping repo cards")
        return

    for entry in json.loads(a.projects.read_text(encoding="utf-8"))["projects"]:
        name = entry["repo"]
        try:
            repo = rest(f"/repos/{a.user}/{name}", token)
        except (urllib.error.HTTPError, OSError) as e:
            # A renamed or newly-private repo should not fail the whole run and
            # take every other card down with it.
            print(f"  ! {name}: {e} - skipped", file=sys.stderr)
            continue
        desc = entry.get("description") or repo.get("description") or ""
        for theme in ("dark", "light"):
            dest = a.out / f"card-{name}-{theme}.svg"
            dest.write_text(card_repo(repo, desc, theme), encoding="utf-8")
            print(f"wrote {dest}")


if __name__ == "__main__":
    main()
