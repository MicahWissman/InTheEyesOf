export interface Anchor {
  id: number;
  gx: number;
  gy: number;
  gz: number;
  start_ts?: number;
  end_ts?: number;
  start_sec?: number;
  narrative_title: string;
  narrative_titles?: Record<string, string>;
  narrative_description?: string;
  transcript_slice?: string;
  relative_time?: string;
  source?: string;
  streams?: string[];
  interpretation?: string | null;
  expertQuote?: string | null;
  expertVerbatim?: string | null;
  corpusFile?: string | null;
  audioUrl?: string | null;
  audioUrls?: Record<string, Record<string, string>>;
  audioCaption?: string | null;
  audioDuration?: number | null;
  text?: Record<string, string>;
  hasAudio?: boolean;
  isLead?: boolean;
  scores?: Record<string, number>;
  spatialContext?: string;
  gps?: [number, number];
  placement?: 'map' | 'cloud';
  lat?: number;
  lon?: number;
  contentCategory?: 'heritage' | 'nature' | 'context' | 'personal' | 'review';
  score?: number;
  verbatimLang?: string;
}

// ── Expert attention overlays (loaded from gaze_overlay.json alongside narrative_anchors.json) ──

export interface GazeOverlay {
  anchorId: number;
  gazeTarget: [number, number, number];  // world-space point the expert fixated on
  gazeSpread: number;                     // radians — cone half-angle (narrow = focused)
  gazeDepth: number;                      // metres — distance from anchor to target
  bodyState: 'dwelling' | 'scanning' | 'glancing';
  confidence: 'high' | 'medium' | 'synthetic';
  frameUrl?: string;                      // extracted RGB frame (e.g. "gaze_frames/anchor_003.jpg")
  objectLabel?: string;                   // object detection label (e.g. "stone archway with fresco")
  objectLabel_it?: string;
  _note?: string;                         // rich description from authoring pipeline
  _note_it?: string;
  _connectionGroup?: string;              // links gaze overlays across anchors (e.g. "mountain_orientation")
}

export interface GazeConnection {
  id: string;
  label: string;
  description: string;
  style: 'solid' | 'dotted';
  anchorIds: number[];
}

export interface TouchOverlay {
  pos: [number, number, number];  // world-space contact point
  label: string;                  // what was touched ("plaque text", "stone wall")
  label_it?: string;
  ephemeral: boolean;             // true = transient object (mushroom), false = permanent (tree, wall)
  anchorId?: number;              // assigned at load time — nearest anchor by distance
  frameUrl?: string;              // egocentric frame showing what the expert touched
}

// ── Narrative animations (audio-tied visual effects) ──

export interface AnimationEffectConnectionLines {
  type: 'connection_lines';
  anchorIds: number[];
  color: string;
  style: 'solid' | 'dotted';
  glowPulse?: boolean;
}

export interface AnimationEffectCompassArrow {
  type: 'compass_arrow';
  fromAnchorId: number;
  toAnchorId: number;
  color: string;
}

export interface AnimationEffectCameraFrame {
  type: 'camera_frame';
  anchorIds: number[];
  transitionSec: number;
  holdSec: number;
  returnSec: number;
}

export interface AnimationEffectVignette {
  type: 'vignette';
  color: string;
  holdSec: number;
}

export type AnimationEffect =
  | AnimationEffectConnectionLines
  | AnimationEffectCompassArrow
  | AnimationEffectCameraFrame
  | AnimationEffectVignette;

export interface NarrativeAnimation {
  trigger: 'anchor_play';
  anchorId: number;
  effects: AnimationEffect[];
  duration: number | string;   // seconds or "audio+20s"
  fadeIn?: number;
  fadeOut?: number;
  controls?: ('back' | 'next' | 'dismiss')[];
}

export interface GazeOverlayData {
  gazeOverlays: GazeOverlay[];
  touchOverlays: TouchOverlay[];
  connections?: GazeConnection[];
  animations?: NarrativeAnimation[];
}

export interface TrajectoryPoint {
  t: number;
  lat: number;
  lon: number;
  alt: number;
  wx?: number;
  wy?: number;
  wz?: number;
}

export interface TrajectoryData {
  start_t: number;
  end_t: number;
  sample_hz: number;
  count: number;
  path: TrajectoryPoint[];
  baked?: boolean;
}

export interface Node {
  id: number;
  pos: [number, number, number];
  title: string;
}

export interface Link {
  source: number;
  target: number;
  weight: number;
  semantic_sim: number;
  spatial_prox: number;
  rationale?: string;
}

export interface SemanticGraphData {
  nodes: Node[];
  links: Link[];
}
