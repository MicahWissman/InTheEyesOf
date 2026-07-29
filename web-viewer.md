# Web Viewer: Multimodal Research Interface

The Web Viewer is a React-based 3D application built with Vite, TypeScript, and Three.js (@react-three/fiber). It serves as the primary validation tool for the Spatial-Narrative Pipeline, allowing researchers to inspect AI-generated narratives situated within high-fidelity point cloud environments.

---

## Architecture Overview

The application is designed to be modular and data-driven, using a manifest-based system to swap between different research recordings.

### Core Technologies
- **React 19 & TypeScript:** Application logic and type safety.
- **Three.js & React Three Fiber:** 3D rendering engine.
- **React Three Drei:** Helper components for camera controls, materials, and complex geometries.
- **Leaflet:** 2D geospatial mapping for trajectory overlays.
- **Vite:** Build tool and development server with HTTPS support.

---

## Key Components

### 1. NarrativeViewer (src/components/NarrativeViewer.tsx)
The primary orchestrator component. It manages the toggle between the immersive **3D View** and the analytical **Map View**. It handles data fetching for anchors, graphs, and trajectories.

### 2. PointCloud (src/components/PointCloud.tsx)
Utilizes the `PLYLoader` to render large-scale semi-dense point clouds. It applies a `PointsMaterial` with vertex colors to maintain environmental realism.

### 3. Hotspots (src/components/Hotspots.tsx)
Renders interactive, pulsating `MeshDistortMaterial` spheres at gaze cluster centroids. These "Narrative Nodes" trigger sidebar updates upon selection.

### 4. SemanticConnections (src/components/SemanticConnections.tsx)
Visualizes the relational graph between narrative anchors. It draws lines between nodes where the `semantic_network_builder` identified thematic convergence, with line thickness and color reflecting connection weight.

### 5. TopDownMap & geoRegistration (src/utils/geoRegistration.ts)
A hybrid 2D/3D view that utilizes a Procrustes similarity transform to align SLAM-space coordinates with WGS84 GPS coordinates. This enables real-time "Blue Dot" tracking of the researcher's position relative to the point cloud if the device has GPS.

---

## Data Schema

The viewer expects a specific directory structure and JSON format for each recording in `public/recordings/<id>/`.

### Required Files:
- **`narrative_anchors.json`**: Array of objects containing 3D positions (`gx, gy, gz`), timestamped transcripts, and AI-generated titles/descriptions.
- **`pointcloud.ply`**: The spatial environment exported from the hotspot generation stage.
- **`semantic_graph.json`**: Nodes and links defining thematic relationships.
- **`trajectory_latlon.json`**: Geo-registered trajectory points for map alignment.

### Manifest Configuration:
Recordings must be registered in `public/recordings/manifest.json`:
```json
{
  "recordings": [
    {
      "id": "recording-unique-id",
      "title": "Descriptive Title",
      "anchorsFile": "narrative_anchors.json",
      "pointCloudFile": "pointcloud.ply",
      "semanticGraphFile": "semantic_graph.json",
      "trajectoryFile": "trajectory_latlon.json"
    }
  ]
}
```

---

## Development and Deployment

### Installation
```bash
cd web-viewer
npm install
```

### Local Development
The server runs on port 5173 and uses a basic SSL plugin to enable geolocation APIs which require a secure context.
```bash
npm run dev
```

### Build for Production
```bash
npm run build
```

---

## User Interaction Mandates
- **Navigation:** Supports Orbit controls (Left-click rotate, Right-click pan, Scroll zoom).
- **Recentering:** Double-click any point in the 3D scene to shift the orbital target to that location.
- **Semantic Inspection:** Clicking a connection line in the 3D view opens the "Convergence" panel in the sidebar, displaying the AI's rationale for linking the two locations.
- **Mobile Support:** Adaptive layout that converts the sidebar into a bottom-sheet for field-based validation.
