#!/usr/bin/env bash
# download-tiles.sh — Pre-download CARTO Positron map tiles for all recording sites.
# Run once when you have internet; tiles are served locally by nginx afterward.
#
# Usage:  cd web-viewer && bash scripts/download-tiles.sh
#
# Reads trajectory_latlon.json from each recording to derive bounds,
# downloads z14–z19 tiles with 3-tile padding, stores under public/tiles/.

set -euo pipefail

TILE_URL="https://a.basemaps.cartocdn.com/light_all"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/public/tiles"
RECORDINGS="$(cd "$(dirname "$0")/.." && pwd)/public/recordings"
ZOOM_MIN=14
ZOOM_MAX=19
PAD=3
DELAY=0.05  # seconds between requests — be polite to CDN

mkdir -p "$OUT_DIR"

lat2tiley() {
  local lat=$1 zoom=$2
  python3 -c "
import math
lat_rad = math.radians($lat)
n = 2**$zoom
print(int((1 - math.log(math.tan(lat_rad) + 1/math.cos(lat_rad)) / math.pi) / 2 * n))
"
}

lon2tilex() {
  local lon=$1 zoom=$2
  python3 -c "print(int(($lon + 180) / 360 * 2**$zoom))"
}

downloaded=0
skipped=0
failed=0

for traj in "$RECORDINGS"/*/trajectory_latlon.json; do
  site=$(basename "$(dirname "$traj")")

  # Extract bounds via python (handles the .path[] structure)
  read -r lat_min lat_max lon_min lon_max <<< "$(python3 -c "
import json
data = json.load(open('$traj'))
lats = [p['lat'] for p in data['path']]
lons = [p['lon'] for p in data['path']]
print(min(lats), max(lats), min(lons), max(lons))
")"

  echo "=== $site ==="
  echo "  bounds: lat [$lat_min, $lat_max]  lon [$lon_min, $lon_max]"

  for z in $(seq $ZOOM_MIN $ZOOM_MAX); do
    x_min=$(( $(lon2tilex "$lon_min" "$z") - PAD ))
    x_max=$(( $(lon2tilex "$lon_max" "$z") + PAD ))
    y_min=$(( $(lat2tiley "$lat_max" "$z") - PAD ))
    y_max=$(( $(lat2tiley "$lat_min" "$z") + PAD ))

    for x in $(seq $x_min $x_max); do
      for y in $(seq $y_min $y_max); do
        dest="$OUT_DIR/$z/$x/$y.png"
        if [ -f "$dest" ]; then
          skipped=$(( skipped + 1 ))
          continue
        fi
        mkdir -p "$OUT_DIR/$z/$x"
        url="$TILE_URL/$z/$x/$y.png"
        if curl -sf --max-time 10 -o "$dest" "$url"; then
          downloaded=$(( downloaded + 1 ))
        else
          failed=$(( failed + 1 ))
          rm -f "$dest"
        fi
        sleep "$DELAY"
      done
    done
    echo "  z$z: $(( (x_max - x_min + 1) * (y_max - y_min + 1) )) tiles in range"
  done
  echo
done

echo "Done. downloaded=$downloaded  skipped=$skipped  failed=$failed"
echo "Tile dir: $OUT_DIR ($(du -sh "$OUT_DIR" 2>/dev/null | cut -f1))"
