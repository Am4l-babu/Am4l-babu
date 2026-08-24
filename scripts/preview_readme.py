#!/usr/bin/env python3
"""
preview_readme.py - render README.md to a local page that looks like GitHub.

    python scripts/preview_readme.py
    start preview-readme.html

Written next to the README so every relative `assets/...` path resolves exactly
as it will on github.com. The page carries a light/dark toggle, because half
your readers see each and the <picture> swaps only reveal themselves under one
of them.

Tries GitHub's own /markdown API first, so what you see is literally GitHub's
renderer. Falls back to mistune when that is rate-limited or offline - the
README is mostly raw HTML anyway, so the two agree closely.

This is a look-before-you-push check, not a guarantee. What it cannot show:
camo image proxying, and the fact that GitHub strips <style> and <script> from
markdown (nothing here uses either).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CSS = """
:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--link:#4493f8;--code:#151b23}
body.light{--bg:#fff;--fg:#1f2328;--muted:#59636e;--line:#d1d9e0;--link:#0969da;--code:#f6f8fa}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.6 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif}
.frame{max-width:1012px;margin:0 auto;padding:24px}
.card{border:1px solid var(--line);border-radius:6px;padding:32px}
.bar{color:var(--muted);font-size:12px;padding:6px 2px;display:flex;justify-content:space-between}
h1,h2{border-bottom:1px solid var(--line);padding-bottom:.3em;margin-top:24px}
h2{font-size:1.5em}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
img{max-width:100%}
hr{height:1px;border:0;background:var(--line);margin:24px 0}
code{background:var(--code);padding:.2em .4em;border-radius:6px;font-size:85%;
 font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
pre{background:var(--code);padding:16px;border-radius:6px;overflow:auto}
pre code{background:none;padding:0}
table{border-collapse:collapse;margin:12px 0}
th,td{border:1px solid var(--line);padding:6px 13px}
tbody tr:nth-child(2n){background:var(--code)}
/* the layout tables holding the radar and project cards should be invisible */
td:has(img),td:has(picture){border:0;background:none!important}
sub{font-size:80%;color:var(--muted)}
button{position:fixed;top:16px;right:16px;z-index:9;cursor:pointer;background:var(--code);
 color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:8px 14px;font:inherit}
.note{color:var(--muted);font-size:13px;padding:10px 2px 18px}
.warn{color:#d29922}
"""

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>README preview</title><style>{css}</style></head><body>
<button onclick="document.body.classList.toggle('light')">toggle theme</button>
<div class="frame">
<p class="note">Rendered by {engine}. Relative paths resolve from this folder, so the
images are the real ones. <span class="warn">The four <code>metrics.*</code> panels and the
snake stay blank until Actions runs on the pushed repo.</span></p>
<div class="bar"><span>{repo}</span><span>README.md</span></div>
<div class="card">{body}</div>
</div>
<script>
// Honour the <picture> swaps: the toggle has to re-pick the source by hand,
// because prefers-color-scheme follows the OS, not this button.
function swap(){{
  const light = document.body.classList.contains('light');
  document.querySelectorAll('picture').forEach(p => {{
    const img = p.querySelector('img');
    const src = p.querySelector(`source[media*="${{light ? 'light' : 'dark'}}"]`);
    if (img && src) img.src = src.getAttribute('srcset');
  }});
}}
new MutationObserver(swap).observe(document.body,{{attributes:true,attributeFilter:['class']}});
swap();
</script></body></html>"""


def via_github(md: str) -> str | None:
    body = json.dumps({"text": md, "mode": "markdown"}).encode()
    req = urllib.request.Request(
        "https://api.github.com/markdown", data=body,
        headers={"User-Agent": "preview_readme.py",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode()
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
        print(f"  . GitHub /markdown unavailable ({e}); using mistune",
              file=sys.stderr)
        return None


def via_mistune(md: str) -> str:
    try:
        import mistune
    except ImportError:
        sys.exit("no renderer available: python -m pip install mistune")
    # The README is largely hand-written HTML blocks, so raw HTML must pass
    # through untouched; the table plugin covers the project list.
    return mistune.create_markdown(escape=False, plugins=["table"])(md)


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--readme", type=Path, default=Path("README.md"))
    p.add_argument("--out", type=Path, default=Path("preview-readme.html"))
    p.add_argument("--repo", default="Am4l-babu / Am4l-babu")
    p.add_argument("--offline", action="store_true",
                   help="skip the GitHub API and go straight to mistune")
    a = p.parse_args(argv)

    if not a.readme.exists():
        sys.exit(f"no {a.readme}")
    md = a.readme.read_text(encoding="utf-8")

    html = None if a.offline else via_github(md)
    engine = "GitHub's own /markdown API" if html else "mistune (local fallback)"
    if html is None:
        html = via_mistune(md)

    a.out.write_text(
        PAGE.format(css=CSS, body=html, engine=engine, repo=a.repo),
        encoding="utf-8")
    print(f"wrote {a.out}  ({a.out.stat().st_size // 1024} KB, via {engine})")


if __name__ == "__main__":
    main()
