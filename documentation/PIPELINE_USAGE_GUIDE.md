# Spatial-Narrative Pipeline Usage Guide

This document provides a comprehensive technical guide for transforming raw Meta Project Aria .vrs recordings into interactive 3D narrative visualizations.

---

## Prerequisites and Environment Setup

### 1. Python Environment
The pipeline relies on a specialized Conda environment.

```bash
conda env create -f aria_tools_conda.yml
conda activate aria_tools
```

Key dependencies include:
- projectaria-tools[all]
- openai-whisper
- open3d
- moviepy
- scikit-learn

### 2. VRS Command Line Tools
For low-level VRS file manipulation and inspection, the VRS CLI tool is required.

System Dependencies (Ubuntu/Debian):
```bash
sudo apt-get update
sudo apt-get install -y cmake git ninja-build ccache libgtest-dev libfmt-dev \
libturbojpeg-dev libpng-dev liblz4-dev libzstd-dev libxxhash-dev \
libboost-system-dev libboost-filesystem-dev libboost-thread-dev \
libboost-chrono-dev libboost-date-time-dev
```

Build and Install:
```bash
git clone https://github.com/facebookresearch/vrs.git
cd vrs
mkdir build && cd build
cmake -S .. -B . -G Ninja -DCMAKE_INSTALL_PREFIX=$HOME/vrs_install
ninja install
export PATH="$HOME/vrs_install/bin:$PATH"
```

### 3. Node.js Environment
The Web Viewer and X-Ray Viewer require Node.js 18.0.0 or higher.

---

## Data Ingestion and Processing

### 1. Transcription (Audio Stage)
Extract the audio stream and generate a timestamped transcript.

```bash
python scripts/gaze/semantic/vrs_to_transcript.py \
    --vrs path/to/recording.vrs \
    --output path/to/transcript.txt \
    --interval 10.0
```

### 2. Machine Perception Services (MPS)
Ensure you have the MPS results directory from Meta. It must contain the following subdirectories:
- slam/: closed_loop_trajectory.csv and semi_dense_points.ply
- eye_gaze/: generalized_eye_gaze.csv

---

## Execution Pipeline

### 1. Narrative Orchestration
The orchestrator merges gaze hotspots, transcripts, and hand tracking signals using the Gemini VLM.

```bash
python scripts/gaze/semantic/run_narrative_pipeline.py \
    --vrs path/to/recording.vrs \
    --mps path/to/mps_results \
    --transcript path/to/transcript.txt \
    --output ./pipeline_results
```

### 2. Semantic Network Builder
Generate the relational graph between narrative anchors.

```bash
python scripts/gaze/semantic/semantic_network_builder.py \
    --anchors ./pipeline_results/narrative_anchors.json \
    --output ./pipeline_results/semantic_graph.json \
    --threshold 0.6
```

### 3. Spatial Data Preparation
Convert ECEF coordinates to WGS84 for mapping and generate the gaze-salience point cloud.

```bash
# Trajectory export
python scripts/export_trajectory_latlon.py \
    path/to/mps_results/slam \
    ./pipeline_results/trajectory_latlon.json

# Point cloud generation
python scripts/gaze/hotspots/hotspot_gold_standard.py \
    --mps_root path/to/mps_results \
    --output_ply ./pipeline_results/pointcloud.ply \
    --k 5
```

---

## Web Viewer Deployment

### 1. Directory Structure
Create a new recording entry in `web-viewer/public/recordings/`:

```bash
mkdir -p web-viewer/public/recordings/my_recording
cp ./pipeline_results/* web-viewer/public/recordings/my_recording/
```

### 2. Manifest Update
Add the recording entry to the `recordings` array in `web-viewer/public/recordings/manifest.json`:

```json
{
  "recordings": [
    {
      "id": "my_recording",
      "title": "My Recording Title",
      "anchorsFile": "narrative_anchors.json",
      "pointCloudFile": "pointcloud.ply",
      "semanticGraphFile": "semantic_graph.json",
      "trajectoryFile": "trajectory_latlon.json"
    }
  ]
}
```

### 3. Serving the Viewer
```bash
cd web-viewer
npm install
npm run dev
```

---

## Technical Constraints and Mandates

1. Raycasting Enforcement: All gaze coordinates must be projected onto the 3D point cloud surface using Open3D's KDTree. Raw gaze depth must not be used as a final coordinate.
2. Temporal Alignment: Maintain strict synchronization between tracking_timestamp_us and the narrative nodes.
3. Aesthetic Standards: The web viewer expects point clouds in .ply format and spatial data in serialized JSON.
