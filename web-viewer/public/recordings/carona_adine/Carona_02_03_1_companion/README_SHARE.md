# Carona 02+03 (+Carona1) — MERGED companion · shared recording bundle

A ready-to-load **web-viewer scenario** for the InTheEyesOf expert-attention
project. This is the *companion* arm: the **companion's (Carona) gaze** in a shared
3D frame, aligned to the **expert's (Adine) speech**, with a third recording
(Carona1) added as extra point-cloud coverage.

`id`: `Carona_02_03_1_companion`
Title: *Carona 02+03(+Carona1) — MERGED companion (later-filter, cross-part edges)*

---

## What's in this folder (~91 MB)

| File | Size | What it is |
|------|------|-----------|
| `pointcloud.ply` | 54 MB | Colored merged point cloud (binary PLY, RGB per vertex), ~3.8 M points |
| `narrative_anchors.json` | 4.1 MB | 466 narrative anchors (gaze×speech intent moments) |
| `semantic_graph.json` | 27 MB | Semantic graph: 466 nodes, 8363 typed edges |
| `trajectory_latlon.json` | 1.9 MB | Device trajectory in lat/lon for the map view |
| `pipeline_params.json` | 470 B | Parameters used to build the graph (provenance) |
| `semantic_graph_components.csv` | 3.6 MB | Connected-component summary of the graph |

### Video clips
Anchors reference per-anchor clips via `clip_rel_path` (e.g.
`cluster_01/event_010_cluster_1.mp4`). The `cluster_*/` video folders are **not
bundled here** — you already have them; place/keep them under this folder so the
relative paths resolve. The scenario loads fine without them (only per-anchor
video playback needs them).

---

## How to register it in the viewer

Drop this folder under `web-viewer/public/recordings/Carona_02_03_1_companion/`
and add this entry to `web-viewer/public/recordings/manifest.json`:

```json
{
  "id": "Carona_02_03_1_companion",
  "title": "Carona 02+03(+Carona1) — MERGED companion (later-filter, cross-part edges)",
  "anchorsFile": "narrative_anchors.json",
  "pointCloudFile": "pointcloud.ply",
  "semanticGraphFile": "semantic_graph.json",
  "trajectoryFile": "trajectory_latlon.json"
}
```

`RecordingConfig` fields: `id`, `title`, `anchorsFile`, `pointCloudFile`,
`semanticGraphFile?`, `trajectoryFile?`. The PLY loader (three-stdlib `PLYLoader`)
auto-detects the per-vertex RGB.

---

## Coordinate frame (important)

Everything is in **one metric world frame** (the `mps_Carona_02_03_multislam_out`
multi-SLAM frame), in meters:
- Anchor positions `gx, gy, gz` and `pointcloud.ply` share this frame — anchors sit
  on the cloud surfaces (gaze hotspots raycast onto the 3D points, not fixed-depth).
- `trajectory_latlon.json` is the same path expressed in geographic lat/lon for the
  2D map.

Carona1's cloud was brought into this frame via a rigid transform recovered from
Carona_03's trajectory (shared across two SLAM runs); junction alignment ≈ 12 cm.
Carona1 contributes **point cloud only** — no gaze/anchors.

---

## Anchor schema (`narrative_anchors.json`, list of 466)

Each anchor = a moment where stable gaze coincides with the expert referencing
something. Key fields:

| Field | Meaning |
|-------|---------|
| `gx, gy, gz` | 3D anchor position (world frame, m), raycast onto the cloud |
| `start_ts, end_ts` | device timestamps (µs); `start_sec`, `duration`, `relative_time` |
| `narrative_title`, `narrative_description` | VLM-summarized intent |
| `objects`, `actions`, `spatial_props` | extracted semantic content |
| `transcript_slice` | the expert (Adine) speech for this anchor |
| `discourse_profile {l1,l2,l3}`, `dominant_discourse`, `intent_strength` | discourse layer mix (l1 perceptual / l2 contextual / l3 aside) and gating strength |
| `emotion_profile` | speech emotion (SER arousal/dominance/valence, f0, …) |
| `member_segments` | source Adine transcript segments folded into this anchor |
| `source_recording` | `Carona_02_companion` (105) or `Carona_03_companion` (361) |
| `cluster_id`, `cluster_ids`, `mean_quality`, `sample_count`, `fallback_ratio` | gaze-cluster provenance + quality |
| `clip_rel_path` | path to the (not-bundled) video clip |

"later-filter / intent-gated": low-intent (l3 aside) anchors are filtered after
synthesis; `intent_strength` reflects the gate.

## Graph schema (`semantic_graph.json`)

