[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21776985.svg)](https://doi.org/10.5281/zenodo.21776985)
# In The Eyes Of: Expert Intent Pipeline

In The Eyes Of is a research-driven infrastructure designed to operationalize expert visual attention using Meta Project Aria egocentric data. This pipeline transforms raw .vrs recordings and Machine Perception Services (MPS) outputs into semantically grounded 3D narratives and interactive visualizations.

---

## Research Mission

The primary goal is to identify moments of true interpretive intent rather than simple gaze duration. The pipeline supports the comparison of three relevance models:

1. Dwell-Time Baseline: Simple fixation duration (Gaze Salience).
2. Gaze-Speech Synchronization (DTW): Temporal alignment of gaze and voice.
3. Convergence Model: A semantically grounded pipeline combining stable gaze, transcript cues, 3D raycasting, and vision-language verification.

> For the reasoning behind *why* points are selected, filtered, and connected the way they
> are — the intent-vs-salience design, the Snap Rule, the typed-edge convergence model, and
> what the diagnostics have empirically shown — see [`documentation/RATIONALE.md`](documentation/RATIONALE.md).

---

## Prerequisites

### 1. Environment Setup

The pipeline requires a Conda environment with Project Aria tools and AI synthesis libraries.

```bash
# Create and activate the environment
conda env create -f aria_tools_conda.yml
conda activate aria_tools
```

### 2. VRS Tools Installation

To interact with .vrs files directly (inspecting records, checking integrity), it is recommended to build the VRS CLI from source.

```bash
# System dependencies (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y cmake git ninja-build ccache libgtest-dev libfmt-dev \
libturbojpeg-dev libpng-dev liblz4-dev libzstd-dev libxxhash-dev \
libboost-system-dev libboost-filesystem-dev libboost-thread-dev \
libboost-chrono-dev libboost-date-time-dev

# Build VRS
git clone https://github.com/facebookresearch/vrs.git
cd vrs
mkdir build && cd build
cmake -S .. -B . -G Ninja -DCMAKE_INSTALL_PREFIX=$HOME/vrs_install
ninja install

# Add to PATH
export PATH="$HOME/vrs_install/bin:$PATH"
```

### 3. Node.js for Web Viewers

The visualization tools require Node.js (version 18 or higher) and npm.

```bash
# Verify installation
node --version
npm --version
```

### 4. Authentication and Secrets

Access to the Gemini VLM for narrative synthesis requires Google Cloud authentication and a local secrets file.

```bash
# GCP Authentication
gcloud auth application-default login
```

Create a `secrets.json` file in the project root:
```json
{
  "SERVICE_URL": "your_vlm_endpoint",
  "RESEARCH_PASSWORD": "your_password"
}
```

---

## The Spatial-Narrative Pipeline

The following steps outline the process from a raw recording to a 3D visualization.

### Stage 1: Audio Extraction and Transcription
Extract audio from the .vrs file and generate a timestamped transcript using Whisper.
```bash
python scripts/gaze/semantic/vrs_to_audio.py \
    --vrs /path/to/recording.vrs \
    --output /path/to/recording_audio.wav
```

Extract RGB frames:
```bash
python scripts/gaze/semantic/vrs_to_rgb.py \
    --vrs /path/to/recording.vrs \
    --output /path/to/frames/
```

Whisper transcription:
```bash
python scripts/gaze/semantic/vrs_to_transcript.py \
    --vrs /path/to/recording.vrs \
    --output /path/to/recording_transcript.txt \
    --interval 10.0
```

### Stage 2: Spatial Processing (MPS)
Process your .vrs file through Meta's MPS to generate:
- `slam/semidense_points.csv.gz` — high-quality point cloud for raycasting
- `slam/closed_loop_trajectory.csv` — camera trajectory
- `eye_gaze/general_eye_gaze.csv` — gaze directions

The pipeline auto-detects MPS output next to the `.vrs` file — no need to specify `--mps` manually.

### Stage 3: Narrative Synthesis (The Orchestrator)
Synchronize gaze hotspots, transcript intent, and hand interactions. This script calls the Gemini VLM to synthesize Narrative Anchors.

```bash
python scripts/gaze/semantic/run_narrative_pipeline.py \
    --vrs path/to/recording.vrs \
    --transcript path/to/recording_transcript.txt \
    --output ./pipeline_results \
    --cluster-eps 0.25 \
    --cluster-min-samples 10
```

**Key parameters:**

| Parameter | Default | Description |
|---|---|---|
| `--cluster-eps` | `0.25` | DBSCAN epsilon (meters) for gaze clustering. Lower for dense areas, higher for sparse point clouds |
| `--cluster-min-samples` | `10` | Minimum DBSCAN samples. Lower for sparse/uneven point clouds (e.g., vegetation) |
| `--group_radius` | `2.0` | Merge nearby hotspots within this 3D distance (meters) before VLM synthesis |
| `--skip_synthesis` | — | Skip the VLM step to generate intermediate results only |
| `--no-rationale` | — | Skip AI rationale generation in graph building (saves time/cost) |

**Quality tiers for gaze targets:**

The pipeline assigns a quality score to each gaze point based on raycasting confidence:

| Tier | Quality | Criteria | Usage |
|---|---|---|---|
| STRONG | `1.0` | Perpendicular distance to surface < 0.5m | Confident surface intersection |
| WEAK | `0.5` | Perpendicular distance 0.5m–1.0m | Sparse but plausible hit |
| UNCERTAIN | `0.25` | Perpendicular distance 1.0m–1.5m | Weak hit, treat with caution |
| FALLBACK | `0.0` | No surface found within 1.5m, uses 2.0m depth | Unreliable, filtered from clustering |

Each event in `semantic_results.json` includes: `mean_quality`, `sample_count`, `fallback_ratio`.

Key outputs: `narrative_anchors.json` and event video clips.

### Stage 4: Semantic Graphing
Build a relational network of narrative anchors based on thematic links, tag overlap, and spatial proximity.

```bash
python scripts/gaze/semantic/semantic_network_builder.py \
    --anchors ./pipeline_results/narrative_anchors.json \
    --output ./pipeline_results/semantic_graph.json \
    --threshold 0.6 \
    --alpha 0.5 --beta 0.5 --gamma 0.5
```

**Edge weight formula:** `W = alpha * semantic_sim + beta * tag_overlap + gamma * spatial_proximity`

| Parameter | Default | Description |
|---|---|---|
| `--alpha` | `0.5` | Weight for semantic (embedding cosine similarity) |
| `--beta` | `0.5` | Weight for tag overlap (Jaccard similarity on VLM-extracted object tags) |
| `--model` | `BAAI/bge-m3` | Embedding model (multi-lingual, 38 languages, 568M params) |
| `--gamma` | `0.5` | Weight for spatial proximity (exponential decay of 3D distance) |
| `--threshold` | `0.6` | Minimum edge weight to include an edge |
| `--no-rationale` | — | Skip Gemini rationale generation per edge |

The `--beta` (tag overlap) parameter enables Jaccard similarity between VLM-extracted object lists, which is especially useful for anchoring edges when point clouds are sparse.

### Stage 5: Trajectory and Heatmap Export
Prepare the spatial foundation for the web viewer.

```bash
# Export geo-registered trajectory
python scripts/export_trajectory_latlon.py \
    path/to/mps_results/slam \
    ./pipeline_results/trajectory_latlon.json

# Generate gaze-reactive point cloud
python scripts/gaze/hotspots/hotspot_gold_standard.py \
    --mps_root path/to/mps_results_folder \
    --output_ply ./pipeline_results/pointcloud.ply \
    --k 5
```

---

## Web Viewer Integration

To visualize a recording, assets must be mapped into the web-viewer public directory.

1. Create a recording directory:
   ```bash
   mkdir -p web-viewer/public/recordings/recording-id
   ```

2. Copy pipeline results:
   ```bash
   cp ./pipeline_results/narrative_anchors.json web-viewer/public/recordings/recording-id/
   cp ./pipeline_results/semantic_graph.json web-viewer/public/recordings/recording-id/
   cp ./pipeline_results/trajectory_latlon.json web-viewer/public/recordings/recording-id/
   cp ./pipeline_results/pointcloud.ply web-viewer/public/recordings/recording-id/
   ```

3. Update `web-viewer/public/recordings/manifest.json`:
   ```json
   {
     "recordings": [
       {
         "id": "recording-id",
         "title": "Display Title",
         "anchorsFile": "narrative_anchors.json",
         "pointCloudFile": "pointcloud.ply",
         "semanticGraphFile": "semantic_graph.json",
         "trajectoryFile": "trajectory_latlon.json"
       }
     ]
   }
   ```
   Note: Add the new recording object to the existing `recordings` array.

4. Launch the viewer:
   ```bash
   cd web-viewer
   npm install
   npm run dev
   ```

---

## Sparse Point Cloud Handling

Vegetation and textureless surfaces produce sparse, uneven point clouds. The pipeline adapts via:

1. **Tiered raycasting** — quality scores distinguish confident surface hits from fallback projections (see quality tiers table above).
2. **Adaptive clustering** — `--cluster-min-samples 10` (vs. the legacy 30) prevents over-filtering in sparse areas. Low-quality points (quality < 0.5) are pushed far away before DBSCAN.
3. **Tag overlap** — `--beta` weight on Jaccard similarity of VLM object tags provides semantic edges even when spatial data is unreliable.
4. **Auto MPS detection** — the orchestrator searches for `mps_<recording_name>_vrs` directories automatically.

**Tuning for sparse areas:**

```bash
# For heavy vegetation / sparse point clouds:
python scripts/gaze/semantic/run_narrative_pipeline.py \
    --vrs path/to/recording.vrs \
    --transcript path/to/transcript.txt \
    --output ./pipeline_results \
    --cluster-eps 0.4 \
    --cluster-min-samples 10 \
    --group_radius 3.0
```

For dense, well-structured areas:

```bash
python scripts/gaze/semantic/run_narrative_pipeline.py \
    --vrs path/to/recording.vrs \
    --transcript path/to/transcript.txt \
    --output ./pipeline_results \
    --cluster-eps 0.25 \
    --cluster-min-samples 10 \
    --group_radius 1.0
```

---

## Setting up AI Conversation

The web viewer includes an optional AI conversation feature that lets visitors ask questions about each anchor. Responses are strictly bounded to the expert's recorded statements — the model cannot invent or extrapolate beyond the provided corpus.

> **Safety warning:** The AI toggle (`Ask` button) must be **OFF** unless you are actively testing or running the production experience. Even with the daily cost cap enforced, accidentally leaving AI enabled during development can accumulate small charges across repeated page loads and proximity triggers. Default is `false`; leave it that way until the Pi is deployed at Carona.

---

### 1. Obtain a Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey) and sign in with a Google account.
2. Click **Create API key** and copy the key.
3. Keep it private — treat it like a password.

---

### 2. Add the key to the Pi (never anywhere else)

The key lives **only** in a `.env` file on the Pi, inside the backend service directory. It must never be committed, printed in logs, or passed to the frontend.

```bash
# On the Pi:
cd backend/conversation-service/
cp .env.example .env
nano .env
# Paste your key as: GEMINI_API_KEY=your_key_here
# Save and exit (Ctrl+O, Ctrl+X)
```

The `.env` file is listed in `.gitignore` and will never be tracked by git. Do not paste the key into this repository or into any chat conversation.

---

### 3. Start the backend service

```bash
# Install dependencies (first time only)
cd backend/conversation-service/
npm install

# Start (foreground, useful for testing)
npm start

# Or run persistently with pm2
npm install -g pm2
pm2 start server.js --name conversation-service
pm2 save
pm2 startup   # follow the printed command to enable auto-start on reboot
```

The service binds to `127.0.0.1:3001` (loopback only). Nginx proxies `/api/*` to it — see `backend/conversation-service/nginx.conf.example` for the exact snippet to add to your site config.

Verify the service is running:
```bash
curl http://127.0.0.1:3001/api/health
# Expected: {"ok":true,"aiConfigured":true,"dailyCostUSD":"0.0000","capUSD":1,"overCap":false}
```

---

### 4. Configure the daily cost cap

The default cap is **$1.00 USD per day**. Once reached, the service returns HTTP 429 and the UI shows a friendly message. No further charges are incurred until midnight UTC resets the counter.

To change the cap, add to `.env`:
```
DAILY_COST_CAP_USD=2.00
```

Current Gemini 2.0 Flash pricing (as of 2025): $0.075 / 1M input tokens, $0.30 / 1M output tokens. At the default settings (200 output tokens, ~800 input tokens per turn), one full 5-exchange session costs roughly **$0.0004**. The $1.00 daily cap allows approximately 2,500 visitor exchanges.

---

### 5. Populate corpus files after the Carona recording session

Each anchor needs a plain-text corpus file containing the expert's recorded statements at that location. The AI is strictly bounded to this content.

**After the Carona field session:**

1. Run the narrative pipeline (Stages 1–3) to produce `narrative_anchors.json`.
2. For each anchor, create a corpus file at:
   ```
   web-viewer/public/recordings/<recording-id>/corpus/anchor_NNN.txt
   ```
   where `NNN` is the zero-padded anchor ID (e.g. `anchor_000.txt`, `anchor_001.txt`).
3. Populate each file with the expert's verbatim transcript segments and any curated interpretive notes relevant to that anchor. Plain text only — one thought per line works well.
4. Set `"corpusFile": "corpus/anchor_NNN.txt"` on each anchor in `narrative_anchors.json`.
5. Optionally set `"interpretation"` and `"expertQuote"` fields for the sidebar display.

Until corpus files exist, the ASK button is hidden for that anchor. Visitors will not see missing-corpus errors.

---

## Engineering Standards

### The Snap Rule
Gaze hotspots must never float in space. All spatial processing must use 3D Raycasting (Open3D KDTree) against the MPS Point Cloud to ensure intersections with physical surfaces.

### Data Integrity
Maintain the relationship between tracking_timestamp_us and world-space coordinates. Use the X-Ray Viewer (x-ray-viewer/) to inspect and nudge registration if spatial drift is detected.

### Compatibility
Ensure that spatial outputs (JSON/PLY) remain compatible with both the Python visualization scripts and the React-based viewers.

---

## Citation

If you use this software, please cite the accompanying paper:

> Borunda, L., Argota Sánchez-Vaquerizo, J., Wissman, M., Lamoureux, K., Zhu, M., Marchiori, E., Gavazzi, A., Cantoni, L. In The Eyes Of: An Offline-First System for Geolocalized Expert Narration in Heritage Interpretation. Proceedings of NGEN-AI 2026, University of Trento, Italy. Springer.

See `CITATION.cff` for machine-readable citation metadata.

## License

This project is licensed under the [MIT License](LICENSE).

## Changelog

See [`documentation/CHANGELOG.md`](documentation/CHANGELOG.md) for a detailed version history.
