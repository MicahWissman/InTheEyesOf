# Pipeline Rationale — Why Points Are Selected, Filtered, and Connected

> This document explains the *reasoning* behind the pipeline, not its commands. For
> setup and stage-by-stage usage, see [`README.md`](../README.md) and
> [`PIPELINE_USAGE_GUIDE.md`](PIPELINE_USAGE_GUIDE.md). The concrete parameter values
> cited here are the current defaults in `scripts/gaze/semantic/`; treat them as the
> instantiation of the principles below, not as the principles themselves.

---

## 1. The question the pipeline exists to answer

A long fixation is cheap to measure and almost always the wrong signal. People stare
because they are confused, lost, waiting, or simply pointing their head somewhere while
they think. **Dwell time measures effort, not meaning.**

What we actually want to capture is *interpretive intent*: the moment an expert attends
to a meaningful object **because** it matters to what they are doing or saying. The
entire pipeline is built to separate that signal — **intent** — from its loud, common
impostor — **visual salience**.

This framing forces a specific evaluation design. Every component is judged by whether it
helps distinguish three competing models of relevance:

| # | Model | What it claims relevance *is* |
|---|-------|-------------------------------|
| 1 | **Dwell-Time Baseline** | Long fixation = important. (Salience.) |
| 2 | **Gaze–Speech Synchronization (DTW)** | Gaze that temporally aligns with speech = important. |
| 3 | **Convergence Model** *(target)* | A point where *multiple independent signals agree* — stable grounded gaze **and** a verbal reference **and** spatial/semantic coherence — = important. |

The Convergence Model is the hypothesis. Models 1 and 2 are the baselines it must beat.
Everything below serves that comparison.

---

## 2. Selection — from a gaze ray to a point that means something

Raw eye gaze is a direction, not a place. A yaw/pitch pair tells you where the eye
pointed, not *what* it landed on. If we stopped there, every downstream step would be
reasoning about angles floating in front of the head.

### 2.1 Grounding the gaze on a real surface — the Snap Rule

We refuse to let gaze targets float. For every gaze sample we build a world-space ray
(CPF yaw/pitch rotated into world frame via the time-matched trajectory, `merge_asof`
within 100 ms) and **intersect it with the MPS point cloud** rather than projecting to a
fixed distance (`get_refined_gaze_points`, `spatial_transcript_summarizer.py`).

The ray is snapped to the cloud point with the smallest *perpendicular* distance to the
ray, searched in a 1.5 m neighborhood around a 2.0 m guess. The result is a 3D point that
sits on an actual physical surface the expert was looking at.

**Why this matters (not just how):**
- A surface-grounded point is *comparable*. Two glances at the same façade from different
  standpoints resolve to the same location; two glances at angularly-similar but
  physically-different things do not. Fixed-depth projection destroys both properties.
- It makes 3D reasoning honest. Clustering, distance, and proximity edges only mean
  something if the coordinates are real geometry, not a constant radius sphere.
- It is the precondition for *object grounding* — the project's core deliverable. You
  cannot ask "what object was this?" of a point that isn't on an object.

This is **The Snap Rule**, and it is a hard invariant: the 2.0 m fixed-depth projection
exists only as a labeled fallback, never as the default. Reverting it silently would
invalidate every spatial claim the pipeline makes.

### 2.2 Honest uncertainty — quality tiers instead of silent guesses

Not every ray finds a confident surface. Rather than discard the misses or pretend they
hit, each refined point is stamped with a **quality tier** by perpendicular distance:

| Tier | Perp. distance | Meaning |
|------|----------------|---------|
| **STRONG** (1.0) | < 0.5 m | Confident surface hit |
| **WEAK** (0.5) | 0.5–1.0 m | Plausible but loose |
| **UNCERTAIN** (0.25) | 1.0–1.5 m | Weak association |
| **FALLBACK** (0.0) | no surface in 1.5 m | No geometry; uses 2.0 m depth |

