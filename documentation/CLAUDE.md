# CLAUDE.md — Project Context for Claude Code

> Durable context, constraints, and ethos — read first, every session. This is NOT a
> status tracker: current work, open bugs, and roadmap live in the active session, not here.
> The project has two halves — an AUTHORING pipeline (offline, builds the content) and a
> RUNTIME (offline, serves it to visitors). Know which half a task touches.

<project>
  <name>InTheEyesOf</name>
  <type>Research Infrastructure + field-deployed runtime</type>
  <summary>
    Infrastructure for hypothesis testing and benchmark construction, operationalizing
    "expert visual attention" from Meta Project Aria egocentric data — AND an offline-first
    runtime that serves the resulting expert narration to visitors on-site.
  </summary>
</project>

---

## Research Mission (authoring half)

<research_question>
  How can multimodal signals identify moments of true **interpretive intent** rather than
  simple gaze duration or coincidental eye movement?
</research_question>

<intent_vs_salience>
  <visual_salience>Long fixations reflecting difficulty/confusion/navigation. NOT the target.</visual_salience>
  <semantic_intent>Expert looks at a meaningful object while verbally referencing it. This IS the target.</semantic_intent>
  <mandate>Prioritize work that produces defensible "golden set" labels and measures object grounding accuracy.</mandate>
</intent_vs_salience>

### The Three Relevance Models
| # | Model | Description |
|---|-------|-------------|
| 1 | **Dwell-Time Baseline** | Simple fixation duration (gaze salience) |
| 2 | **Gaze-Speech Synchronization (DTW)** | Temporal alignment of gaze and voice |
| 3 | **Convergence Model** *(Target)* | Stable gaze + transcript cues + 3D raycasting + vision-language verification |

---

## Project Ethos (runtime half)

**Offline-first, no runtime inference in the delivered experience.** All model work happens at
authoring time; the runtime is deterministic playback that knows where the visitor is and plays
what the expert said there. Audio-first ("assisted reality") — the visitor attends to the site,
not the screen. Any live AI is an explicitly gated, OFF-BY-DEFAULT experimental layer; keeping
it off is what keeps the offline-first claim true.

**Knowledge sovereignty — provenance hierarchy (load-bearing):** Layer A = expert's verbatim
words (ground truth, served first, never paraphrased away) > Layer B = attributed authored
interpretation (exposed only with provenance) > Layer C = optional live AI. Never substitute a
lower layer for a higher one, never hide provenance.

---

## Technical Pipeline (authoring)

<pipeline>
  <stage id="1" name="Ingestion and MPS">
    Process Aria .vrs into MPS outputs (trajectory, gaze, point clouds).
    <tools>projectaria_tools, scripts/ingestion/</tools>
  </stage>
  <stage id="2" name="Semantic Analysis and Raycasting">
    Cluster gaze hotspots, align with Whisper transcripts.
    <tools>scripts/gaze/semantic/spatial_transcript_summarizer.py</tools>
    <critical_rule name="The Snap Rule">
      Gaze hotspots (gx,gy,gz) must NOT float. Refine via 3D raycasting (Open3D KDTree)
      against the MPS point cloud so they intersect physical surfaces. Never revert to
      fixed-depth projection.
    </critical_rule>
  </stage>
  <stage id="3" name="Spatial Narrative Synthesis, Discourse & Typed-Edge Graphing">
    Narrative anchors combining AI-summarized intent, 3D coords, hand-interaction signals, discourse classification (L1/L2/L3), and prosody/SER.
    Typed-edge graph builder with intent-gated referential channels and hyperparameter ablation study.
    <tools>scripts/gaze/semantic/semantic_network_builder.py, scripts/gaze/semantic/classify_discourse.py, scripts/gaze/semantic/ablation_study.py, scripts/gaze/semantic/plot_ablation.py</tools>
  </stage>
  <stage id="4" name="Multimodal Validation and Web Runtime">
    React/Three.js web viewer for visualizing gaze, trajectory, and validating 3D scene registration.
    <tools>web-viewer/, scripts/export_trajectory_latlon.py</tools>
  </stage>
</pipeline>

---

## Runtime — machines, stack, modes

- **Pi — `ssh eyesof`** — on-site edge node; serves everything at runtime, offline. Repo at
  `~/workspace/InTheEyesOf`. nginx + a Node `/ask` proxy. The RUNTIME tier.
- **DGX / edg — `ssh edg`** — heavy offline processing (embeddings, reconstruction). AUTHORING
  tier, never on the runtime critical path.
- **Web viewer** — React + Vite + three.js PWA in `web-viewer/`. Build: `cd web-viewer && npm run build`.
- **Three runtime modes:** MAP (OSM + coupled fixed-isometric follow-cam), AR (horizon-lock flat
  view), 3D (orbitable inspection). Mobile shows all three; desktop shows MAP/3D (no sensors → no AR).

---

