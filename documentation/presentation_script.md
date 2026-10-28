# "In The Eyes Of" — Conference Presentation Script (Draft)

**Target length:** 20 minutes talk (+ Q&A buffer)
**Format:** 15 content slides, timed. Each slide block has: slide bullets (what goes on the deck), a speaker script paragraph (what you say), and a visual note (what to show).
**Source material:** paper draft (`InTheEyesOf__An_Offline_First_System...pdf`) and `documentation/CLAUDE.md`.
**Existing figure assets to reuse:** `documentation/fig_system_architecture_v2.svg`, `fig_authoring_pipeline.svg`, `fig_architecture_sovereignty.svg` — these already match Figs. 1–4 in the paper, so slides 5–9 can lift them directly instead of rebuilding diagrams.

This is a first draft to react to — trim, reorder, or cut sections freely. Timings assume a moderate speaking pace (~130 wpm) and are cumulative.

---

## Slide 1 — Title (0:00–0:45)

**Slide bullets:**
- In The Eyes Of: An Offline-First System for Geolocalized Expert Narration in Heritage Interpretation
- Authors, affiliations (Virginia Tech, ETH Zürich, USI Lugano, Lugano Living Lab, Univ. of Genoa)
- Your name / presenting author, conference name, date

**Speaker script:**
"Good [morning/afternoon]. I'm going to talk about a system we built and field-deployed at four heritage sites on two continents — it lets an expert walk a site once, narrating what they see, and turns that single walk into a geolocalized audio guide that runs entirely offline, with zero internet connection, from a battery-powered box on site."

**Visual:** Title slide, maybe one striking photo from a deployment (Carona hillside or Steger Center point cloud).

---

## Slide 2 — The Problem (0:45–2:30)

**Slide bullets:**
- Heritage sites are connectivity-poor, multi-hour, multi-visitor environments
- Digital interpretation is usually designed as if reliable site networking exists
- Consequence: systems fail exactly where interpretation is needed most
- Cloud-dependent design also has a sovereignty cost: the site must route its own expert knowledge through an outside platform

**Speaker script:**
"Outdoor archaeological sites, historic villages, dispersed monuments — these frequently have no reliable wireless coverage. A guided visit runs for hours. Visitors show up with a mix of phones and tablets, some without GPS at all. Yet most digital interpretation tools — AR guides, chatbot museum companions — assume you can always reach the cloud. That assumption fails precisely where heritage interpretation matters most. There's a second, less obvious cost too: if the site has to route its own expert's knowledge through an outside cloud platform every time a visitor asks a question, the site doesn't really own that knowledge anymore. It's renting access to its own content."

**Visual:** A simple photo/map showing a remote heritage site with a "no signal" indicator, or a one-line contrast: "always-on cloud assumption" vs "reality on site."

---

## Slide 3 — Design Thesis (2:30–4:00)

**Slide bullets:**
- First principle: the system must work with **zero site connectivity**
- Audio-first / "assisted reality": visitor attends to the site, not a screen
- Central design decision: **AI runs at authoring time, not runtime**
- Runtime = deterministic, offline playback: knows where you are, plays what the expert said there

**Speaker script:**
"So we flipped the assumption. Zero connectivity is the starting constraint, not an edge case to patch around later. Second, we wanted visitors looking at the site, not a screen — that's what the industry calls 'assisted reality,' audio-first delivery. And the central architectural decision that falls out of both of those: all the AI — the language models, the semantic analysis — runs once, at authoring time, before deployment. The runtime that visitors actually use is just deterministic playback. It knows where you're standing and plays back what the expert said about that spot. No inference happens live."

**Visual:** Simple two-box diagram: "Authoring time (cloud, once, supervised)" → "Runtime (edge node, offline, deterministic)."

---

## Slide 4 — Contributions (4:00–5:00)

**Slide bullets:**
1. Offline-first architecture serving the full experience from a battery-powered edge node
2. Authoring-time pipeline: semantic analysis of expert speech + gaze → knowledge graph → geolocalized narrative points
3. Reproducible georeferencing pipeline: egocentric capture → browser-renderable, georeferenced scene
4. Multi-device positioning topology: one GPS phone supplies position to a whole group

