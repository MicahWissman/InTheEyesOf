# Gemini Context & Project Mandates: "In The Eyes Of"

This document serves as the primary context for Gemini CLI when interacting with the **InTheEyesOf** repository. It defines the project's research-driven mission, technical architecture, and the specific mandates that must govern all code modifications and analysis.

---

## 🔬 Research Mission & Philosophical Prioritization
This repository is not a standalone software product; it is **infrastructure for hypothesis testing** and **benchmark construction** in a research project. The broader goal is to operationalize "expert visual attention" using Meta Project Aria egocentric data.

### Core Research Question
*How can multimodal signals identify moments of true **interpretive intent** rather than simple gaze duration or coincidental eye movement?*

### The Three Relevance Models
When reasoning about the codebase, evaluate all logic through the lens of comparing these three approaches:
1.  **Dwell-Time Baseline:** Simple fixation duration (Gaze Salience).
2.  **Gaze-Speech Synchronization (DTW):** Temporal alignment of gaze and voice.
3.  **Convergence Model (The Target):** A semantically grounded pipeline combining stable gaze, transcript cues, 3D intersection (raycasting), and vision-language verification.

### Intent vs. Salience
*   **Visual Salience:** Long fixations that may reflect difficulty, confusion, or simple navigation.
*   **Semantic Intent:** Moments where an expert is looking at a meaningful object while verbally referencing it.
*   **Mandate:** Prioritize implementations that improve the project’s ability to produce defensible “golden set” labels and measure object grounding accuracy.

---

## 🏗️ Technical Pipeline & Data Structure

### Stage 1: Ingestion & MPS
*   Processing Meta Project Aria `.vrs` files into Machine Perception Services (MPS) outputs (Trajectory, Gaze, Point Clouds).
*   **Tools:** `projectaria_tools`, `scripts/ingestion/`.

### Stage 2: Semantic Analysis & Raycasting
*   Clustering gaze hotspots and aligning them with Whisper-generated transcripts.
*   **Mandate (The "Snap" Rule):** Gaze hotspots (`gx, gy, gz`) must not float in space. They must be refined using **3D Raycasting** (Open3D KDTree) against the MPS Point Cloud to ensure they represent intersections with physical surfaces.
*   **Tools:** `scripts/gaze/semantic/spatial_transcript_summarizer.py`.

### Stage 3: Spatial Narrative Synthesis & Graphing
*   Generating the final narrative anchors (`narrative_anchors.json`) that combine AI-summarized intent, 3D spatial coordinates, and **Hand Interaction** signals.
*   **New: Stage 3b (Semantic Graphing):** Building a relational network of narrative anchors (`semantic_network_builder.py`) using embeddings to identify non-spatial thematic links.
*   **Tools:** `scripts/gaze/semantic/run_narrative_pipeline.py`, `scripts/gaze/semantic/hand_interaction_extractor.py`, `scripts/gaze/semantic/semantic_network_builder.py`.

### Stage 4: Multimodal Validation (Viewers)
*   **Web Viewer:** A React/Three.js frontend used to visualize the "expert gaze" within the 3D point cloud for human-annotated validation. Now supports geospatial trajectory overlays.
*   **X-Ray Viewer:** A specialized inspection tool for precise spatial alignment, allowing users to "see through" surfaces and nudge point cloud registration.
*   **Tools:** `InTheEyesOf/web-viewer/`, `InTheEyesOf/x-ray-viewer/`, `scripts/export_trajectory_latlon.py`.

---

## 🛠️ Operational Guidelines for Gemini

### 1. Research-First Implementation
Before suggesting a feature, ask: *Does this help compare the three research approaches or support human-annotated validation?* If it is "technically interesting but scientifically weak," discard it.

### 2. No Reversions of Raycasting Logic
The 2.0m fixed-depth gaze projection is a legacy baseline. All future spatial processing must default to the **Raycasting Intersection** model using Open3D to maintain surface alignment.

### 3. Data Integrity & Alignment
Protect the relationship between the `tracking_timestamp_us` in the `.vrs` files and the world-space coordinates. Use the **X-Ray Viewer** to validate and "nudge" registration if drift is detected, but never introduce arbitrary transforms without documentation.

### 4. Development Workflow
*   **Research Phase:** Reproduce any reported issues and map the research implication.
*   **Strategy Phase:** Present the change in terms of the Research Mission.
*   **Validation Phase:** Ensure that spatial outputs (JSON/PLY) remain compatible with both the Python viz scripts and the Web/X-Ray Viewers.

---

## 📁 Key File Map
*   `/scripts/gaze/semantic/`: Core logic for intent extraction, hand interaction, and semantic networking.
*   `/scripts/ingestion/`: `.vrs` to MPS/SLAM processing.
*   `/web-viewer/`: React/Three.js infrastructure for expert review and geospatial mapping.
*   `/x-ray-viewer/`: Specialized spatial alignment and inspection tool.
*   `documentation/PIPELINE_USAGE_GUIDE.md`: The definitive operational handbook.
