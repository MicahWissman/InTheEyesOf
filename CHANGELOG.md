# Changelog

All notable changes to the InTheEyesOf pipeline are documented here.

---

## [v0.5-beta] — 2026-06-10 — Multilingual Transcription, Cross-Device Alignment & Multimodal Fusion

### Added
- **Robust audio extraction** — `vrs_to_audio_direct.py` reads the mic stream directly into a full-length 16 kHz mono WAV. Fixes a truncation bug in `vrs_to_audio.py`, where the `convert_vrs_to_mp4` + down-sample path collapsed a 48-min recording's audio to ~5 min.
- **Multilingual transcription** — `transcribe_wav.py`: faster-whisper (default) and whisperx backends; per-window language detection (`--lang-window`) and a **4-pass code-switch merge** (`--passes`: an auto pass + forced it/es/en, picking the highest Whisper word-probability language per segment) for es/it/en recordings; optional whisperx speaker diarization; emits native variable-length segments (`--segments` CSV) and/or the binned pipeline `.txt`; GPU via `--device cuda`. Tuning: `--vad-threshold` (passes sensitivity), whisperx `--chunk-size` (segment length); the 4-pass merge partitions words per segment by start time so boundary words are not duplicated.
- **Canonical transcript format** — `transcript_format.py`, a single source of truth (multi-line; optional `(lang[, SPEAKER])` tag on the marker line) shared by all transcript generators so the format cannot drift.
- **Mic-channel A/B diagnostic** — `experiments/mic_ab.py` compares mic channels / mixes by Whisper `avg_logprob`, with global-reference normalization to avoid silence-induced hallucination.
- **Cross-device time map** — `fit_device_timemap.py` fits per-recording linear maps from matched-utterance control points (slope ≈ 1 confirms clock sync; per-recording offsets); `apply_device_timemap.py` places one device's transcript on another device's spatial timeline.
- **Multimodal fusion** — `extract_sensors.py` (IMU/GPS/`audio_t0` from a VRS) + `build_fusion.py` (one row per transcript segment: transcript × eye-gaze × head-IMU × GPS+speed × hand-tracking, with `body_state`), reproducing the upstream Adine fusion schema for any recording/device, joined on the device clock (`t_device_ns = audio_t0_ns + seg_seconds·1e9`).
- **Discourse-level classification** — `classify_discourse.py` tags each transcript segment as **L1 concrete** (object-referential — the interpretive-intent target), **L2 contextual** (background/RAG-like scaffolding), or **L3 aside** (jokes/procedural/metalinguistic — noise), via the LLM service batched with local context; writes a `seg_idx`-keyed `<name>_discourse.csv` sidecar. It propagates downstream: `build_fusion --discourse` adds the level per fusion row; `apply_device_timemap` carries it onto the time-mapped `fromAdine` segments; and `enrich_anchors_discourse.py` rolls the segments in each anchor's gaze window into a `discourse_profile {l1,l2,l3}`, `dominant_discourse`, and `intent_strength` (= frac L1) — the convergence model's referential gate, separating interpretive intent from contextual/aside speech with **no extra VLM calls**.
- **Recording merge** — `merge_recordings.py` merges world-frame-sharing recordings (the Carona multi-SLAM halves) into one: concatenated anchors (tagged `source_recording`), continuous trajectory, stacked point cloud. The convergence graph is rebuilt over the merged anchors so **cross-part edges** form (Carona_02↔03: **2,448 / 8,363 = 29%**). Within-part rationales transplant from the parts' graphs (`transplant_rationales.py`, matched by anchor description-pair — **948 recovered** for the later-filter merge); only strong cross-part edges (degree ≥2 + referential — **12**) need fresh computation. So a full merged graph's strong-edge rationales cost ~**12 VLM calls** instead of thousands.
- **Fusion assembly** — `assemble_fusion.py` composes all per-segment enrichments into one master table: it left-joins each `--add` CSV's *new* columns onto the base fusion by `seg_idx` (works whether the add is a full augmented copy — `_snap.csv`, `_emo.csv` — or a thin sidecar — `_discourse.csv`). The integration point that keeps discourse + snapshot + prosody/emotion in a single `_enriched.csv` instead of forking separate files.
- **Per-segment speech emotion + prosody** — `extract_prosody_emotion.py`: **Layer A** dimensional SER (`audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim` → `ser_arousal/dominance/valence`, language-agnostic) + **Layer B** interpretable prosody via librosa (`f0_mean/std/range_hz`, `energy_mean/std`, `voiced_frac`, `pause_frac`; `--egemaps` also writes the full openSMILE eGeMAPSv02 sidecar). Slices the WAV by each segment, joins the fusion on `seg_idx`, runs `--device {mps,cuda,cpu}`, and is **fully local** (no VLM service — immune to connection blips). Needs `librosa` (+ `opensmile` for `--egemaps`).
- **Per-segment snapshots** — `extract_snapshots.py` pulls **`--frames` candidate `camera-rgb` frames per transcript segment** (default 3: before/center/after — evenly-spaced interior timestamps, avoiding boundary transition frames), with an optional mean-gaze overlay, uprighted (`np.rot90 k=3`) and downscaled, written `seg_<idx>_<f>.jpg` (or `seg_<idx>.jpg` for `--frames 1`). With `--update-csv` it adds `snapshot_path` (the center pick, a sensible default) + `snapshot_candidates` (all frames) keyed by `seg_idx`, so the best frame per segment can be chosen. Reuses the fusion device-clock anchors (`t_*_device_ns`, same domain as RGB); primary use is the expert (Adine) egocentric view.
- **Intent-gated convergence + golden-set shortlist** — `semantic_network_builder` now gates the **referential** channel by `√(intent_i·intent_j)` (default on; `--no-intent-gate` to disable), so an object-overlap edge counts as referential convergence only when both anchors were genuinely object-referential — on Carona_02 this cut spurious referential edges **93 → 14** while total edges dropped only ~4% (it demotes convergence degree rather than deleting edges). `golden_candidates.py` ranks anchors by `intent_strength` into **candidate / low_intent / aside / silence** tiers and emits a CSV (highest-yield first, with a blank `human_intent` column) for human intent-labeling; silence/aside anchors are tagged, not dropped, so they remain the salience (Model-1) baseline.