`{ metadata, nodes (466, one per anchor), links (8363, typed edges), components }`.
Edges are typed (spatial / referential / thematic) with a convergence-degree weight
(`edge_method: typed_edges_with_convergence_degree`, embedding model `BAAI/bge-m3`,
thresholds in `pipeline_params.json`).

---

## Provenance — how each file was produced

Pipeline stages: MPS multi-SLAM → gaze clustering + raycast → transcript alignment
→ VLM synthesis → multimodal enrichment → intent gating → cross-part graph.

- **`pointcloud.ply`** — MPS semi-dense points (`semidense_points.csv.gz`) from two
  multi-SLAM runs, quality-filtered (`inv_dist_std ≤ 0.005`, `dist_std ≤ 0.05`),
  then **colorized per recording** by projecting into that recording's Aria RGB
  stream (FISHEYE624 model + `closed_loop_trajectory.csv`, exposure-weighted mean).
  Carona1 (from the second multi-SLAM run) is **rigid-aligned** into the canonical
  frame via a transform recovered from Carona_03's shared trajectory (≈47 mm fit,
  ≈12 cm at the junction). Then **per-recording white-balance + luminance levels +
  chroma-match** (so the three parts match in brightness/saturation), merged, and
  voxel-downsampled to ~3.8 M points.
- **`trajectory_latlon.json`** — `closed_loop_trajectory.csv` exported to geographic
  lat/lon (`scripts/export_trajectory_latlon.py`).
- **`narrative_anchors.json`** — companion gaze (`general_eye_gaze.csv`, Carona
  device) DBSCAN-clustered → each hotspot **raycast onto the point cloud** (Open3D
  KDTree, never fixed-depth) → time-aligned with the **expert (Adine) transcript**
  (mapped onto the Carona timeline) → **VLM-summarized** into title/description/
  objects/actions → **enriched** with `discourse_profile` and `emotion_profile`
  pulled from the per-recording **fusion tables** (see below) → **intent-gated**
  (later-filter: low-intent L3 asides removed post-synthesis) → anchors from
  Carona_02 (105) and Carona_03 (361) **merged** with `source_recording` tags.
- **`semantic_graph.json`** — anchors embedded (`BAAI/bge-m3`) → **typed edges**
  (spatial / referential / thematic) with convergence-degree weights; cross-part
  edges allowed so Carona_02↔Carona_03 anchors can link. Thresholds in
  `pipeline_params.json`.
- **`semantic_graph_components.csv`** — connected-component summary of that graph.
- **`pipeline_params.json`** — graph-builder parameters (provenance record).

## Fusion tables (per-segment multimodal — NOT in this bundle)

The multimodal signals were assembled upstream into **per-recording** fusion
tables, **not shipped here** (they live with the sender, in `aria/Carona/`):

- `Carona_02_fusion_m8_enriched.csv` — **529 segments**
- `Carona_03_fusion_m8_enriched.csv` — **980 segments**

Each is one row per transcript segment (`seg_idx`), consolidating: gaze
(yaw/pitch/depth + std), head IMU (accel/gyro), GPS speed + lat/lon, body state,
hand-visibility fractions, discourse (level/label/confidence), prosody (f0, energy,
voiced/pause fractions), and SER emotion (arousal/dominance/valence) — built by
`assemble_fusion.py` (joins all enrichments by `seg_idx`).

**Status:** consolidated *within* each recording (all modalities in one enriched
table), but **Carona_02 and Carona_03 are NOT merged into a single combined fusion
table** — they remain two separate per-recording files. Their signals are, however,
already **embedded in the anchors** here (`emotion_profile`, `discourse_profile`,
`intent_strength`, `member_segments` with `adine_seg_idx`), so the viewer bundle is
self-contained. Request the fusion CSVs only if you need segment-level data.

### Reference (sender-side paths, not shipped)
Location: `aria/Carona/` on the sender's machine. Builder:
`scripts/gaze/semantic/{build_fusion.py, assemble_fusion.py}` (in the repo).

| File | Role |
|------|------|
| `Carona_02_fusion_m8_enriched.csv` | Carona_02 — full enriched fusion (529 segs) ← use this |
| `Carona_03_fusion_m8_enriched.csv` | Carona_03 — full enriched fusion (980 segs) ← use this |
| `Carona_0{2,3}_fusion_m8.csv` | base spine (pre-enrichment) |
| `Carona_0{2,3}_fusion_m8_emo.csv` | prosody + SER emotion only |
| `Carona_0{2,3}_fusion.csv` | older base (288 / 732 segs), superseded by `_m8` |

Naming: `_m8` = current segment set · `_emo` = prosody/emotion · `_snap` = snapshot
· `_enriched` = all enrichments merged by `seg_idx` (the one to use).
The matching expert-side tables are `CaronaAdine{1,2,3}_fusion_m8_enriched.csv`.

Questions → contact the sender.