**Why keep and label the bad hits instead of dropping them?** Because a defensible
golden set requires *traceable* confidence. A reviewer (or a paper) must be able to say
"this anchor rests on STRONG geometry; that one is a FALLBACK guess" — and weight them
accordingly. Discarding the uncertain points would hide the pipeline's own doubt, which
is exactly the thing scientific infrastructure must not do. The tier travels with the
data all the way to `pipeline_params.json` as an aggregate histogram.

---

## 3. Filtering — turning a cloud of glances into a few meaningful moments

A recording produces tens of thousands of grounded gaze points. Most are transit — the
eye sweeping between things. Filtering is where salience is stripped away and candidate
*moments* survive. It happens in four deliberate stages.

### 3.1 Trust the map before trusting the gaze
The point cloud itself is filtered first (`dist_std <= 0.15`, MPS's recommended
confidence threshold). Snapping gaze to noisy geometry would manufacture false precision,
so low-confidence cloud points are removed before any raycasting.

### 3.2 Exclude what we can't stand behind
Gaze points below WEAK quality (`quality < 0.5`) are pushed to infinity (`-1e6`) so they
**cannot join a cluster** (`run_indexing`). Intent claims are only built on gaze we can
physically locate. Uncertain and fallback points still exist in the record, but they do
not get to *found* a hotspot.

### 3.3 Spatial agreement — clustering (the "where")
Surviving points are clustered with **DBSCAN** (`eps = 0.25 m`, `min_samples = 10`).
DBSCAN is chosen on purpose: it has no fixed number of clusters and it treats sparse
sweeps as noise. A "hotspot" is therefore defined as *a place the eye returned to enough
times, tightly enough, to be more than a passing glance* — a spatial vote of confidence,
not a single sample.

### 3.4 Temporal persistence — the actual salience filter (the "when")
Within each cluster, contiguous gaze becomes an **event**. Two thresholds encode the
intent-vs-salience judgment directly:
- `GAP_TOLERANCE_US = 1.5 s` — brief look-aways don't break a sustained fixation.
- `MIN_EVENT_DURATION_US = 0.8 s` — anything shorter is a glance, not attention, and is
  dropped.

This is where flicker and transit die. What remains is a **"significant viewing event"**:
a sustained, surface-grounded fixation. Note that this stage still only measures
*salience* (stable looking). It is necessary but not sufficient for intent — that
distinction is made later, by connection.

### 3.5 Giving each moment language and identity
Each event's time window (expanded by `TRANSCRIPT_CONTEXT_SEC = 5 s` on each side) is
aligned to the transcript, summarized, and passed to a vision-language step that names
the **objects** and **actions** present. Finally, hotspots within `group_radius = 2.0 m`
are merged into **anchors** so that one physical feature looked at repeatedly becomes one
narrative node, not many.

> **A caveat the pipeline now records honestly:** the `objects` list is currently inferred
> by a language model **from the transcript text**, not detected from the gaze image. It
> reflects what the expert *said*, not what the camera *saw*. Section 5 explains why this
> matters and what the visual-grounding work showed.

---

## 4. Connection — operationalizing "convergence"

Selected, filtered anchors are the nodes. The edges are where the Convergence Model lives.
For every pair of anchors we compute three **independent** channels
(`semantic_network_builder.py`):

| Channel | Signal | Computation |
|---------|--------|-------------|
| **Spatial** | Are they in the same place? | `P = exp(-lam · d)` over 3D distance |
| **Referential** | Do they name the same things? | Jaccard overlap of object tags |
| **Thematic** | Do they mean the same thing? | Cosine of `bge-m3` embeddings of the narratives |

The key design decision is that these are **typed edges**, not a fused score. Each channel
is thresholded on its own (`tau_spatial`, `tau_referential`, `tau_thematic`), and an edge
records *which* channels fired and a **convergence degree** of 0–3.

**Why typed instead of a weighted sum `αS + βT + γP`?** Because a single blended number
hides the very thing we are trying to measure. "These two moments are connected by *all
three* signals" is a fundamentally stronger, more falsifiable claim than "these two
moments scored 0.62." Convergence degree makes the model's central hypothesis — that
*agreement across independent modalities* marks intent — directly visible and directly
testable. The old fused weight is retained only for viewer backward-compatibility and is
deprecated.