### Changed
- **`vrs_to_transcript.py`** now emits the canonical multi-line format via `transcript_format` (its old single-line output was silently dropped by the transcript parser).
- **Viewer edge strictness controls** — a toolbar panel filters which edges are shown/highlighted **live** (no graph rebuild): a **convergence-degree** selector (`1+ / 2+ / 3` — i.e. how many channels must agree), a **min-weight** slider, and a **"referential only"** toggle; the legend shows the visible/total edge count. Lets you tighten to the strong multi-channel-convergence edges (deg ≥ 2 is ~15–26% of edges; the rest are weak single-channel, mostly thematic) and compare families at any strictness.
- **Viewer edge highlighting + legend** — the convergence graph now renders **referential** edges (the channel that discriminates gate-after from filter-before) in **magenta**, brighter and wider, against the green spatial/thematic web, with a corner legend. Previously all edges were one green, so the referential difference (e.g. 14 vs 150 edges) was invisible.
- **Viewer controls help + stable orbit** — a bottom-right **`?` info popover** (hover or click) describes every control (point-cloud colour/gradient, size, alpha, edge degree, min-weight, referential-only). The camera now fits the content **only on recording load** — adjusting any slider/filter no longer re-fits and jolts the orbit (dropped drei `<Bounds>` `observe`; added a `FitOnLoad` keyed on the recording). Tilt limit relaxed (`maxPolarAngle` 0.5π → 0.62π) so the camera can dip a bit below the horizon.
- **Viewer grounded orbit + spatial point-cloud gradient** — the 3D scene is rotated so **altitude (data Z) is up** (the ground lies in the XZ plane) and the orbit is a natural **turntable** (`maxPolarAngle` limits the tilt) instead of free 3D tumbling. The point cloud also gets an optional **spatial color gradient** (default on, toggle): earthy↔green↔pinkish across N–S and E–W (Lugano-area palette — north/east earthy, centre green, west pinkish stone), shaded by altitude (low = dark, high = light).
- **Viewer landing-page scroll** — the recording picker (`.recording-list`) now scrolls inside a height-capped `.selector-card` (`max-height: 85vh`), so a long list of scenarios no longer overflows the window off-screen.
- **Viewer auto-fit** — the 3D narrative viewer wraps the scene in drei `<Bounds fit clip observe>`, so a recording whose world frame is far from the origin (e.g. the multi-SLAM Carona frame) opens **centered** instead of off-screen. The previous fixed camera target only framed origin-centered frames like Irchel.
- **Cross-device time-map scripts are config/suffix-driven** — `fit_device_timemap.py --config` (control points as JSON) and `apply_device_timemap.py --suffix` (transcript version, e.g. `m8`) allow re-fitting for new transcript versions without code edits; `fit_device_timemap.py --fixed-slope` forces slope = 1 with a robust median offset (for synced clocks / sparse, noisy control points).