**Speaker script:**
"Four contributions, and I'll walk through each. An architecture that serves the complete visitor experience — scene, narration, positioning — with no connectivity. An authoring pipeline that fuses what the expert said with what they looked at into a knowledge graph, so the runtime never has to think. A reproducible way to take egocentric capture and turn it into a georeferenced, browser-renderable 3D scene. And a practical fix for a real deployment problem: most tablets in a tour group don't have GPS, so we relay position from the one phone that does."

**Visual:** Four-item numbered list, icon per item.

---

## Slide 5 — System Architecture Overview (5:00–7:00)

**Slide bullets:**
- Three functional components: **spatial substrate → authoring-time analysis → offline runtime**
- Split across two tiers: always-present **edge tier**, optional **cloud tier**
- Expert wears Project Aria glasses, walks the site once, narrating
- Aria MPS pipeline → closed-loop SLAM trajectory, semi-dense point cloud, eye-gaze stream, hand-tracking stream
- Runtime: Node.js service on the edge node — scene, anchors, narration audio, position relay

**Speaker script:**
"Here's the whole system in one picture. [Use fig_system_architecture_v2.svg] Three bands: the spatial substrate, which is the raw capture and processing; the authoring-time analysis, which is three stages I'll detail in a minute; and the offline runtime that visitors actually interact with. The input to all of this is a single walk: an expert puts on Meta's Project Aria capture glasses and walks the site once, narrating naturally, the way they would for a real visitor. Project Aria's Machine Perception Services process that recording into a SLAM trajectory, a 3D point cloud, an eye-gaze stream, and hand-tracking. That's our raw material. On the runtime side, a Node.js service on a Raspberry Pi at the edge serves the 3D scene, the narration audio, the narrative anchors, and a position-relay service — all self-hosted, over the site's own Wi-Fi network, zero external dependency."

**Visual:** `fig_system_architecture_v2.svg` (Fig. 1 in the paper) — full width.

---

## Slide 6 — Knowledge Sovereignty: Content Layers A/B/C (7:00–8:30)

**Slide bullets:**
- **Layer A** — expert's verbatim words, ground truth, always disclosed, never paraphrased away
- **Layer B** — everything the pipeline derives: anchor placement, segmentation, typed edges, model-composed narrative, served TTS narration
- **Layer C** — optional live conversation (planned, off by default)
- Rule: never substitute a lower layer for a higher one; never hide provenance

**Speaker script:**
"This is the ethical backbone of the design, and it's worth a slide on its own. We organize everything the system serves into three layers of decreasing authority. Layer A is the expert's actual words — that's ground truth, and it is always available in-app, never paraphrased away. Layer B is everything we derive from that: where we placed the anchor in 3D space, how we segmented the walk, the AI-composed narrative summary, the synthesized multilingual narration the visitor actually hears. Layer C would be live AI conversation — that's on the roadmap, explicitly gated off by default. The hard rule across the whole system: never substitute a lower-authority layer for a higher one, and never hide where content came from. Even though the audio-first experience means most visitors hear Layer B, the source transcript — Layer A — is always one tap away."

**Visual:** `fig_architecture_sovereignty.svg` — pyramid or layered diagram, A on top.

---

## Slide 7 — Authoring Pipeline, Stage 1: Signal Extraction & the Snap Rule (8:30–10:15)

**Slide bullets:**
- Gaze samples merged onto SLAM trajectory (100 ms tolerance) → world-space gaze rays
- **The Snap Rule:** rays raycast onto the measured 3D point cloud (Open3D k-d tree) — anchors sit on the physical surface the expert looked at, never floating, never fixed-depth
- Quality tiers: strong (<0.5 m) / weak (0.5–1.0 m) / uncertain (≥1.0 m) / fallback (2.0 m fixed depth, last resort)
- Gaze events: DBSCAN clustering in world space, ±5 s transcript window attached
- Hand-tracking gated at >0.8 confidence marks pointing gestures

**Speaker script:**
"Stage 1 is where we figure out what the expert was physically looking at. Eye-gaze samples get merged onto the SLAM trajectory, converted into 3D rays. Here's the key idea we call the Snap Rule: instead of guessing a fixed depth for where the gaze lands, we raycast that ray against the actual measured point cloud and snap to the real surface. So when the expert looks at a specific column or a specific tree, the anchor sits exactly where that object physically is, not floating in space at some assumed distance. Each snap gets a quality tier based on how close the match is, and only degrades to a fixed 2-meter guess as an absolute last resort. We then cluster nearby gaze samples into discrete 'gaze events' and slice out a five-second window of transcript around each one."

