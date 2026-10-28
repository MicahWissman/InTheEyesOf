# Agent Runbook: one Aria recording → InTheEyesOf web viewer

This runbook takes one Aria Gen 1 recording (a VRS file plus its MPS output) and turns it into a recording you can open in `web-viewer/`. It follows the 2026-10 runs of `tour1_seg0`, `kristin_cowgill_seg0` and `collin_gilbert`. Every command runs from the repo root (`ITEO/InTheEyesOf`).

## 0. Before you start

- **Conda env:** use `aria-dev` (`P=~/anaconda3/envs/aria-dev/bin/python`). It has everything the pipeline needs once `moviepy<2` is installed, which is already done.
  - pip warns that projectaria-tools wants moviepy>=2. Ignore it: only the unused `vrs_to_mp4` tool needs moviepy 2.
- **Dependency rule:** if a dependency problem comes up, **stop and ask the user** before installing, pinning or patching code.
- **Gemini:** Stages 1, 3 and 4 call the Gemini research service. They read `secrets.json` in the repo root, which is a symlink.
  - Check the service with a one-line POST before a long run: `{"prompt": "Reply with exactly: OK"}`, with `Authorization: <RESEARCH_PASSWORD>`.
  - The first call can take about 30 s while the service starts up.
- **MPS:** the recording's MPS folder needs `slam/`, `eye_gaze/` and `hand_tracking/`. Check `slam/summary.json` for SUCCESS.
  - If SLAM failed with error 102, it's IMU saturation. Use the `fix-mps-health-check` skill: split the VRS, run MPS on the seg VRS, and use the seg everywhere afterwards.
- **GPS:** check `geo_available` in `slam/closed_loop_trajectory.csv`. The map bake needs it. If it is 0% everywhere (recording started and stayed indoors, so the GPS never got a fix), see "Indoor sites with no GPS" below.
- **Memory (WSL has ~15 GB):** run heavy steps **one at a time**. Measured peaks: a large-v3 CPU transcription ~7–8.5 GB, Stage 1 ~2–5 GB, the combine ~9–11 GB. Two transcriptions at once crashed WSL.
- **Never `pkill -f` / `pgrep -f` a pattern that appears in your own command line**: it matches (and kills, exit 144) the calling shell, or makes a wait loop spin forever. Use PIDs from `ps -eo pid,args | grep "[p]attern"`.
- **Commits:** don't commit unless the user asks.

Variables used below:

```bash
P=~/anaconda3/envs/aria-dev/bin/python
ID=<recording_id>          # e.g. kristin_cowgill_seg0 (also the viewer folder name)
V=/path/to/recording.vrs   # the seg VRS if the recording was split
M=/path/to/mps_<name>_vrs  # MPS root with slam/ eye_gaze/ hand_tracking/
R=pipeline_results/$ID; I=$R/inputs; mkdir -p $I
```

## 1. Audio and sensors (in parallel, about 1 min)

```bash
$P scripts/gaze/semantic/vrs_to_audio_direct.py --vrs $V --output $I/$ID.wav --mix best > $I/audio.log 2>&1 &
$P scripts/gaze/semantic/extract_sensors.py --vrs $V --out-prefix $I/$ID > $I/sensors.log 2>&1 &
wait
```

## 2. Transcription (CPU, about 15–40 min; run it in the background)

The aria-dev GPU path is broken (CUDA 12 vs 13 mismatch), so use `--device cpu`.

```bash
$P scripts/gaze/semantic/transcribe_wav.py --wav $I/$ID.wav --segments $I/${ID}_segments.csv \
   --output $I/${ID}_transcript.txt --device cpu --model large-v3 > $I/transcribe.log 2>&1
```

**Check the proper nouns.** Whisper wrote "Cowgill" as "Kogel".

1. Find the variants: `grep -ohiE "<pattern>" $I/*_transcript.txt | sort | uniq -c`.
2. Back up the originals: `cp $f $f.whisper-orig`.
3. Fix them with `sed` in the transcript and segments CSV before Stage 1. If you fix them after Stage 1, also fix `stage1/semantic_results.json`.
4. Ask the user before changing anything.

## 3. Geo bake (point cloud and trajectory in the map frame, about 1 min)