### Fixed
- **`load_transcript` (spatial_transcript_summarizer.py)** now robustly parses BOTH single-line and multi-line transcripts — it captures same-line text after the marker and strips the optional `(lang)`/speaker tag — matching its docstring.
- **Transient VLM-blip resilience** — `narrative_synthesizer` and `semantic_network_builder` now wrap the VLM service POST in a retry/backoff (4 attempts), so a brief DNS/timeout hiccup no longer poisons a whole stage with `Connection Error` placeholders / empty objects. `repair_rationales.py` is an idempotent, re-runnable companion that regenerates **only** the failed rationales in a graph (few quick retries per edge + a consecutive-failure circuit breaker) — for recovering viewer-readiness after a connection drop without redoing the good ones. `--min-degree`/`--referential-only` target just the **strong** edges (e.g. degree ≥2 + referential — a few hundred) when generating rationales for a whole dense graph would be too many.

### Fixed (follow-up to the Performance work)
- **`process_events` cluster-id crash** — the column-selective trajectory read makes `merged_df` all-numeric, so `df.iterrows()` upcasts the int `cluster_id`/`tracking_timestamp_us` to float, breaking `f"cluster_{cluster_id:02d}"`. Cast both back to int explicitly (the old full read masked this by keeping the string `graph_uid` column).

### Performance
- **Faster Stage-1 trajectory/gaze loading** — `load_data` now reads only the ~8 columns it uses, with a faster parser (pyarrow CSV, with an optional `.parquet` sibling), falling back to pandas. **~12× faster** on a 976 MB multi-SLAM `closed_loop_trajectory.csv` (4.1 s → 0.3 s) and ~4× on a 257 MB one; output is numerically identical (validated on yaw/pitch/pos/quat). `csv_to_parquet.py` converts a recording's huge CSV to a Parquet sibling once for further reuse (the loader auto-detects it).
- **Faster point-cloud loading** — the semidense `.csv.gz` is now read column-selectively via pyarrow (**~2.2×**, 10.8 s → 5.0 s; identical filtered set). Removed the `read_global_point_cloud` attempt: that binary API returns millions of Python objects whose per-point extraction is *slower* than the vectorized CSV path (and its import was failing anyway because `filter_points_from_confidence` moved to `mps.utils`).
- **Vectorized raycasting** — `get_refined_gaze_points` now does one batched, multithreaded `cKDTree.query_ball_point` instead of a per-ray open3d query loop; output is identical (validated). Modest (~1.3×) — raycasting was never the bottleneck (~1–3 s); the load fixes above were the real wins.

---

## [v0.4-beta] — 2026-06-05 — Visual-Grounding Pilot, Channel Diagnostics, Multi-Site Recordings