**Visual:** `fig_authoring_pipeline.svg` (Fig. 2 detail) — trajectory → snap → cluster → segment pipeline.

---

## Slide 8 — Stage 2: Narrative Synthesis & Discourse Gating (10:15–12:00)

**Slide bullets:**
- Co-located gaze events merged into **anchors** (complete-linkage clustering)
- One LLM call per anchor (Gemini 2.5 Flash, text-only) → structured JSON: title, narrative, objects, actions, spatial properties
- **Discourse classification** (L1/L2/L3) gates on interpretive *intent*, not just gaze dwell:
  - L1 = concrete, object-referential (the actual target)
  - L2 = contextual scaffolding
  - L3 = aside / procedural noise
- Local speech-emotion recognition (arousal/valence/dominance) → conditions delivery prosody

**Speaker script:**
"This is really the core research question of the project: how do you tell the difference between an expert glancing at something briefly out of genuine interpretive interest, versus just looking around while thinking, or talking about something unrelated? Long gaze dwell alone doesn't tell you that — someone can stare at something out of confusion, not insight. So every transcript segment gets classified into three discourse levels: concrete and object-referential speech, which is our actual target signal; contextual scaffolding; or asides and procedural noise, like 'okay let's walk this way now.' That classification, aggregated per anchor, gives us an interpretive-intent strength score, and it's what gates which content actually counts as genuine interpretation downstream. In parallel, a locally-run speech-emotion model extracts the expert's tone — arousal, valence, dominance — which later shapes how the synthesized narration is delivered."

**Visual:** `fig_authoring_pipeline.svg` (Fig. 3 detail) — two parallel paths recombining into enriched anchor.

---

## Slide 9 — Stage 3: Typed-Edge Knowledge Graph (12:00–13:30)

**Slide bullets:**
- Anchors become nodes in a **site knowledge graph**
- Every anchor pair scored on **three independent typed channels**:
  - Spatial (proximity), Thematic (embedding cosine similarity), Referential (object-tag overlap)
- Referential channel is **intent-gated** — only counts when both anchors are genuinely object-referential
- Convergence degree ≥ 2 = edge retained → this is what determines which neighboring stops a visitor is offered

**Speaker script:**
"Once we have enriched anchors, we build a graph out of them. Rather than collapsing all the ways two narrative points might relate into one fuzzy similarity score, we score every pair on three separate, typed channels: are they physically close, are they thematically similar in what the expert said, and do they share the same referenced objects? That last channel — referential — is gated by the interpretive-intent score from Stage 2, so casual chatter doesn't create false connections. We only keep an edge if it passes the referential test, or if it converges on at least two of the three channels. That's the graph that actually ships — it decides which nearby stories a visitor gets offered when they're standing at a given anchor."

**Visual:** `fig_authoring_pipeline.svg` (Fig. 4 detail) — the three-channel scoring diagram.

---

## Slide 10 — Worked Example: Carona, Lugano (13:30–14:45)

**Slide bullets:**
- Single continuous expert walk → 446 narrative anchors (after pruning ~20 logistics/off-topic asides)
- Example quote (translated from Italian): expert narrating hillside ecology — "...this vegetal city growing around us"
- Anchor: *Ecological Formation of Vegetation* — objects: {animals, forest, plants, soil, water networks}
- Linked to neighbor anchor *Forest, Animals, and Soil* — converges on **all three channels** (degree 3) → edge retained with an LLM-generated rationale

**Speaker script:**
"Let me make this concrete with a real example from our Carona deployment, a historic village above Lake Lugano. The expert is walking a wooded hillside, narrating the ecology of the slope — I'll read the translated quote: [read quote]. Stage 1 snaps that gaze to a strong-quality target on the hillside. Stage 2 produces a structured anchor titled 'Ecological Formation of Vegetation.' Stage 3 finds that this anchor converges with a neighboring one about forest, animals, and soil — on all three channels at once, thematic, referential, and spatial — so that edge gets kept, with an automatically generated rationale explaining the shared theme. That one walk produced 446 of these anchors."

**Visual:** Screenshot from Fig. 5a/5b — the Carona map view with anchor list, or a simple text callout with the quote.

---

## Slide 11 — Georeferencing Pipeline (14:45–15:45)