```bash
$P scripts/bake_geo_aligned_recording.py --trajectory $M/slam/closed_loop_trajectory.csv \
   --points $M/slam/semidense_points.csv.gz --out $R/baked --recording-id $ID --recording-title "<Title>" > $R/bake.log 2>&1
```

This writes `baked/pointcloud.ply` and `baked/trajectory_latlon.json`. The trajectory file includes `enu_origin` and `"baked": true`.

## 4. Stage 1: gaze events (about 20–40 min, makes Gemini calls)

```bash
$P scripts/gaze/semantic/spatial_transcript_summarizer.py --mps_root $M --vrs_path $V \
   --transcript $I/${ID}_transcript.txt --output $R/stage1 > $R/stage1.log 2>&1
```

Then check:
- the number of events;
- `mean_quality` and `fallback_ratio` in `stage1/semantic_results.json`;
- no "AI processing failed" or "Gemini Error" lines in the log.

The point-cloud subsample is seeded, so a rerun gives the same events.

## 5. Choose the grouping radius (no AI calls). Show the user before Stage 3.

Use a complete-linkage sweep over the event centroids:

```python
import json, sys, numpy as np
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import pdist
e = json.load(open(sys.argv[1])); Z = linkage(pdist([[x['gx'], x['gy'], x['gz']] for x in e]), 'complete')
for r in [1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30]:
    s = np.bincount(fcluster(Z, r, 'distance'))[1:]
    print(f"{r:>4} m -> {len(s):>3} anchors (singletons {(s==1).sum()}, max {s.max()})")
```

Good radii depend a lot on the site:

| Recording | Walk | Events | Radius | Anchors |
|---|---|---|---|---|
| Tour1 seg0 | 1.1 km outdoor | 156 | 30 m | 28 |
| Kristin Cowgill seg0 | 204 m mostly indoor | 109 | 1.5 m | 22 |
| Collin Gilbert | 394 m mostly indoor | 89 | 6 m | 22 |

## 6. Stage 3: narrative synthesis (Gemini)

```bash
$P scripts/gaze/semantic/narrative_synthesizer.py --results_json $R/stage1/semantic_results.json \
   --mps_root $M --output $R/stage1/narrative_anchors.json --group_radius <R> > $R/stage3.log 2>&1
```

Every anchor should have a `narrative_title`. If the AI's JSON fails to parse, fix the parse only and leave the text alone.

## 7. Move the anchors into the map frame and add ids (required)

No repo script does this yet. Save the helper below (for example as `bake_anchors.py` in your scratchpad) and run it:

```bash
cp $R/stage1/narrative_anchors.json $R/narrative_anchors.world.json
$P bake_anchors.py --trajectory $M/slam/closed_loop_trajectory.csv --baked-traj $R/baked/trajectory_latlon.json \
   --anchors $R/narrative_anchors.world.json --out $R/narrative_anchors.json
```

The viewer breaks in two ways without this step:
- **No `id` field:** map markers can't be clicked.
- **Graph built from SLAM-frame anchors:** the graph draws Z-up, rotated 90° against the cloud.

```python
#!/usr/bin/env python3
"""Apply bake_geo_aligned_recording.py's world->Three.js transform to anchors (+ add id)."""
import argparse, json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, "<repo>/scripts")
import bake_geo_aligned_recording as B

ap = argparse.ArgumentParser()
for a in ("--trajectory", "--baked-traj", "--anchors", "--out"): ap.add_argument(a, required=True)
args = ap.parse_args()

rows, world_geo, ecef_geo = B.load_trajectory(Path(args.trajectory))
R_w2e, t_w2e = B.umeyama_rigid(world_geo, ecef_geo)
c = ecef_geo.mean(0); lat0, lon0, _ = B.ecef_to_wgs84(*c)
R_e2enu = B.enu_rotation_at(lat0, lon0)
R = B.R_ENU2THREE @ R_e2enu @ R_w2e                 # same as the bake (no --gps-offset)
t = B.R_ENU2THREE @ (R_e2enu @ (t_w2e - c))

by_t = {int(r["tracking_timestamp_us"]): r for r in rows}   # verify vs baked trajectory
err = max(np.linalg.norm(np.array([float(by_t[p["t"]][k]) for k in ("tx_world_device", "ty_world_device", "tz_world_device")]) @ R.T + t
                         - [p["wx"], p["wy"], p["wz"]]) for p in json.load(open(args.baked_traj))["path"])
print(f"baked-trajectory check: max {err*1000:.3f} mm")
if err > 1e-3: sys.exit("transform does not reproduce the bake — refusing to write")

anchors = json.load(open(args.anchors))
for i, a in enumerate(anchors):
    p = np.array([a["gx"], a["gy"], a["gz"]]) @ R.T + t
    a["world_gx"], a["world_gy"], a["world_gz"] = a["gx"], a["gy"], a["gz"]
    a["gx"], a["gy"], a["gz"] = (float(v) for v in p)
    a["id"] = i                                       # viewer keys anchors (and graph nodes) by id
json.dump(anchors, open(args.out, "w"), indent=2, ensure_ascii=False)
np.savez(Path(args.out).with_suffix(".xform.npz"), R=R, t=t)
```