### Added
- **Visual-grounding pilot** (`scripts/gaze/semantic/experiments/`) — two-stage gaze→object grounding that tests whether the object at the gaze point is an *independent* signal from the transcript-derived objects:
  - `extract_gaze_crops.py` (aria_tools env) — calibrated fisheye gaze→pixel reprojection via `get_gaze_vector_reprojection` at the expert's measured fixation depth, saving foveal RGB crops, marked previews, and a manifest. Replaces the legacy pinhole approximation; correctly drops gaze samples outside the RGB FOV.
  - `dino_ground.py` (base env) — zero-shot Grounding DINO on the crops with **symmetric** bge-m3 canonicalization of both visual and transcript objects to one controlled vocabulary; reports Jaccard overlap and gaze↔speech coupling.
- **Referential-channel diagnostic** (`experiments/referential_diagnostic.py`) — quantifies the referential channel's distribution, its redundancy with the thematic channel, and the count of "referential-only" edges, across exact / soft / IDF object-matching variants.
- **Multi-site recordings** — Steger Center 1 (Riva San Vitale) and Irchel Park 30 added with paired guided/storytelling and enriched/object-inventory scripts: `StegerCenter1_guided1`, `StegerCenter1_enriched2`, `Irchel_30_guided1`, `Irchel_30_enriched2`. Registered in the web-viewer manifest with anchors, semantic graph, and lat/lon trajectory.

### Changed
- **Ablation study migrated to typed-edge parameters** — `ablation_study.py` now sweeps `tau_spatial × tau_referential × tau_thematic × lam` (336 combos), the actual edge-controlling parameters of the typed-edge system, instead of the legacy fused-weight grids.

### Research findings
- **Referential channel is redundant.** The ablation showed only `tau_thematic` materially changes edge counts. The diagnostic traced this to the object channel being near-zero under exact string matching; even after soft-matching repair it adds ~0 edges beyond the thematic channel (corr ≈ 0.55), because `objects` and `narrative_description` are generated from the same transcript. A knowledge graph over text-derived objects would inherit this redundancy.
- **Vision largely agrees with speech.** With calibrated projection, ~58% of foveated objects (Steger) are already named in the transcript; the visual channel adds only modest, partly-noisy new content. Vision's defensible value is grounding/verification (object at gaze, with box + depth), not vocabulary expansion.
- **Guided narration couples ~2× more tightly with gaze than the enriched inventory.** Paired comparison (identical gaze crops, swapped transcript objects) replicated on both sites: Steger guided 50% vs enriched 25%; Irchel guided 37.5% vs enriched 18.8%. Moment-by-moment narration references the live fixation; comprehensive inventories do not.

---

## [v0.3-beta] — 2026-05-26 — Semantic Pipeline Hardening, Typed Edges, Multi-Run Deployments

