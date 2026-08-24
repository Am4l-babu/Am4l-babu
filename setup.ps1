# setup.ps1 - regenerate every asset, then optionally push to Am4l-babu/Am4l-babu.
#
#   .\setup.ps1              # regenerate only
#   .\setup.ps1 -Push        # regenerate, then force-push (replaces the old profile README)
#
# See SETUP.md for the token and workflow setup that this does NOT do.

[CmdletBinding()]
param(
    [string] $User  = 'Am4l-babu',
    [string] $Photo = 'assets/photo.jpg',
    # Which cell of the looks.py matrix becomes assets/portrait.png.
    [string] $Look  = 'photo--sky-round',
    [switch] $Push
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

# --- python ---------------------------------------------------------------
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw 'python is not on PATH' }

Step 'Checking Pillow / numpy / scipy (dotify.py and cutout.py need them)'
try { python -c 'import PIL, numpy, scipy' 2>$null } catch { }
if (-not $?) {
    Write-Host '   installing...'
    python -m pip install --quiet Pillow numpy scipy
}

# --- portrait -------------------------------------------------------------
if (Test-Path $Photo) {
    Step "Cutting the sky out of $Photo"
    # Not used by the current portrait, which keeps the sky - but every other
    # look in the matrix needs it, and it is cheap.
    python scripts/cutout.py $Photo -o assets/photo-cut.png

    Step "Portrait looks -> assets/options"
    python scripts/looks.py

    Step "Installing $Look as the portrait"
    Copy-Item "assets/options/$Look.png" assets/portrait.png -Force
} else {
    Write-Warning "$Photo not found - skipping the portrait. Drop the photo there and rerun."
}

# --- charts and cards -----------------------------------------------------
Step 'Skill radar'
python scripts/radar.py --data assets/skills.json -o assets/radar

Step 'Language radar (live)'
python scripts/radar.py --github $User -o assets/radar-langs `
    --limit 7 --values --curve 0.4 `
    --exclude 'makefile,cmake,batchfile,dockerfile,shell,procfile,linker script'

Step 'Stat and repo cards (live)'
# $env:GITHUB_TOKEN, if set, lifts the 60-calls-an-hour anonymous limit and
# fills in the contribution and streak tiles.
python scripts/cards.py --user $User --projects assets/projects.json --out assets

Write-Host "`nAssets regenerated. Open preview.html to look at them." -ForegroundColor Green

# --- push -----------------------------------------------------------------
if (-not $Push) {
    Write-Host "Run with -Push to publish to https://github.com/$User/$User" -ForegroundColor DarkGray
    return
}

Step "Publishing to https://github.com/$User/$User"
Write-Host "This FORCE-PUSHES and replaces the profile README currently live there." -ForegroundColor Yellow
$answer = Read-Host 'Type the word REPLACE to continue'
if ($answer -cne 'REPLACE') { Write-Host 'Aborted.'; return }

if (-not (Test-Path .git)) {
    git init -b main
    git remote add origin "https://github.com/$User/$User.git"
}
git add .
git commit -m 'New profile README'
if ($?) { git push --force origin main }