---

## 5. What we have actually learned (and why the design is evolving)

A rationale that only states intentions is marketing. This section records what the
instrumentation has *shown*, including where it contradicted our expectations. These
findings are reproducible via `scripts/gaze/semantic/experiments/`.

### 5.1 Two of the three connection channels are largely redundant
A 336-combination sweep of the typed-edge thresholds (`ablation_study.py`) found that
**only `tau_thematic` materially changes the graph.** A dedicated diagnostic
(`referential_diagnostic.py`) explained why: the referential channel is near-zero under
exact tag matching, and even after repair it adds essentially no edges the thematic
channel doesn't already produce (correlation ≈ 0.55). The reason is structural — the
`objects` and the `narrative_description` are generated from the **same transcript**, so
they are not independent evidence. **Consequence:** the convergence graph, as currently
fed, behaves close to a text-similarity graph. Adding a knowledge graph over those same
text-derived objects would inherit the redundancy, not cure it.

### 5.2 The missing independence is *visual*
If two of three channels collapse onto "what was said," the only way to restore genuine
multimodal convergence is a channel grounded in **what was seen**. The visual-grounding
pilot (`extract_gaze_crops.py` + `dino_ground.py`) tests this: it reprojects each gaze
sample into the RGB frame with the **calibrated fisheye model** at the expert's measured
fixation depth, crops the foveal region, and runs open-vocabulary detection (Grounding
DINO) on what the expert *actually looked at*.

The honest result, after removing measurement artifacts (a symmetric object vocabulary
and the calibrated projection): vision and speech **largely agree** — on Steger, ~58% of
foveated objects are already named in the transcript. So the visual channel does **not**
add a large new *vocabulary* of objects. Its defensible value is different and arguably
more important: **grounding and verification** — confirming *which* object the fovea was
on, with a pixel box, a confidence, and a depth, none of which a transcript can provide.
That is precisely the "object grounding accuracy" the project is meant to deliver.

### 5.3 Narration style changes the coupling — measurably
Using identical gaze crops and swapping only the transcript, moment-by-moment **guided**
narration couples roughly **2× more tightly** with the gaze than a comprehensive
**enriched object inventory** — replicated on both sites (Steger 50% vs 25%; Irchel 37.5%
vs 18.8%). A speaker who says *"I'm focused on the flag"* co-references the live fixation;
an exhaustive scene description does not. **Implication for golden-set construction:**
guided, first-person narration is the better-aligned modality for harvesting intent
labels.

### 5.4 Site/activity type may dominate transcript style
Across everything, coupling tracked the *kind of looking*: a deliberate architectural
inspection (Steger) coupled more than an exploratory park walk (Irchel). This is the
intent-vs-salience axis re-appearing at the level of whole recordings, and it is the next
thing worth measuring directly.

---

## 6. Design principles (the invariants behind the choices)

1. **Ground before you reason.** No spatial claim is made on a point that isn't snapped
   to real geometry (the Snap Rule). Fixed-depth is a labeled fallback, never a default.
2. **Carry your uncertainty.** Quality tiers and fallback flags travel with the data so
   confidence is auditable, not hidden.
3. **Persistence over duration-alone.** A moment must be *spatially* (clustering) and
   *temporally* (min-duration) stable before it is a candidate at all — but stability is
   salience, not yet intent.
4. **Independence is the whole point.** Convergence only means something if the channels
   are independent. The current redundancy of the text-derived channels is a known
   limitation, and visual grounding is the path back to real independence.
5. **Falsifiable over impressive.** Typed edges, per-channel thresholds, and the
   all-pairs component export exist so claims can be checked and rated, not admired.
6. **Protect registration.** The link between `tracking_timestamp_us` and world space is
   sacred; drift is corrected by validated nudging, never by arbitrary transforms.

---

*See also: [`CHANGELOG.md`](../CHANGELOG.md) (v0.4-beta documents the diagnostics and the
visual-grounding pilot summarized in §5), and the architecture figures in this folder.*