**Slide bullets:**
- Aria MPS output lives in a local, gravity-aligned SLAM frame with **arbitrary heading** — not georeferenced
- Rigid similarity transform (Umeyama least-squares) maps SLAM frame → local East-North-Up frame at an Earth anchor point
- Applied to point cloud + every anchor → metric, north-aligned, georeferenced scene
- Renders in a browser-based PWA with a top-down map
- Carona fit: scale 0.9994, residual 0.040 m RMS (0.092 m max) — internal consistency, not surveyed ground-truth accuracy

**Speaker script:**
"One more piece of engineering worth mentioning: the raw SLAM output from Aria has no idea which way is north or where on Earth it is — it's a self-consistent local coordinate frame. We compute a rigid similarity transform, once, using the Umeyama method, mapping that frame onto a real-world East-North-Up frame anchored at a known Earth point. Apply that to the point cloud and every anchor, and you get a metric, north-aligned scene that renders in a normal web browser with a real top-down map underneath it. On our Carona scene that fit recovers a scale within 0.06% of 1.0 and a residual of 4 centimeters — though I want to be precise that this measures internal consistency of the transform, not accuracy against a surveyed ground truth, which is still on our list of things to validate."

**Visual:** Before/after: raw point cloud floating in arbitrary space → same cloud aligned over satellite map.

---

## Slide 12 — Field Deployments & Runtime Numbers (15:45–17:00)

**Slide bullets:**
- Four sites, two continents:

| Site | Setting | Anchors |
|---|---|---|
| Irchel Park, Zürich (CH) | Outdoor urban park | 68 |
| Carona, Lugano (CH) | Historic village | 446 |
| Steger Center, Riva San Vitale (CH) | Building + gardens | 11 |
| Gilbert Hall, Virginia Tech (USA) | University campus | 8 |

- Runtime profile (Raspberry Pi 5, 86.4 Wh power bank): 3.5 W sustained draw → **~25 hour** projected endurance
- Position relay latency: 0.42 ms median; viewer holds 90 fps at 1.5M points

**Speaker script:**
"We've deployed this at four sites across two continents, from a full historic village down to a single university hallway — the pipeline scales down as easily as up. On the hardware side, the entire edge node is a Raspberry Pi 5 running off a battery bank: 3.5 watts sustained, which projects to roughly 25 hours of runtime on a single charge — enough for a full day of tours without plugging in. Position relay between devices runs sub-millisecond, and the 3D viewer holds 90 frames per second on a commodity phone. These are feasibility numbers from real deployment sessions, not a controlled lab benchmark, but they show the budget works."

**Visual:** Deployment site photos (small grid of 4) + the two key stats (25h endurance, sub-ms relay) as large callouts.

---

## Slide 13 — Multi-Device Positioning & Ethics (17:00–18:00)

**Slide bullets:**
- Most tablets lack GNSS; no uplink means no network positioning either
- Fix: **one GPS-equipped phone** publishes position over a WebSocket relay on the edge node; other devices subscribe
- Ethics: **"privacy-by-derivation"** — all raw recordings run through Meta EgoBlur (face/plate redaction) before any downstream processing
- Runtime never serves raw video — only point cloud, synthesized narration, and selective redacted stills
- VT IRB: Not Human Subjects Research (protocol 26-089); expert co-author gave informed consent

**Speaker script:**
"Two quick practical notes. First, positioning: most tablets people bring on a tour don't have GPS, and there's no cell network to fall back on anyway. Since the group is physically moving together, we just need one phone with GPS — it publishes its position over a local WebSocket relay, and every other device on the network subscribes to that. Second, ethics — an egocentric camera on a public heritage site inevitably captures bystanders who never consented. Every raw recording gets run through Meta's EgoBlur to redact faces and license plates before any further processing happens, including before it's sent to any cloud service. The runtime itself never serves raw video — only the derived point cloud, synthesized narration, and occasional already-redacted still frames. This was reviewed by our IRB and determined not to be human-subjects research, and our expert narrator is a full co-author who gave informed consent to everything, including publication."

**Visual:** Simple diagram: phone with GPS → WebSocket relay → other devices. Small EgoBlur before/after redaction example if available (non-sensitive).

---

## Slide 14 — Research Roadmap (18:00–19:15)