Expect the check to report under 0.1 mm.

## 8. Stage 4: semantic graph (Gemini, about 10–20 min)

Build the graph from the **map-frame** anchors so that the node `pos` values match the cloud:

```bash
$P scripts/gaze/semantic/semantic_network_builder.py --anchors $R/narrative_anchors.json \
   --output $R/semantic_graph.json --threshold 0.6 [--lam 0.2 --gamma 0.25] > $R/graph.log 2>&1
```

- **Edge types:** edges are typed (spatial, thematic or referential), and each type has its own tau.
- **`--gamma` hardly changes the edge count. `--lam` (spatial decay) does.**
  - At the default `--lam 0.05`, any two anchors within about 18 m count as "spatial". That covers a whole building.
  - For indoor or short walks, use `--lam 0.2` (within about 4.6 m).
- **Preview before spending Gemini calls:** add `--count-only` to get just the edge count.
- **Reference counts:** Tour1 had 46 edges for 28 anchors. Kristin 64 / 22 and Collin 40 / 22, both with `--lam 0.2`.
- **Check:** every link has a `rationale` with no "fail" or "error" in it.
- **Python output is buffered**, so the log looks frozen while the rationale calls run. Use `python -u` if you want live progress.

## 9. Web viewer

```bash
D=web-viewer/public/recordings/$ID; mkdir -p $D
cp $R/narrative_anchors.json $R/semantic_graph.json $R/baked/pointcloud.ply $R/baked/trajectory_latlon.json $D/
```

Add an entry to `web-viewer/public/recordings/manifest.json` → `recordings`, copying the shape of `tour1_seg0`:

```json
{ "id": "<ID>", "lang": "en", "title": "<Title>",
  "anchorsFile": "narrative_anchors.json", "pointCloudFile": "pointcloud.ply", "pointCloudLodFile": "pointcloud.ply",
  "semanticGraphFile": "semantic_graph.json", "trajectoryFile": "trajectory_latlon.json" }
```

Remove entries whose files are missing, so the selection screen doesn't fill up with dead recordings.

## 10. Verify

1. `python3 -m json.tool manifest.json`, then `cd web-viewer && npm run build`.
2. Start the preview with `npx vite preview --port 4179`. It serves **HTTPS** (self-signed certificate), so give Playwright `ignoreHTTPSErrors`.
3. If Playwright's own browser is missing, point `executablePath` at a cached one under `~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome`.
4. Open `https://localhost:4179/?recording=<ID>`. Every file should return 200.
   - Position comes from each phone's own GPS. The shared relay (`web-viewer/server/gps-relay.js`, `wss://<host>/gps`) is off unless the URL has `?gpsRelay=1`. Don't turn it on for multi-person studies: it sends each visitor's position to every other viewer.
   - The intro card is always the Carona one in Italian; dismiss it with "Inizia a esplorare".
   - The intro/welcome overlays (`.intro-overlay`, `.welcome-overlay`) can keep intercepting clicks in headless mode. Remove them with `page.evaluate(() => document.querySelectorAll('.intro-overlay,.welcome-overlay').forEach(e => e.remove()))`, or use `dispatchEvent('click')` on `.anchor-item`.
5. Click an anchor marker. It should grow and open its narrative in the sidebar.
6. The anchors should sit on the walked path on the satellite map.
7. Report: anchor and edge counts, the radius and graph flags used, any failures. Mention what you couldn't test (phone GPS, AR, audio).

