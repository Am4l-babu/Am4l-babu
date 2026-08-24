# Setup

This folder is the *content* of the special repo `Am4l-babu/Am4l-babu`. Whatever
`README.md` says there is what shows up at the top of
[github.com/Am4l-babu](https://github.com/Am4l-babu).

That repo already exists and already has a README. Everything below assumes you
are **replacing** it.

---

## 0. The portrait

Done — `assets/portrait.png` is the photograph itself with rounded corners, at
600px for the 300px slot so it stays sharp on a retina screen. This section is
for changing it.

### Switching to a different look

`scripts/looks.py` renders the photo as every combination of two axes:

| treatment (what happens to the pixels) | backdrop (what is behind you) |
|---|---|
| `photo` — untouched | `sky` — the photograph, square corners |
| `duotone` — luminance on a navy→cyan ramp | `sky-round` — the photograph, rounded corners ← **current** |
| `dots` — halftone grid, photo colours | `bare` — sky removed, transparent |
| `dots-mono` — the same grid, all cyan | `card-dark` — sky removed, dark card + cyan wash |
| | `card-light` — sky removed, pale card + cyan wash |
| | `circle` — head-and-shoulders disc with a cyan ring |

```powershell
python scripts\looks.py                      # all 24, into assets/options
python scripts\looks.py --only photo --backdrops circle,card-dark   # a subset
copy assets\options\duotone--circle.png assets\portrait.png         # install one
```

Compare them with `assets/options/_grid-dark.png` and `_grid-light.png`, which
lay the whole matrix out on a dark and a light page. Two things they show:

- The `bare` column has nothing behind it, so it changes with the reader's
  theme. Both `card-` columns bring their own background and look identical to
  everybody.
- `dots-mono` on a light page is the weakest cell — cyan on near-white.

`assets/options/` is **gitignored** (24 renders, ~7 MB, all regenerable in one
command). Only the chosen `assets/portrait.png` is committed. Switching looks
means copying a new file over it — the README always points at the same name.

### The two scripts behind the looks

`cutout.py` keys the sky out on hue: blue above the other two channels, keeping
only the blue regions that touch the border, then growing into the pale cloud.
Everything in the `bare`, `card-dark` and `card-light` columns depends on it.
It reports what fraction of the frame survived — this photo lands at 27%.
If it ever eats part of the subject, raise `--threshold`; if sky survives,
lower it. It assumes a plain **sky** background; against a wall it will find
nothing and say so.

`dotify.py` builds the halftone. Two settings in there are not obvious:

- **`--equalize` needs the cutout.** It rescales against the histogram of
  whatever it is handed, and two-thirds of this frame is bright sky — equalise
  the whole thing and the entire tonal range goes to the sky, leaving a black
  silhouette. That is exactly what the first attempt produced.
- **`--gamma 0.30`.** Dot radius tracks brightness and the shirt is near-black,
  so at the default gamma those dots vanish and you get a floating head above a
  bright mundu.

It can also do things the matrix does not cover: `--mode binary` for a grid of
0s and 1s, `--mode ascii` for text you can paste in a code block, `--reveal` for
a scan-line draw-in on load, and dropping `--color` for a cyan-only SVG pair
that swaps on `prefers-color-scheme` (the README would then need a `<picture>`).

### A different photo

```powershell
copy "C:\path\to\new.jpg" assets\photo.jpg
.\setup.ps1                          # cutout + all looks + radars + cards
.\setup.ps1 -Look duotone--circle    # ...and install a different cell
```

The 3:4 framing — full figure against open sky — is worth keeping. The `circle`
look crops that away, which is the tradeoff for the conventional avatar shape.

---

## 1. Push it

```powershell
cd d:\portfolio\PERSONAL-PORTFOLIO\github-profile
git init -b main
git add .
git commit -m "New profile README"
git remote add origin https://github.com/Am4l-babu/Am4l-babu.git
git push --force origin main     # --force: this replaces the old profile README
```

`setup.ps1` does the same thing with a confirmation prompt.

> The old README is not backed up anywhere by this. If you want it, grab it
> first: `curl -o old-profile-README.md https://raw.githubusercontent.com/Am4l-babu/Am4l-babu/main/README.md`

### About the nested repo

`git init` in here puts a second `.git` inside the portfolio repo, and git then
records `github-profile` in the outer repo as an unclickable gitlink instead of
as files. Two clean ways out — pick one:

- **Keep the files in the portfolio repo** (they are useful history) and publish
  from a throwaway clone instead of initialising here:
  ```powershell
  git clone https://github.com/Am4l-babu/Am4l-babu.git $env:TEMP\profile
  robocopy . $env:TEMP\profile /MIR /XD .git
  cd $env:TEMP\profile; git add -A; git commit -m "New profile README"; git push
  ```
- **Or let this be its own repo** and stop the portfolio repo tracking it: add
  `github-profile/` to the portfolio's `.gitignore`, then `git init` here.

---

## 2. The one secret you need

**This is the only piece of data the profile needs from you.** Everything else —
username, repo list, stars, languages, project descriptions — the workflows
already read for themselves.

Two of the three workflows need a token that can read your contribution graph.
The built-in `GITHUB_TOKEN` cannot: the graph is only exposed through the
GraphQL API, which will not answer for it.

1. [Create a classic PAT](https://github.com/settings/tokens/new) with scopes
   **`public_repo`** and **`read:user`**. Nothing else. No expiry, or set a
   calendar reminder — the panels go stale silently when it lapses.
2. Repo → Settings → Secrets and variables → Actions → New repository secret
3. Name it exactly **`METRICS_TOKEN`**, paste the token, save.

What breaks without it:

| | with the token | without |
|---|---|---|
| contribution calendar (isocalendar) | renders | **empty** |
| habits panel | renders | **empty** |
| achievements | renders | **empty** |
| languages panel | renders | **empty** |
| stat card streak tiles | 3 contribution tiles | falls back to top-language + join-year |
| radars, project cards, snake, portrait | fine | fine |

The four `metrics.*` panels are the ones in the middle of the page, so without
the token the profile has a hole in it. Add the secret before judging how it
looks.

---

## 2b. One thing that is knowingly stale

`assets/radar-langs-*.svg` was generated locally **without** a token, and the
anonymous API ran out of its 60 calls an hour partway through the repo sweep —
so it is built from roughly two-thirds of your repos and under-counts Python.
It is committed so the README has no broken image on push. `charts.yml` triggers
on any push that touches `scripts/`, so the first push replaces it with a
complete one. Nothing to do here; just do not read the current numbers as final.

---

## 3. Kick the workflows

Actions tab → run each one manually once (`Run workflow`), or just push again.

| workflow | what it makes | when |
|---|---|---|
| `metrics.yml` | `assets/metrics.*.svg` — isocalendar, habits, languages, achievements, in a light **and** a dark render each (8 files) | every 6h |
| `charts.yml` | `assets/radar-*.svg`, `assets/card-*.svg` | daily 03:30 UTC, and on any push touching the JSON or the scripts |
| `snake.yml` | the snake animation, pushed to an orphan `output` branch | every 12h |

The snake is the one that looks broken longest — it needs the `output` branch to
exist, which only happens after `snake.yml` runs once.

`metrics.yml` runs as a 2-job matrix, light then dark, one at a time — each job
commits its SVGs straight to the repo, so they must not race. That is eight
metrics invocations per run and takes a few minutes. The README picks the right
one per reader with `<picture>`, which is why the calendar does not sit on a
white slab inside a dark page.

---

## 4. Make it yours

Everything below is a plain file. Edit it, push, the workflow redraws.

**`assets/skills.json`** — the left-hand radar. The numbers in there were
inferred from what your repos are written in, not from you. They are
self-ratings; change them.

**`assets/projects.json`** — which four repos get cards, and the blurb on each.
Stars, forks, language and the `live ↗` marker come from the API on every run,
so they are never stale. If you set the description on the repo itself you can
drop it here — the repo's own description is the fallback.

Changing which repos are featured means changing two things: this file, **and**
the four `<td>` blocks in `README.md`, which name the SVGs by filename.

**The tagline** — the `lines=` parameter on the `readme-typing-svg` URL near the
top of `README.md`. `+` is a space, `%26` is `&`.

**The colour** — cyan `#00f0ff`, matching itzmeaml.in. It appears in:
`scripts/dotify.py` (`THEMES`), `scripts/radar.py` (`THEMES`),
`scripts/cards.py` (`THEMES`), the snake palette in `.github/workflows/snake.yml`,
and the badge/typing URLs in `README.md`.

---

## 5. Checking it locally

```powershell
python -m pip install Pillow numpy scipy mistune
python scripts\radar.py --data assets\skills.json -o assets\radar
python scripts\cards.py --user Am4l-babu --out assets

python scripts\preview_readme.py ; start preview-readme.html   # the whole page
start preview.html                                             # just the artwork
```

`preview_readme.py` renders README.md through GitHub's own `/markdown` API and
wraps it in GitHub's page styling, writing `preview-readme.html` next to the
README so every relative `assets/...` path resolves the way it will on
github.com. It falls back to mistune when the API is rate-limited. Use the
light/dark toggle on the page — the `<picture>` swaps only show one of their two
faces at a time. The file is gitignored.

`cards.py` and `radar.py --github` are stdlib-only. Unauthenticated they get 60
API calls an hour, which is enough for one run and not two. Set `$env:GITHUB_TOKEN`
to a PAT to lift that (and to fill in the streak tiles).

GitHub's markdown renderer is close enough to a browser for this, but not
identical: it strips `<style>` from inline SVG in some contexts and ignores
`<script>` entirely. Nothing here relies on either. `preview.html` is the fast
check; the real check is pushing and looking.

---

## Why the cards are self-hosted

The obvious way to build this page is `github-readme-stats`, `streak-stats` and
`github-profile-trophy`. All three are shared public instances. They return 503
when overloaded and 402 when out of quota, and when they do, that entire section
of your profile turns into broken-image icons — on the page recruiters look at.

`scripts/cards.py` renders the same information into SVG files that live in this
repo. They render as long as GitHub renders. The tradeoff is that they refresh on
a schedule rather than on page load, which for a follower count nobody is
watching in real time is not a tradeoff at all.

`lowlighter/metrics` is the exception: it runs as an Action inside your repo and
commits the result, so it has the same property.