**Slide bullets:**
- **Runtime generative interpretation** — pluggable interface for Layer B/C models; on-device quantized model on edge accelerator is the next systems study
- **Interpretive-alignment metric** — cosine similarity between embeddings of expert vs. visitor description of the same region; needs an instrumented visitor study
- **Visual grounding** — vision pass on gaze-centered frames to independently verify *what* the expert was looking at, not just infer it from speech
- **Indoor positioning** — 6-DoF visual positioning to close the GNSS gap indoors
- This is a **feasibility paper, not a validation paper** — 8 explicit success criteria are listed but unmeasured (spatial grounding accuracy, anchor correctness, narration fidelity, edge precision, threshold sensitivity, discourse-label agreement, value over baseline, interpretive alignment)

**Speaker script:**
"I want to be upfront about where this stands. This is a systems and feasibility paper — we're not claiming a validated visitor-outcomes study yet, and the paper is explicit about that. Four directions we're actively pushing: moving the generative interpretation itself onto the edge device, so eventually even content authoring doesn't need the cloud; a proposed interpretive-alignment metric that would measure, automatically, how closely a visitor's understanding tracks what the expert actually said, using embedding similarity; adding a real computer-vision pass so we're not purely inferring what object the expert looked at from their speech alone; and closing the indoor positioning gap where GPS doesn't reach. We also lay out eight concrete success criteria the system should eventually be judged against — things like anchor correctness and edge precision — and we're honest that none of them are measured in this paper yet. That's the next phase of work."

**Visual:** Roadmap as a simple horizontal timeline or 4-box grid, one per direction.

---

## Slide 15 — Conclusion (19:15–20:00)

**Slide bullets:**
- Early-stage, field-deployed, offline-first system for expert-narrated heritage interpretation
- AI does the hard semantic work once, at authoring time — runtime is deterministic, connectivity-free playback
- Working deployment across 4 sites validates the *approach*; visitor-outcome validation is the stated next step
- Code, prompts, and configuration released in the project repository

**Speaker script:**
"To wrap up: heritage sites don't have reliable connectivity, and they shouldn't have to depend on it to deliver their own expert knowledge. We moved all the AI work to a one-time authoring pass, so the actual visitor experience is a deterministic, offline playback system running off a battery pack on site. We've proven that architecture works across four real deployments on two continents. What's next is measuring whether it actually improves how visitors understand a site — and that's the visitor study we're planning. Everything — the pipeline code, the prompts, the configuration — is open in the project repository. Happy to take questions."

**Visual:** Repository URL / QR code, contact info, "Thank you."

---

## Appendix / Backup Slides (not in main 20 min, for Q&A)

Keep these ready but off the main deck flow — pull up only if asked:

- **Table 1 (paper)** — full authoring-pipeline parameter list (DBSCAN epsilon, thresholds, model versions) if someone asks for implementation specifics.
- **Table 4 (paper)** — full implemented-vs-planned capability matrix, if someone asks "what's actually shipped vs. aspirational."
- **The three relevance models** (from `CLAUDE.md`, underlying research framing): (1) dwell-time baseline, (2) gaze-speech DTW synchronization, (3) convergence model (the deployed target) — useful if asked "how does this compare to just using gaze duration?"
- **Runtime modes** — MAP (OSM + isometric follow-cam), AR (horizon-lock), 3D (orbit) — if asked about the actual visitor-facing app UI. Mobile gets all three; desktop gets MAP/3D only (no AR sensors).
- **Cloud vs. local today** — speech-to-text, embeddings, and speech-emotion already run locally; 3D reconstruction (Aria MPS), the LLM narrative/discourse work, and ElevenLabs TTS are the three remaining cloud dependencies, each with a stated local-replacement path.
- **Threshold sensitivity data point** — a released parameter sweep shows retained-edge count falling from ~2,300 to ~600 as the thematic threshold rises, i.e. current thresholds are curatorial choices, not optimized ones.

---

## Presenter notes

- **Total runtime check:** 15 slides × stated timings = 20:00 exactly. Build in ~30–60s of natural slack by trimming Slide 5 or 9 if you're running long — those are the two most compressible without losing the throughline.
- **Likely audience questions to pre-empt:** (1) "Why not just use GPT-4o live at runtime?" → answer is the offline-first/connectivity constraint, Slide 3. (2) "How do you know the AI-generated narrative is accurate?" → Layer A/B distinction, Slide 6, plus roadmap criterion #3 (narration fidelity). (3) "Has this been tested with real visitors?" → explicitly not yet, Slide 14 — be direct about this, the paper is upfront about it too.
- **If time is short (15 min):** cut Slide 13 (fold ethics into one bullet on Slide 12) and compress Slides 7–9 into a single "authoring pipeline" slide with three sub-bullets instead of three slides.