## Several recordings of the same place (one combined multi-SLAM experience)

Done for Cowgill on 2026-10-27: `cowgill_combined` = Collin + Kristin, 44 anchors, 193 edges. The individual experiences (`collin_gilbert`, `kristin_cowgill_seg0`) stay in the viewer unchanged.

**Rule: each person's perspective must stay separable.** Every combined anchor carries:

| Field | Meaning |
|---|---|
| `source_recording` | the single-run ID (`collin_gilbert`) |
| `source_person` | display name (`Collin`) |
| `source_color` | marker / tag colour for that person |
| `source_anchor_id` | the anchor's `id` in that person's own experience (1:1 mapping) |
| `source_start_ts`, `source_end_ts` | original device-clock timestamps |

Graph links get `cross_recording` (true / false) and `people` (e.g. `["Collin", "Kristin"]`). `anchor_sources.csv` lists every anchor with its person, for analysis.

### A. Run each recording on its own first (steps 1–10)

The combined experience reuses each person's Stage 1 events and Stage 3 narratives verbatim, so the text is identical across the individual and combined experiences. Finish the single-SLAM runs first, including the "Kogel" fix.

### B. Multi-SLAM

```bash
aria_mps multi -i a.vrs -i b_seg0.vrs -o mps_<site>_combined -n <site>_combined   # one -i per VRS; seg VRS if split
```

Output layout (SLAM only; no eye gaze or hand tracking, which the single runs already have):

```
mps_<site>_combined/
  vrs_to_multi_slam.json   # {"<vrs path>": "0", ...} — which numbered folder is which person. CHECK IT.
  0/slam/  1/slam/         # closed_loop_trajectory.csv, semidense_points.csv.gz, summary.json, ...
  summary.json.zip         # despite the name, plain JSON (Aligner componentsBefore/After)
```

Check:
- Every `*/slam/summary.json` is SUCCESS.
- All trajectories share one `graph_uid`.
- `geo_available` = 1. Cowgill kept 100% after multi-SLAM.

### C. Combine (no Gemini calls, about 3 min)

```bash
C=/path/to/site_dir
$P scripts/combine_multislam_recordings.py --out pipeline_results/<site>_combined \
  --part <idA>:<PersonA>:<single MPS A>/slam:$C/mps_<site>_combined/<folder A>/slam \
  --part <idB>:<PersonB>:<single MPS B>/slam:$C/mps_<site>_combined/<folder B>/slam
```

`<id>` is the `pipeline_results/<id>` folder from step A. Take the folder numbers from `vrs_to_multi_slam.json`. For Cowgill, Collin = 0 and Kristin = 1.

What the script does:
1. **Re-registers each person.** It fits single-SLAM world → multi-SLAM world (rigid Umeyama on poses with matching timestamps) and applies the fit to `stage1/semantic_results.json` and `narrative_anchors.world.json`.
   - It refuses to continue if RMSE > 25 cm. In that case, rerun Stage 1 on a per-person MPS root: symlink `eye_gaze/` and `hand_tracking/` from the single run and `slam/` from the multi output. Then run Stage 3 and re-run the combine.
   - Cowgill fits: Collin 3.7 cm, Kristin 1.8 cm.
2. **Bakes once for everyone.** It fits one world→ECEF transform from all parts' geo rows (do not run `bake_geo_aligned_recording.py` per person: each bake picks its own ENU origin, and the people would drift apart). It stacks the clouds (200k points per person), then writes the path and map-frame anchors with `id` = merged index.
3. **Puts the people end to end on one timeline.** Each person has their own device clock, and the clocks overlap. The viewer places map markers by binary-searching `path[].t` with `anchor.start_ts`, so the script shifts each later person by a constant (`segments[].t_offset_us`, plus a 60 s gap) and keeps the originals in `source_start_ts` / `source_end_ts`. Each path point has `src`. `segments` gives each person's path index range.

Outputs in `pipeline_results/<site>_combined/`:
- `narrative_anchors.json` (map frame)
- `narrative_anchors.world.json` (multi-SLAM frame)
- `anchor_sources.csv`
- `combine_params.json`
- `baked/`
- `parts/<id>/` (multi-frame events and anchors, `single_to_multi.npz`)