### Added
- **Pipeline provenance logging** — `run_narrative_pipeline.py` now writes `pipeline_params.json` with: per-run event/anchor/edge/node counts, mean quality and fallback ratio, point-cloud size, embedding model name, graph builder parameters (alpha, beta, gamma, lam, threshold), and installed package versions (sentence-transformers, open3d, sklearn, scipy, numpy). Enables reproducibility across runs.
- **Per-event quality-tier distribution** — each event in `semantic_results.json` now carries `quality_tiers` (strong/weak/uncertain/fallback sample counts); `pipeline_params.json` aggregates an overall tier histogram.
- **Independent spatial decay parameter** — `semantic_network_builder.py` now accepts `--lam` (decay rate in 1/m) separately from `--gamma` (spatial weight). The spatial channel is `P = exp(-lam*d)`, weighted by `gamma`. Fixes the prior bug where gamma doubled as both weight and decay.
- **Typed edges with convergence degree** — edges are now independently thresholded per channel (spatial, referential, thematic). Each edge carries a `types` list and `convergence_degree` (0–3) indicating how many channels agree. Deprecated: the old fused `weight` field is retained for viewer compatibility.
- **Per-channel threshold tuning** — `--tau-spatial`, `--tau-referential`, `--tau-thematic` flags let you set individual channel thresholds independently.
- **Full pairwise components** — all `N*(N-1)/2` pairwise evaluations are always emitted: in `graph["components"]` (JSON) and a `_components.csv` file. Each node carries `narrative_description` + `objects` for self-contained review.
- **Ablation study** — `ablation_study.py` sweeps alpha, beta, gamma, lam, threshold grids (576 combos); `plot_ablation.py` generates 6-panel overview (with lam sweep), alpha×threshold heatmaps, parameter-importance bars, and target-contour plots.
- **Edge-count-only mode** — `semantic_network_builder.py --count-only` exits with `EDGE_COUNT:<n>` without VLM calls.
- **vrs_to_audio.py / vrs_to_rgb.py** — extract expert audio clips and synchronized RGB frames from VRS recordings.
- **Web-viewer point-cloud controls** — color picker, size slider, and opacity slider in the title bar; applied to both 3D and Top-Down views.
- **Multi-run recordings** — manifest updated with Irchel_30 enriched v2, v3, v3.5, v3.6 (balanced graph), and v4.0 (semantic-focused: 49 anchors, 57 edges).

### Changed
- **emoji cleanup** — `semantic_network_builder.py` uses plain-text log messages (no emojis).
- **docstring update** — `semantic_network_builder.py` builder class docstring updated to reflect bge-m3 and typed-edge logic (MiniLM references removed).
- **Web-viewer manifest** — added semantic graph and trajectory file paths for all enriched runs.
- **Graph metadata** — now records `edge_method: "typed_edges_with_convergence_degree"`, `tau_*` thresholds, `edges_by_degree`, and `total_pairs_evaluated`.
- **ABORTED: `semantic_network_builder.py` logic** — the fused weight formula `W = alpha*S + beta*T + gamma*P` has been replaced by independent per-channel thresholds with convergence degree counting. The old formula is no longer used.

### Fixed
- **gamma/lam conflation** — prior to this version, gamma served double-duty as both the spatial weight and the distance decay rate. Now lam controls decay and gamma controls weight independently.
- **Docstring "three tiers" → "four tiers"** — `get_refined_gaze_points()` docstring corrected to match the actual four-tier quality system.
- **MiniLM references removed** — all stale MiniLM-L6-v2 references updated to BAAI/bge-m3 (code docstring and CHANGELOG).

---

## [v0.2] — 2026-05-22 — Stage 1 Fixes: Sparse Point Cloud Handling

### Added
- **Tiered raycasting quality** — gaze points are scored with quality flags:
  - `1.0` STRONG: perpendicular distance to surface < 0.5m
  - `0.5` WEAK: 0.5m–1.0m perpendicular
  - `0.25` UNCERTAIN: 1.0m–1.5m perpendicular
  - `0.0` FALLBACK: no surface within 1.5m, uses 2.0m depth
- **Per-event quality metadata** — `semantic_results.json` now includes `mean_quality`, `sample_count`, `fallback_ratio` per event
- **Tag overlap edges** — semantic graph now uses Jaccard similarity of VLM-extracted object tags (parameter `--beta`)
- **Auto MPS detection** — orchestrator auto-detects MPS directories from VRS path (`_find_mps_for_vrs()`)
- **vrs_to_audio.py / vrs_to_rgb.py** — new scripts for audio extraction and RGB frame export
- **Sparse cloud handling section** in README with tuning examples

### Changed
- DBSCAN `min_samples` default: 30 → 10 (better for sparse/uneven point clouds)
- Low-quality points (quality < 0.5) pushed far from clustering region
- `--cluster-eps` / `--cluster-min-samples` CLI args propagated through orchestrator
- `--group_radius` default remains 2.0m (merge nearby hotspots before VLM synthesis)