## Mandates and Hard Rules

<mandates>
  <mandate id="1" name="Research-First Implementation">
    Before a feature, ask: does it help compare the three models or support human-annotated
    validation? Technically interesting but scientifically weak → discard.
  </mandate>
  <mandate id="2" name="No Reversions of Raycasting Logic">
    The 2.0m fixed-depth projection is a legacy baseline. Default to raycasting intersection
    (Open3D). Do not revert under any circumstances.
  </mandate>
  <mandate id="3" name="Data Integrity & Registration">
    Protect the tracking_timestamp_us ↔ world-space relationship. Validate trajectory and point cloud registration. Never introduce arbitrary transforms.
  </mandate>
  <mandate id="4" name="Output Compatibility">
    Spatial outputs (JSON/PLY) must stay compatible with the Python viz scripts AND the Web Viewer after any change.
  </mandate>
</mandates>

### Runtime DO NOT TOUCH (load-bearing — changing these breaks working systems)
- **`fitGeoRegistration` / geo-registration fit & scale** — affine math is verified; if alignment
  looks wrong, the trajectory data is the wrong layer to fix, not the fit.
- **Map / iso positioning** — Leaflet is the SINGLE SOURCE OF TRUTH for the 2D viewport; the iso
  camera is derived from it. Don't refactor "for consistency."
- **AR orientation contract** — keep YXZ Euler order, roll locked at 0, never re-add `<Center>`,
  no orientation deadband/gate (pure EMA only — a gate makes panning chunky).
- **Orbit** is the desktop/no-sensor fallback and internal base state — keep it, never a mode a
  visitor lands in.

### Runtime hard invariants (lessons paid for in hours)
- **Audio:** one shared gesture-unlocked HTMLAudioElement, all playback through the single
  hardened `doPlay` path (watchdog + channel-release). Never `new Audio()` per anchor. Every
  trigger (tap, "I'm here", proximity) funnels through one play function. Reset currentTime=0
  only AFTER metadata loads.
- **Asset URLs root-relative** (`/recordings/...`), never absolute `http://host/...` — nginx
  forces http to https for secure-context sensors; an absolute http URL hits the 301 and fails.
- **Large point clouds:** decimate to a draw budget; never render a hidden 3D scene behind
  another mode (WebGL context loss crashes the app). Keep the webglcontextlost handler.
- **GPS:** the accuracy guard must not starve AR while the map still tracks. Rail-snap defaults OFF.
- **Heard anchors:** fully-heard anchors turn gray (#999999) at 40% opacity across ALL modes
  (MAP, orbit, 3D, AR). They must remain visible — never hide or remove them.

### Secrets
- Keys (ElevenLabs, Gemini) live ONLY in `.env` on the Pi, read server-side — never in the
  client bundle. The `/ask` proxy holds the Gemini key; the browser calls `/ask` relative.
- `.gitignore` ignores `.env` at any depth. ALWAYS `git status | grep -i env` before `git add -A`.

---

## Development Workflow

<workflow>
  <phase name="Research">Reproduce the issue and map the research implication before writing code.</phase>
  <phase name="Strategy">Frame the change against the Research Mission / which relevance model it serves; for runtime work, against the offline-first ethos.</phase>
  <phase name="Validation">Confirm spatial outputs (JSON/PLY) stay compatible with the Python viz scripts and the Web Viewer.</phase>
</workflow>

- Run agent sessions inside `tmux` (an SSH/cable drop kills a foreground agent mid-build).
- Tag before risky passes and push: `git tag pre-<name> && git push origin pre-<name>`.
- Investigate before changing; anchor sign/direction fixes to a known-good reference, don't guess.
- Build, report, and DO NOT commit unless told. End with `cd web-viewer && npm run build`, report last ~15 lines.
- Device behavior is the truth, not the build — a green build has repeatedly hidden broken
  on-device behavior (GPS, compass, audibility, AR turn direction). State what still needs a device test.
- Ship-stable over feature-rich. Field-deployed under deadlines; a working simpler path beats a fragile richer one.

---

## Key File Map
scripts/gaze/semantic/     # Core intent, discourse classification, prosody/SER, typed-edge networking, and ablation study
scripts/ingestion/         # .vrs processing and MPS output handling
web-viewer/                # React/Three.js runtime viewer (MAP/AR/3D) + expert review
server/                    # Node /ask proxy (Gemini key server-side)
documentation/             # Pipeline usage guides, changelog, and operational references
ablation_results/          # Parameter grid sweep output JSON, plots, and CSV (ignored by git)
pipeline_results/          # Output artifacts (JSON, PLY, etc.)
CITATION.cff               # Machine-readable author and citation metadata

---

## Register
Be a skeptical collaborator: ground fixes in evidence, sequence honestly, flag scope/deadline
tradeoffs, prefer one definitive fix anchored to a known-good reference over repeated guessing.
No cheerleading.