Sanity check: anchors of the same place from different people should be close together. For Cowgill: library ↔ library 1.5 m, lobby ↔ lobby 2.1 m.

### D. Graph (Gemini only for the cross-person edges)

```bash
R=pipeline_results/<site>_combined
$P -u scripts/gaze/semantic/semantic_network_builder.py --anchors $R/narrative_anchors.json \
   --output $R/semantic_graph.json --threshold 0.6 --lam 0.2 --gamma 0.25 --count-only   # preview
$P -u scripts/gaze/semantic/semantic_network_builder.py --anchors $R/narrative_anchors.json \
   --output $R/semantic_graph.json --threshold 0.6 --lam 0.2 --gamma 0.25 --no-rationale > $R/graph.log 2>&1
$P scripts/gaze/semantic/transplant_rationales.py --merged $R/semantic_graph.json \
   --source pipeline_results/<idA>/semantic_graph.json --source pipeline_results/<idB>/semantic_graph.json
$P -u scripts/gaze/semantic/repair_rationales.py --graph $R/semantic_graph.json > $R/repair.log 2>&1   # rerun until 0 remain
```

- Use the same `--lam` / `--gamma` as the single runs. That way the within-person edges are exactly the single graphs' edges, and transplant copies all their rationales.
- Cowgill: 104 within-person edges transplanted (40 Collin + 64 Kristin), 89 Collin↔Kristin edges generated. The transplant output must show zero within-person placeholders.

Then tag the graph so each node and link shows whose perspective it is:

```python
import json
R = "pipeline_results/<site>_combined"
A = {a["id"]: a for a in json.load(open(f"{R}/narrative_anchors.json"))}
g = json.load(open(f"{R}/semantic_graph.json"))
for n in g["nodes"]:
    a = A[int(n["id"])]
    n.update({k: a[k] for k in ("source_recording", "source_person", "source_color", "source_anchor_id")})
for l in g["links"]:
    p = sorted({A[l["source"]]["source_person"], A[l["target"]]["source_person"]})
    l["people"], l["cross_recording"] = p, len(p) > 1
json.dump(g, open(f"{R}/semantic_graph.json", "w"), indent=2, ensure_ascii=False)
```

### E. Viewer

Copy `narrative_anchors.json`, `semantic_graph.json`, `baked/pointcloud.ply` and `baked/trajectory_latlon.json` to `web-viewer/public/recordings/<site>_combined/`, and add a manifest entry (title e.g. "… (Combined: Collin + Kristin)"). Then verify as in step 10. Also check that the anchor list shows the expected count of `.person-tag` per person (Cowgill: 22 Collin, 22 Kristin), and that selecting an anchor shows its person tag in the sidebar title.

The viewer reads the source tags (added 2026-10-27):
- Markers in 3D and on the map use `source_color` (Collin amber `#f59e0b`, Kristin purple `#a855f7`).
- The sidebar title, the anchor list and both ends of a selected link show a `person-tag` with `source_person`.
- Anchors without these fields render exactly as before.

The `start_ts` shift doesn't change a recording's narrative or audio. `relative_time` / `start_sec` still count from each person's own recording start.

### Indoor sites with no GPS, no single-SLAM runs (Cowgill Hall Robotics, 2026-10-28)

`robotics_lab_combined` = four people in one small robotics lab (Gen 1, about 4–16 min each). It differed from Cowgill in four ways. Follow this route whenever the multi-SLAM output is the only SLAM you have.

**1. No single-SLAM runs: run Stage 1 directly on the multi-SLAM frame.** Per person, make an MPS root of symlinks, with `slam/` from the multi output and `eye_gaze/` + `hand_tracking/` from that person's `aria_mps single` run:

```bash
R=pipeline_results/<id>; mkdir -p $R/mps
ln -sfn $C/mps_<site>_combined/<n>/slam $R/mps/slam
ln -sfn $C/mps_<recording>_vrs/eye_gaze $R/mps/eye_gaze; ln -sfn $C/mps_<recording>_vrs/hand_tracking $R/mps/hand_tracking
```