### Fixed
- **pandas `.values` read-only assignment** — replaced with direct column assignment (`merged['col'] = values`)
- **_find_mps_for_vrs() relative path bug** — added `os.path.abspath()` for correct path resolution
- **Tuple unpacking bug** — `get_refined_gaze_points()` now correctly returns `(points, quality_flags)` tuple

### Comparison: New vs Old Parameters (Irchel_30 recording)

| Metric | New (min_samples=10) | Old (min_samples=30) |
|--------|----------------------|----------------------|
| Gaze events | 74 | 21 |
| Unique clusters | 58 | 2 |
| Mean quality | 0.73 | 0.22 |
| Fallback ratio | 0.05 | 0.26 |
| Anchors with objects | 63 | 17 |
| Graph edges | 7 | 0 |

---

## [v0.1.5] — 2026-03-30 — Conversational Infrastructure

### Added
- `scripts/bake_geo_aligned_recording.py` — offline ENU alignment pipeline
- `scripts/generate_anchor_audio.py` — ElevenLabs TTS for anchor narratives
- `web-viewer/src/contexts/AIContext.tsx` — AI conversation state management
- `web-viewer/src/contexts/AudioContext.tsx` — master audio enable/disable toggle with localStorage persistence
- `web-viewer/src/hooks/useDampedDeviceOrientation.ts` — damped AR-sense camera mode
- `web-viewer/src/components/ConversationPanel.tsx` — real-time Gemini conversation UI
- `offline TTS generation script` — offline ElevenLabs audio generation

### Changed
- **Narrative anchors schema** — added `audioUrl` and `audioCaption` fields
- **Web-viewer architecture** — introduced React contexts (AI, Audio) for state management
- **AR features** — proximity-based anchor states for AR-style discovery feedback
- Follow Visitor mode extended to top-down point cloud view
- Map zoom extended to 22 (overzoom OSM), anchor markers scale dynamically

---

## [v0.1.4] — 2026-03-28 — Immersive 3D & GPS Integration

### Added
- **Immersive 3D mode** — compass cone, GPS recentering, north-aligned point cloud
- **Geo-registration utility** — `scripts/export_trajectory_latlon.py` converts trajectory to lat/lon
- **2D map view** — `TopDownMap.tsx` component with overzoom OSM tiles
- **Top-down point cloud view** — `TopDownPointCloud.tsx` for walking-through-site experience
- **Server doc** — RPi 5 server setup, jetson setup, HTTPS enable script
- **GPS relay** — WebSocket bridge shares Pixel GPS to tablets without GPS
- **Semantic connections** — `SemanticConnections.tsx` renders graph edges in web-viewer
- **Semantic network builder** — `semantic_network_builder.py` builds semantic-spatial graph from narrative anchors
- **Follow Visitor mode** — 3D view for walking-through-site experience
- **Damped AR-sense camera mode** — device orientation with damping

### Changed
- Major web-viewer refactor — `NarrativeViewer.tsx` expanded to 492 lines
- Sidebar restructured for new immersive/2D/AR modes
- `semantic_network_builder.py` — convergence graph engine with semantic similarity + spatial proximity weighting
- **narrative_synthesizer.py** — expanded from 95 to 109 lines with structured VLM output

### Removed
- `scripts/generate_anchor_audio.py` — removed in favor of inline TTS infrastructure

---

## [v0.1.3] — 2026-03-28 — Pipeline Infrastructure

### Added
- **Semantic network graph builder** (`semantic_network_builder.py`) — builds edges from:
  - Semantic similarity (cosine of BAAI/bge-m3 multilingual embeddings)
  - Spatial proximity (exponential decay of 3D distance)
  - Convergence weight: `alpha * S + beta * P`
- **Web-viewer README** — `web-viewer/README.md` with setup instructions
- **CLAUDE.md** — project context, research mission, three relevance models
- **X-Ray viewer** — spatial alignment/inspection tool with PLY loading
- **Raspberry Pi 5 server** — network hosting for InTheEyesOf network
- **Jetson server setup** — `setup_rpi5_server.sh`

