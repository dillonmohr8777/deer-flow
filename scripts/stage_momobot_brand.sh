#!/usr/bin/env bash
# Stage the private MomoBot brand kit into a server-side content dir.
#
#   scripts/stage_momobot_brand.sh <src_dir> <dest_dir>
#
# <src_dir> is the kit folder (agents.json, icons/, mascot/, videos/, stills/, fonts/).
# The About copy comes from $ABOUT_MD (default: the Oct 20 pricing-and-about note),
# section "About MomoBot", written to <dest_dir>/about.md with the price paragraph
# marked <!--pricing--> so the gateway can hide it while show_pricing is false.
# Point config.yaml momobot_brand.content_dir at <dest_dir> (prod: ~/momobot-prod/brand).
# Never commit <dest_dir>; the repo is public and the kit is not client-approved.
set -euo pipefail

[ $# -eq 2 ] || { echo "usage: $0 <src_dir> <dest_dir>" >&2; exit 2; }
src=$1
dest=$2
about_md=${ABOUT_MD:-$HOME/Documents/Codex/2026-10-20/momobot-slack/MOMOBOT-PRICING-AND-ABOUT.md}

[ -f "$src/agents.json" ] || { echo "missing $src/agents.json" >&2; exit 1; }
[ -f "$about_md" ] || { echo "missing About source $about_md" >&2; exit 1; }
mkdir -p "$dest"/{icons,mascot,videos,stills,fonts}

cp "$src/agents.json" "$dest/agents.json"
cp "$src"/icons/*.svg "$dest/icons/"
cp "$src/mascot/momobot-design-c-cutout.png" "$dest/mascot/"
cp "$src"/videos/*.mp4 "$dest/videos/"
cp "$src"/stills/*poster.png "$dest/stills/"
cp "$src"/fonts/* "$dest/fonts/"

# About section: from its heading to the next "## ", heading dropped, price paragraph marked.
awk '/^## About MomoBot/{on=1; next} /^## /{on=0} on' "$about_md" |
  sed -e '/./,$!d' |
  sed -e 's/^\(\*\*What you pay for\.\*\*\)/<!--pricing-->\1/' >"$dest/about.md"
[ -s "$dest/about.md" ] || { echo "About section not found in $about_md" >&2; exit 1; }

python3 - "$dest" <<'PY'
import json, pathlib, subprocess, sys

dest = pathlib.Path(sys.argv[1])
kit = json.loads((dest / "agents.json").read_text())
missing = []

def need(rel):
    if rel and not (dest / rel).is_file():
        missing.append(rel)

for a in kit["agents"] + [kit["max_plus"]]:
    need(a.get("icon"))
    need(a.get("hero_art"))
for v in kit["videos"].values():
    for k in ("landscape", "vertical", "poster_landscape", "poster_vertical"):
        need(v.get(k))
        if k in ("landscape", "vertical") and (dest / v[k]).is_file():
            out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,width,height", "-of", "csv=p=0", str(dest / v[k])], capture_output=True, text=True)
            if out.returncode or not out.stdout.strip():
                missing.append(f"{v[k]} (ffprobe failed)")
if "<!--pricing-->" not in (dest / "about.md").read_text():
    missing.append("about.md (no pricing marker)")
if kit.get("show_pricing") is not False:
    missing.append("agents.json show_pricing must be false when staging")
if missing:
    sys.exit("staging failed: " + ", ".join(missing))
PY

(cd "$dest" && find . -type f ! -name MANIFEST.sha256 | sort | xargs shasum -a 256 >MANIFEST.sha256)
(cd "$dest" && shasum -a 256 -c --quiet MANIFEST.sha256)
echo "staged $(find "$dest" -type f ! -name MANIFEST.sha256 | wc -l | tr -d ' ') files into $dest (agents.json show_pricing=false, videos ffprobe ok, sha256 verified)"