Run steps 1, 2, 4, 5 and 6 with `M=$R/mps`. Then `cp $R/stage1/narrative_anchors.json $R/narrative_anchors.world.json`. Skip the per-person geo bake, `bake_anchors` and per-person graphs. Pass the multi `slam/` as both slam dirs to the combine; the fit is then an exact identity (RMSE 0.0). `source_anchor_id` = the index in that person's Stage 3 output.

**2. No GPS fix → pin the site by hand.**
- Check the raw stream to be sure. If every VRS `gps` record has `accuracy` 9998999, lat/lon 0 and empty `raw_data`, the receiver never saw a satellite. MPS can't geo-align that, and rerunning MPS won't help.
- Ask the user for the building's lat/lon. The combine then centres all trajectories there: `--manual-geo LAT,LON[,ALT] [--heading DEG]`.
- The MPS world is gravity-aligned with +Z up, so placement is a translation plus a yaw. `--heading` rotates the site clockwise on the map; 0 = world +X east.
- The trajectory and `combine_params.json` record `geo_source: "manual"`. Re-pinning only needs a rerun of the combine and the graph tagging; the copy to the viewer stays the same.

**3. Dense small rooms break the default Stage 1 clustering.**
- With the default DBSCAN `eps` 0.25 m, gaze on nearby objects chains together. Andrew came out as **2 events**, one of them 245 s long.
- Sweep `--eps` / `--min-samples` offline before Stage 1's Gemini calls. Load the raycast gaze once and call `run_indexing` per setting.
- The lab used `--eps 0.1 --min-samples 5`, giving 47 / 46 / 69 / 192 events with the longest event at 9–28 s.
- Dense rooms also made Stage 1's raycast hold every ray's 1.5 m neighbour list at once (~15 GB for Luis's 9,629 rays). Since 2026-10-28, `get_refined_gaze_points` queries in chunks of 256 rays. The output is bit-identical and peaks at ~2 GB.
- The Stage 3 radii are sub-metre too:

| Person (tag) | Events | Radius | Anchors |
|---|---|---|---|
| Andrew (AI Accessibility) | 47 | 0.25 m | 12 |
| Luis (Digital Fabrication) | 192 | 0.5 m | 22 |
| Harry (Mechanical Engineering) | 46 | 0.5 m | 14 |
| Cara (Industrial Design) | 69 | 0.15 m | 13 |

**4. Graph: the thematic channel dominates in a single-topic room.**
- In one lab, every anchor is about robotics and 3D printing. With `--lam 0.2`, 1,495 of the 1,830 possible pairs became edges.
- The lab used `--lam 2.0 --tau-thematic 0.8`, which gives 219 edges (90 of them cross-person); "spatial" then means the same display (≤ 0.46 m).
- Preview with `--count-only`. No transplant step is needed: the graph is built once, with rationales, on the combined anchors.

**Tags:** `PERSON` is the tag text (here the topic, at the user's request), and the optional 5th `--part` field is the speaker's name. It is stored as `source_speaker` on anchors and graph nodes, `speaker` in `segments`, and a column in `anchor_sources.csv`.

```bash
M=$C/mps_robotics_lab_combined
$P scripts/combine_multislam_recordings.py --out pipeline_results/robotics_lab_combined \
 --part "robotics_ai_accessibility:AI Accessibility:$M/0/slam:$M/0/slam:Andrew" \
 --part "robotics_digital_fabrication:Digital Fabrication:$M/3/slam:$M/3/slam:Luis" \
 --part "robotics_mechanical_engineering:Mechanical Engineering:$M/2/slam:$M/2/slam:Harry" \
 --part "robotics_industrial_design:Industrial Design:$M/1/slam:$M/1/slam:Cara" \
 --manual-geo 37.22990745071064,-80.42457932938132,598.66
```

Parts go in recording order, which comes from the VRS `.json` `start_time`.

**Sanity check:** Andrew's, Harry's and Luis's Braille-handrail anchors landed within 0.72 m of each other, and every anchor is within 1 m of a walked path.

### Older route: `merge_recordings.py`

`scripts/gaze/semantic/merge_recordings.py` (used for Carona) only concatenates viewer folders and tags `source_recording`. It is **wrong for parts baked separately**, because each bake has its own ENU origin. It also leaves the overlapping timestamps and drops `baked` / `enu_origin` from the trajectory. Use `combine_multislam_recordings.py` instead.