### Changed
- **Web-viewer** — major refactor: semantic graph wiring, semantic connections rendering, sidebar restructured
- **README.md** — moved documentation to `documentation/`, cleaned up structure

### Fixed
- **Web-viewer manifest.json** — updated recording paths

---

## [v0.1.2] — 2026-03-28 — Repository Organization

### Changed
- **File reorganization** — moved old/unused scripts to `outdated/`:
  - `conversion/`, `slam/`, `ingestion/`, `experimental/`, `viz/` scripts
  - Old documentation files consolidated
- **Directory structure** — `scripts/gaze/hotspots/` for active gaze analysis
- **Git submodules** — added for x-ray-viewer with recorded data
- **web-viewer** — initialized React/Three.js project with Vite, ESLint, TypeScript
- **Web-viewer data** — added pre-generated narrative anchors, point clouds for gilbert-test-2/3

### Added
- **web-viewer/README.md** — project setup docs
- **x-ray-viewer** — spatial alignment tool with alignment controls, bottom sheet
- **Bake geo-aligned recording** pipeline for offline ENU alignment

---

## [v0.1.1] — 2026-03-27 — Pipeline Foundation

### Added
- **Core pipeline scripts** (`scripts/gaze/semantic/`):
  - `spatial_transcript_summarizer.py` — clusters gaze hotspots, aligns with transcript
  - `narrative_synthesizer.py` — AI VLM synthesis for narrative anchors
  - `run_narrative_pipeline.py` — orchestrator for all pipeline stages
  - `hand_interaction_extractor.py` — hand tracking analysis
- **VRS processing** (`scripts/vrs_processing/`):
  - `vrs_to_transcript.py` — Whisper transcription
  - `vrs_to_kimera.py` — UI for selecting VRS/MPS paths
  - `split_vrs_chunks.py` — VRS file splitting
- **Point cloud utilities** — `clean_mps_points.py`, `process_mps_for_cloudcompare.py`
- **SLAM research** — `slam_algorithm.py` (Python implementation of SLAM algorithm)
- **Gaze analysis** — `align_gaze_to_pc.py`, `gaze_heatmap.py`, `extract_hotspot_frames.py`
- **Google Cloud bucket** — `upload_vrs.py`, `GCS_USAGE_GUIDE.md`
- **secrets.json** — credentials management (untracked in git)
- **ARIAvrsToMp4.py** — video extraction from VRS files
- **xyzTest.py** — trajectory coordinate transformation testing

### Changed
- **Conda environment** — `aria_tools_conda.yml` for dependency management
- **Git structure** — moved from monolithic to modular script layout
- **README.md** — comprehensive pipeline documentation

---

## [v0.1.0] — 2026-02-27 — Initial Repository

### Added
- **Project Aria SDK baseline** — Dr. Borunda's sample code for working with Project Aria
- **ARIAvrsToMp4.py** — initial VRS to MP4 conversion
- **closedLoopXYZParser.py** — trajectory CSV parsing
- **parse csv for rhino.py** — point cloud parsing for Rhino 3D
- **process_aria_walk.py** — walk processing utility
- **gitignore** — basic filtering configuration

---

## Comparison: New vs Old Parameters (Irchel_30 recording)

| Metric | New (min_samples=10) | Old (min_samples=30) |
|--------|----------------------|----------------------|
| Gaze events | 74 | 21 |
| Unique clusters | 58 | 2 |
| Mean quality | 0.73 | 0.22 |
| Fallback ratio | 0.05 | 0.26 |
| Anchors with objects | 63 | 17 |
| Graph edges | 7 | 0 |

The old parameters collapsed into only 2 clusters with 26% fallback, producing 0 graph edges. The new parameters find 58 well-separated clusters (quality 0.73) yielding 7 meaningful semantic-spatial edges.

---

## Known Issues
- `hotspot_gold_standard.py` requires `open3d` (not installed in base conda env)
- `numexpr 2.10.1` vs required `2.10.2` (non-blocking warning)
