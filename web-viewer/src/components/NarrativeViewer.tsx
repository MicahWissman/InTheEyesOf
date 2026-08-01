import { useState, useEffect, useLayoutEffect, useRef, useMemo, Suspense, useCallback } from 'react';
import { Canvas, useThree, useFrame } from '@react-three/fiber';
import { OrbitControls, Html } from '@react-three/drei';
import * as THREE from 'three';
import { PointCloud } from './PointCloud';
import { Hotspots } from './Hotspots';
import { Sidebar } from './Sidebar';
import { SemanticConnections } from './SemanticConnections';
import { TopDownMap } from './TopDownMap';
import { markerColor } from '../utils/anchorEncoding';
import { resolveAudioUrl } from '../utils/audioResolver';

// Shared type: written by NarrativeViewer on Leaflet events, read by CameraController
type IsoLeafletView = {
  slamX: number; slamY: number; slamZ: number;
  groundWidthM: number; geoScale: number;
};
import type { Map as LeafletMap } from 'leaflet';
import type { Anchor as AnchorType, SemanticGraphData, Link, TrajectoryData, GazeOverlayData } from '../types';
import { GazeBeams, TouchMarks, MapGazeLines, MapTouchDots, ScenePopup } from './GazeOverlays';
import { AnchorLabels } from './AnchorLabels';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { fitGeoRegistration } from '../utils/geoRegistration';
import { classifyDistance } from '../utils/proximity';
import type { ProximityCategory } from '../utils/proximity';
import { useIsMobile } from '../hooks/useIsMobile';
import { useDeviceOrientation } from '../hooks/useDeviceOrientation';
import { useDampedDeviceOrientation } from '../hooks/useDampedDeviceOrientation';
import { useAudio } from '../contexts/AudioContext';
import { useAI } from '../contexts/AIContext';
import { useNarrativeAnimations } from '../hooks/useNarrativeAnimations';
import { AnimatedOverlays } from './AnimatedOverlays';
import { WelcomeOverlay } from './WelcomeOverlay';
import { SettingsPanel } from './SettingsPanel';
import { CamView } from './CamView';
import { NarrativeBubble } from './NarrativeBubble';
import type { NearbyAnchorInfo } from './NarrativeBubble';

// ── AR Sense tuning constants ──────────────────────────────────────────────────
const AR_DEFAULT_PITCH_DEG = -20;
const AR_EYE_HEIGHT_M = 1.6;  // default eye height above medianWy (ImmersiveCamera)
const AR_IDLE_TIMEOUT_MS = 60000;
const AR_IDLE_COUNTDOWN_MS = 5000;
const AR_MOTION_THRESHOLD_DEG = 2;

// GPS glide: EMA factor on lat/lon — lower = more inertia / longer glide
const AR_GPS_GLIDE_ALPHA = 0.10;

// GPS accuracy guard — readings above this threshold are rejected.
// Phone GPS is often 10–40 m outdoors; 50 m avoids starving the pipeline.
// Tune down once walking data from the debug overlay shows typical accuracy.
const AR_GPS_MAX_ACCURACY_M = 50;

// Rail-snap: camera blends toward nearest trajectory point when within RAIL_RADIUS meters.
// AR_RAIL_SNAP_ENABLED = false → free GPS follow; true → blend toward recorded path.
// Radius reduced to 3 m so re-enabling gives a gentle assist rather than a hard pin.
const AR_RAIL_SNAP_ENABLED = false;
const AR_RAIL_RADIUS_M = 3.0;

// Orientation: yaw follows phone turn ~1:1; pitch is horizon-biased to avoid floor-dives
const AR_YAW_FACTOR = -1.0; // negated to match ImmersiveCamera Euler(pitch, -yaw, 0)
const AR_PITCH_FACTOR = 0.25;
// ORIENTATION_SMOOTHING_ALPHA = 0.15 lives inside useDampedDeviceOrientation

// ── AR Horizon Lock (experimental) ───────────────────────────────────────────
// When true: yaw-only camera — tilting phone up/down does NOT move camera, no pitch flicker.
// When false: falls back to the existing yaw+pitch path (AR_PITCH_FACTOR in use).
// Flip to false to compare against the full pitch-tracking behaviour.
const AR_HORIZON_LOCK = true;
const AR_HORIZON_PITCH_DEG = 0;    // fixed camera pitch from horizon (degrees, tunable)

// Static initial camera quaternion: looking along -Z with 20° downward tilt.
const AR_INITIAL_CAM_Q = new THREE.Quaternion().setFromEuler(
  new THREE.Euler(THREE.MathUtils.degToRad(AR_DEFAULT_PITCH_DEG), 0, 0, 'YXZ'),
);

// CAM mode: identity = straight ahead, full pitch tracking, no horizon lock
const CAM_INITIAL_Q = new THREE.Quaternion();

// ── ISO/MAP camera geometry (mirrors TopDownPointCloud constants) ──────────────
const ISO_H = 80;   // camera height above target (world units)
const ISO_D = 60;   // camera offset south of target
const COLOR_HEARD = '#666666';

// ── AR vertical swipe — eye height ───────────────────────────────────────────
// Tap: vertical travel < threshold → falls through to R3F click (anchor selection)
// Swipe: vertical travel ≥ threshold → adjusts heightOffset
const AR_HEIGHT_SWIPE_TAP_THRESHOLD_PX = 10;
// 750 px of vertical drag ≈ 3 m of height change (tunable)
const AR_HEIGHT_SWIPE_M_PER_PX = 3 / 750;
const AR_HEIGHT_SWIPE_MIN_M = 0.0;
const AR_HEIGHT_SWIPE_MAX_M = 4.0;

// ── GPS distance gate — suppress GPS when device is far from the recording area
const GPS_TOO_FAR_M = 500;

function haversineDist(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// ── Proximity auto-play thresholds ─────────────────────────────────────────────
const PROX_ENTER_M = 4;   // metres — fires auto-play on enter
const PROX_EXIT_M = 8;   // metres — must leave before hysteresis re-arm

// Synthesise a brief soft chime via Web Audio (no audio file needed)
function playSoftChime() {
  try {
    type WebkitWindow = Window & { webkitAudioContext?: typeof AudioContext };
    const AC = window.AudioContext ?? (window as unknown as WebkitWindow).webkitAudioContext;
    if (!AC) return;
    const ac = new AC();
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.connect(gain);
    gain.connect(ac.destination);
    osc.type = 'sine';
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.0, ac.currentTime);
    gain.gain.linearRampToValueAtTime(0.12, ac.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, ac.currentTime + 0.7);
    osc.start(ac.currentTime);
    osc.stop(ac.currentTime + 0.7);
    osc.onended = () => ac.close();
  } catch { /* Web Audio unavailable */ }
}

type ViewMode = 'map' | '3d' | 'orbit' | 'ar' | 'cam';
type ThreeDMode = 'orbit' | 'immersive' | 'arSense';

export interface NarrativeViewerProps {
  title: string;
  anchorsUrl: string;
  pointCloudUrl: string;
  semanticGraphUrl?: string;
  trajectoryUrl?: string;
  onGpsStatusChange?: (status: 'waiting' | 'active' | 'error' | 'too_far') => void;
  lang?: string;
  onLangChange?: (lang: 'en' | 'it' | 'es') => void;
  gender?: string;
  onGenderChange?: (gender: 'm' | 'f') => void;
}

// ── GPS marker: droplet pin + ground shadow + compass heading cone ───────────
const DROPLET_PROFILE = (() => {
  const pts = [
    [0.00, 0.00], [0.15, 0.20], [0.35, 0.50], [0.45, 0.80],
    [0.40, 1.10], [0.25, 1.30], [0.00, 1.50],
  ];
  return pts.map(([x, y]) => new THREE.Vector2(x, y));
})();
const COMPASS_CONE_HALF_ANGLE = Math.PI / 8;

function GpsMarker({
  pos,
  compassAlpha,
  mode,
  northRotation,
  zFlipped,
}: {
  pos: { x: number; y: number; z: number };
  compassAlpha: number | null;
  mode: 'iso' | 'orbit';
  northRotation: number;
  zFlipped: boolean;
}) {
  const dropletGeo = useMemo(() => new THREE.LatheGeometry(DROPLET_PROFILE, 16), []);

  const { coneGeo, coneLineObj } = useMemo(() => {
    const len = mode === 'orbit' ? 3.5 : 6;
    const sx = Math.sin(COMPASS_CONE_HALF_ANGLE) * len;
    const sy = Math.cos(COMPASS_CONE_HALF_ANGLE) * len;
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    shape.lineTo(sx, sy);
    shape.lineTo(0, len * 0.92);
    shape.lineTo(-sx, sy);
    shape.closePath();
    const pts = [[0, 0], [sx, sy], [0, len * 0.92], [-sx, sy], [0, 0]];
    const verts = new Float32Array(pts.length * 3);
    pts.forEach(([px, py], i) => { verts[i * 3] = px; verts[i * 3 + 1] = py; verts[i * 3 + 2] = 0; });
    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
    const lineMat = new THREE.LineBasicMaterial({ color: '#4488ff', opacity: 0.85, transparent: true });
    const lineObj = new THREE.Line(lineGeo, lineMat);
    lineObj.rotation.x = -Math.PI / 2;
    lineObj.position.y = 0.03;
    return { coneGeo: new THREE.ShapeGeometry(shape), coneLineObj: lineObj };
  }, [mode]);

  const headingRotY = useMemo(() => {
    if (compassAlpha === null) return null;
    const rad = THREE.MathUtils.degToRad(compassAlpha);
    // Z-flipped parent (MAP/3D non-baked): Ry(NR)*S(1,1,-1) mirrors heading → NR - rad
    // Identity parent (ORBIT, or baked ISO): geographic→SLAM needs +π offset → rad + π - NR
    return zFlipped ? northRotation - rad : rad + Math.PI - northRotation;
  }, [compassAlpha, northRotation, zFlipped]);

  const scale = mode === 'iso' ? 1.5 : 1.0;

  return (
    <group position={[pos.x, pos.y, pos.z]}>
      {/* Pulsing glow — Html overlay, always on top of point cloud */}
      <Html center style={{ pointerEvents: 'none' }} zIndexRange={[50, 0]}>
        <div className="gps-marker-glow" />
      </Html>

      {/* Droplet body */}
      <mesh geometry={dropletGeo} scale={[scale, scale, scale]} renderOrder={999}>
        <meshBasicMaterial color="#4488ff" opacity={0.9} transparent depthTest={false} depthWrite={false} />
      </mesh>
      {/* Droplet outline — solid bright edge */}
      <lineSegments scale={[scale, scale, scale]} renderOrder={1000}>
        <edgesGeometry args={[dropletGeo, 30]} />
        <lineBasicMaterial color="#88ccff" opacity={1} transparent depthTest={false} />
      </lineSegments>

      {/* Compass heading cone: outline in ISO, outline+fill in ORBIT */}
      {headingRotY !== null && (
        <group rotation={[0, headingRotY, 0]}>
          <primitive object={coneLineObj} />
          {mode === 'orbit' && (
            <mesh geometry={coneGeo} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.03, 0]}>
              <meshBasicMaterial color="#4488ff" opacity={0.3} transparent depthWrite={false} side={THREE.DoubleSide} />
            </mesh>
          )}
        </group>
      )}
    </group>
  );
}

// Frames the entire point cloud in bird's-eye view using world-space bounding box.
function RecenterToCloud({
  signal,
  controlsRef,
}: {
  signal: number;
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
}) {
  const { camera, scene } = useThree();

  useEffect(() => {
    if (signal === 0) return;

    scene.updateMatrixWorld(true);

    const box = new THREE.Box3();
    let hasPoints = false;

    scene.traverse((obj) => {
      if (obj instanceof THREE.Points && obj.geometry) {
        obj.geometry.computeBoundingBox();
        const localBox = obj.geometry.boundingBox;
        if (localBox) {
          box.union(localBox.clone().applyMatrix4(obj.matrixWorld));
          hasPoints = true;
        }
      }
    });

    if (!hasPoints || box.isEmpty()) return;

    const center = new THREE.Vector3();
    box.getCenter(center);
    const size = new THREE.Vector3();
    box.getSize(size);
    const radius = Math.max(size.x, size.y, size.z) * 0.6;
    const camDist = Math.max(radius * 2.2, 5);

    camera.position.set(
      center.x + camDist * 0.15,
      center.y + camDist,
      center.z + camDist * 0.25,
    );

    const controls = controlsRef.current;
    if (controls) {
      controls.target.copy(center);
      controls.update();
    }
  }, [signal, camera, scene, controlsRef]);

  return null;
}

// ── Cinematic fly-in for ORBIT mode ──────────────────────────────────────────
// Arcs the perspective camera from bird's-eye down to near the user's GPS
// position / heading direction over ~2 s, then hands off to OrbitControls.
const FLY_IN_DURATION = 2.5;
const FLY_IN_HOLD = 0;
const FLY_IN_ARC_HEIGHT = 0;
const FLY_IN_FOV_START = 25;  // narrow FOV at start ≈ ortho-like
const FLY_IN_FOV_END = 70;  // normal persp FOV at landing

const FOLLOW_CAM_DISTANCE = 8;
const FOLLOW_CAM_HEIGHT = 5;
const FOLLOW_CAM_LERP = 0.04;

function OrbitFlyIn({
  active,
  onComplete,
  onDebugStep,
  userSlamPos,
  compassAlpha,
  isoLeafletViewRef,
  controlsRef,
}: {
  active: boolean;
  onComplete: () => void;
  onDebugStep?: (step: number) => void;
  userSlamPos: { x: number; y: number; z: number } | null;
  compassAlpha: number | null;
  isoLeafletViewRef: React.MutableRefObject<IsoLeafletView | null>;
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
}) {
  const { camera, invalidate } = useThree();
  const startRef = useRef(new THREE.Vector3());
  const endRef = useRef(new THREE.Vector3());
  const lookStartRef = useRef(new THREE.Vector3());
  const lookEndRef = useRef(new THREE.Vector3());
  const elapsedRef = useRef(0);
  const runningRef = useRef(false);
  const debugStepRef = useRef(0);
  const userSlamPosRef = useRef(userSlamPos);
  userSlamPosRef.current = userSlamPos;
  const compassAlphaRef = useRef(compassAlpha);
  compassAlphaRef.current = compassAlpha;

  useEffect(() => {
    if (!active) { runningRef.current = false; debugStepRef.current = 0; onDebugStep?.(0); return; }

    // --- Start from the actual camera position (synced to ortho by CameraController) ---
    startRef.current.copy(camera.position);

    const view = isoLeafletViewRef.current;
    if (view) {
      lookStartRef.current.set(view.slamX, view.slamY, view.slamZ);
    } else {
      lookStartRef.current.set(
        camera.position.x,
        camera.position.y - ISO_H,
        camera.position.z - ISO_D,
      );
    }

    // --- Compute end position (snapshot GPS/compass from refs) ---
    const gps = userSlamPosRef.current;
    const alpha = compassAlphaRef.current;

    if (gps && alpha !== null) {
      // Land exactly where FollowCamera will hold — seamless handoff
      const headingRad = THREE.MathUtils.degToRad(alpha);
      const behindX = gps.x - Math.sin(headingRad) * FOLLOW_CAM_DISTANCE;
      const behindZ = gps.z - Math.cos(headingRad) * FOLLOW_CAM_DISTANCE;
      endRef.current.set(behindX, gps.y + FOLLOW_CAM_HEIGHT, behindZ);
      lookEndRef.current.set(
        gps.x + Math.sin(headingRad) * FOLLOW_CAM_DISTANCE * 0.5,
        gps.y + FOLLOW_CAM_HEIGHT * 0.5,
        gps.z + Math.cos(headingRad) * FOLLOW_CAM_DISTANCE * 0.5,
      );
    } else if (gps) {
      endRef.current.set(gps.x + 3, gps.y + FOLLOW_CAM_HEIGHT, gps.z + 3);
      lookEndRef.current.set(gps.x, gps.y, gps.z);
    } else {
      // No GPS — land 30% lower, same look target
      const sx = startRef.current.x;
      const sy = startRef.current.y;
      const sz = startRef.current.z;
      const lx = lookStartRef.current.x;
      const ly = lookStartRef.current.y;
      const lz = lookStartRef.current.z;
      endRef.current.set(
        sx * 0.85 + lx * 0.15,
        sy * 0.5,
        sz * 0.85 + lz * 0.15,
      );
      lookEndRef.current.set(lx, ly, lz);
    }

    elapsedRef.current = 0;
    runningRef.current = true;
    debugStepRef.current = 1;
    onDebugStep?.(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useFrame((_, delta) => {
    if (!runningRef.current) return;
    invalidate();

    elapsedRef.current += delta;
    const totalDuration = FLY_IN_HOLD + FLY_IN_DURATION;
    const overall = Math.min(elapsedRef.current / totalDuration, 1);

    // Debug step tracking (1→2 at 25%, 2→3 at 60%, 3→4 at completion)
    const newStep = overall >= 1 ? 4 : overall > 0.6 ? 3 : overall > 0.25 ? 2 : 1;
    if (newStep !== debugStepRef.current) {
      debugStepRef.current = newStep;
      onDebugStep?.(newStep);
    }

    // Hold phase: camera stays at bird's-eye start position
    const animT = Math.max(0, (elapsedRef.current - FLY_IN_HOLD) / FLY_IN_DURATION);
    const raw = Math.min(animT, 1);
    // Cubic ease-in-out
    const t = raw < 0.5
      ? 4 * raw * raw * raw
      : 1 - Math.pow(-2 * raw + 2, 3) / 2;

    const s = startRef.current;
    const e = endRef.current;

    // Animate FOV from narrow (ortho-like) to full perspective
    if ('fov' in camera) {
      (camera as THREE.PerspectiveCamera).fov = FLY_IN_FOV_START + (FLY_IN_FOV_END - FLY_IN_FOV_START) * t;
      (camera as THREE.PerspectiveCamera).updateProjectionMatrix();
    }

    // X/Z: linear lerp. Y: quadratic bezier with arc hump.
    const midY = Math.max(s.y, e.y) + FLY_IN_ARC_HEIGHT;
    const x = s.x + (e.x - s.x) * t;
    const y = (1 - t) * (1 - t) * s.y + 2 * (1 - t) * t * midY + t * t * e.y;
    const z = s.z + (e.z - s.z) * t;
    camera.position.set(x, y, z);

    // Lerp lookAt target
    const lx = lookStartRef.current.x + (lookEndRef.current.x - lookStartRef.current.x) * t;
    const ly = lookStartRef.current.y + (lookEndRef.current.y - lookStartRef.current.y) * t;
    const lz = lookStartRef.current.z + (lookEndRef.current.z - lookStartRef.current.z) * t;
    camera.lookAt(lx, ly, lz);

    if (overall >= 1) {
      runningRef.current = false;
      const controls = controlsRef.current;
      if (controls) {
        controls.target.set(lx, ly, lz);
        controls.update();
      }
      onComplete();
    }
  });

  return null;
}

// ── Follow camera: compass-tracked RPG overhead view ──────────────────────────
function FollowCamera({
  active,
  userSlamPos,
  compassAlpha,
  northRotation,
  controlsRef,
}: {
  active: boolean;
  userSlamPos: { x: number; y: number; z: number } | null;
  compassAlpha: number | null;
  northRotation: number;
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
}) {
  const { camera, invalidate } = useThree();
  const wasActiveRef = useRef(false);

  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    if (active) {
      controls.enableRotate = false;
    } else if (wasActiveRef.current) {
      controls.enableRotate = true;
    }
    wasActiveRef.current = active;
  }, [active, controlsRef]);

  useFrame(() => {
    if (!active || !userSlamPos) return;
    const controls = controlsRef.current;
    if (!controls) return;

    const hasHeading = compassAlpha !== null;
    const headingRad = hasHeading
      ? THREE.MathUtils.degToRad(compassAlpha!) - northRotation
      : 0;

    const targetX = userSlamPos.x;
    const targetY = userSlamPos.y + AR_EYE_HEIGHT_M * 0.5;
    const targetZ = userSlamPos.z;

    let desiredX: number, desiredY: number, desiredZ: number;
    if (hasHeading) {
      desiredX = userSlamPos.x - Math.sin(headingRad) * FOLLOW_CAM_DISTANCE;
      desiredY = userSlamPos.y + FOLLOW_CAM_HEIGHT;
      desiredZ = userSlamPos.z - Math.cos(headingRad) * FOLLOW_CAM_DISTANCE;
    } else {
      desiredX = camera.position.x;
      desiredY = userSlamPos.y + FOLLOW_CAM_HEIGHT;
      desiredZ = camera.position.z;
    }

    const k = FOLLOW_CAM_LERP;
    camera.position.x += (desiredX - camera.position.x) * k;
    camera.position.y += (desiredY - camera.position.y) * k;
    camera.position.z += (desiredZ - camera.position.z) * k;

    controls.target.x += (targetX - controls.target.x) * k;
    controls.target.y += (targetY - controls.target.y) * k;
    controls.target.z += (targetZ - controls.target.z) * k;

    controls.update();
    invalidate();
  });

  return null;
}

function DoubleClickFocus({ controlsRef }: { controlsRef: React.RefObject<OrbitControlsImpl | null> }) {
  const { camera, gl } = useThree();

  useEffect(() => {
    const canvas = gl.domElement;

    const onDblClick = (e: MouseEvent) => {
      const controls = controlsRef.current;
      if (!controls) return;

      const rect = canvas.getBoundingClientRect();
      const ndcX = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const ndcY = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), camera);

      const currentDist = camera.position.distanceTo(controls.target);
      const newTarget = new THREE.Vector3();
      raycaster.ray.at(currentDist, newTarget);

      controls.target.copy(newTarget);
      controls.update();
    };

    canvas.addEventListener('dblclick', onDblClick);
    return () => canvas.removeEventListener('dblclick', onDblClick);
  }, [camera, gl, controlsRef]);

  return null;
}

function OrbitAutoRecenter({
  controlsRef,
  active,
}: {
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
  active: boolean;
}) {
  const { camera, scene, invalidate } = useThree();
  const interactingRef = useRef(false);
  const idleStartRef = useRef(0);
  const doneRef = useRef(false);

  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;
    const onStart = () => { interactingRef.current = true; doneRef.current = false; };
    const onEnd = () => { interactingRef.current = false; idleStartRef.current = performance.now(); };
    controls.addEventListener('start', onStart);
    controls.addEventListener('end', onEnd);
    return () => {
      controls.removeEventListener('start', onStart);
      controls.removeEventListener('end', onEnd);
    };
  }, [controlsRef]);

  const raycaster = useMemo(() => {
    const rc = new THREE.Raycaster();
    rc.params.Points = { threshold: 0.5 };
    return rc;
  }, []);
  const screenCenter = useMemo(() => new THREE.Vector2(0, 0), []);

  useFrame(() => {
    if (!active || interactingRef.current || doneRef.current) return;
    const controls = controlsRef.current;
    if (!controls || idleStartRef.current === 0) return;
    if (performance.now() - idleStartRef.current < 500) return;

    raycaster.setFromCamera(screenCenter, camera);
    const intersects: THREE.Intersection[] = [];
    scene.traverse((obj) => {
      if (obj instanceof THREE.Points) {
        const hits = raycaster.intersectObject(obj);
        intersects.push(...hits);
      }
    });

    if (intersects.length > 0) {
      intersects.sort((a, b) => a.distance - b.distance);
      controls.target.copy(intersects[0].point);
      controls.update();
      invalidate();
    }

    doneRef.current = true;
  });

  return null;
}

// Recovers from WebGL context loss: preventDefault keeps the context recoverable;
// invalidate on restore triggers one re-render so R3F repaints after recovery.
function WebGLContextRecovery() {
  const { gl, invalidate } = useThree();
  useEffect(() => {
    const canvas = gl.domElement;
    const onLost = (e: Event) => { e.preventDefault(); };
    const onRestored = () => { invalidate(); };
    canvas.addEventListener('webglcontextlost', onLost);
    canvas.addEventListener('webglcontextrestored', onRestored);
    return () => {
      canvas.removeEventListener('webglcontextlost', onLost);
      canvas.removeEventListener('webglcontextrestored', onRestored);
    };
  }, [gl, invalidate]);
  return null;
}

// Disposes GPU resources on unmount (recording change or CAM↔cloud switch).
// forceContextLoss removed: the canvas now persists across MAP/3D/AR, so
// forceContextLoss was racing the remount and producing "context already lost".
function ContextDisposer() {
  const { gl } = useThree();
  useEffect(() => {
    return () => { gl.dispose(); };
  }, [gl]);
  return null;
}



// Keeps the canvas rendering every frame in MAP mode so Leaflet-driven panning
// and anchor pulse animations are smooth (mirrors old TopDownPointCloud Canvas
// which used frameloop="always"). Not mounted in 3D/AR — those use demand rendering.
function IsoAnimator() {
  const { invalidate } = useThree();
  useFrame(() => { invalidate(); });
  return null;
}

// Kicks a burst of invalidation frames when viewMode changes — ensures the canvas
// repaints after being un-hidden from CAM (frameloop="demand" won't render otherwise).
function ViewModeInvalidator({ viewMode }: { viewMode: string }) {
  const { invalidate } = useThree();
  const countRef = useRef(0);
  useEffect(() => { countRef.current = 10; }, [viewMode]);
  useFrame(() => {
    if (countRef.current > 0) {
      countRef.current--;
      invalidate();
    }
  });
  return null;
}

// ── ISO anchor marker (colour/size scheme from TopDownPointCloud) ─────────────
function AnchorMarker({
  anchor, selected, proximity, isPlaying, isHeard,
}: {
  anchor: AnchorType;
  selected: boolean;
  proximity?: ProximityCategory;
  isPlaying: boolean;
  isHeard: boolean;
}) {
  const groupRef = useRef<THREE.Group>(null);
  const { invalidate } = useThree();

  useFrame(({ camera, clock }) => {
    if (!groupRef.current) return;
    groupRef.current.quaternion.copy(camera.quaternion);
    if (isPlaying) {
      groupRef.current.scale.setScalar(1 + 0.2 * Math.sin(clock.elapsedTime * Math.PI * 3));
      invalidate();
    } else if (proximity === 'in_range') {
      groupRef.current.scale.setScalar(1 + 0.3 * Math.sin(clock.elapsedTime * 5));
      invalidate();
    } else if (proximity === 'discoverable') {
      groupRef.current.scale.setScalar(1 + 0.12 * Math.sin(clock.elapsedTime * 3));
      invalidate();
    } else {
      groupRef.current.scale.setScalar(1);
    }
  });

  const color = isPlaying ? '#00ff88'
    : (selected || proximity === 'in_range') ? '#00ff88'
      : isHeard ? COLOR_HEARD
        : markerColor(anchor.source);
  const opacity = (isHeard && !selected && !isPlaying) ? 0.4
    : proximity === 'distant' ? 0.35 : 1;
  const isMajor = (anchor.score ?? 0) >= 0.35 || anchor.hasAudio;
  const baseSize = isMajor ? 0.35 : 0.25;
  const size = isPlaying ? 0.65 : selected ? 0.6
    : proximity === 'in_range' ? baseSize + 0.2
      : proximity === 'discoverable' ? baseSize + 0.1 : baseSize;

  return (
    <group ref={groupRef} position={[anchor.gx, anchor.gy + 0.5, anchor.gz]}>
      <mesh>
        {isMajor
          ? <circleGeometry args={[size, 24]} />
          : <shapeGeometry args={[(() => { const s = new THREE.Shape(); s.moveTo(0, size); s.lineTo(size, 0); s.lineTo(0, -size); s.lineTo(-size, 0); s.closePath(); return s; })()]} />}
        <meshBasicMaterial color={color} opacity={opacity} transparent depthWrite={false} />
      </mesh>
      <mesh>
        {isMajor
          ? <ringGeometry args={[size * 0.85, size * 1.6, 24]} />
          : <ringGeometry args={[size * 0.85, size * 1.6, 4, 1, Math.PI / 4]} />}
        <meshBasicMaterial color={color} opacity={opacity * 0.15} transparent depthWrite={false} />
      </mesh>
    </group>
  );
}

// IsoUserMarker removed — replaced by unified GpsMarker above

// ── CameraController ───────────────────────────────────────────────────────────
// Creates one OrthographicCamera (MAP) and one PerspectiveCamera (3D/AR) as
// persistent objects inside the single shared Canvas. Swaps the active camera
// without unmounting the Canvas, so the PointCloud loads ONCE and persists
// across all MAP↔3D↔AR switches. Also drives the iso camera every frame (replaces
// the old IsoCameraSync from TopDownPointCloud).
function CameraController({
  viewMode,
  isoLeafletViewRef,
  isoFallback,
}: {
  viewMode: ViewMode;
  isoLeafletViewRef: React.MutableRefObject<IsoLeafletView | null>;
  isoFallback: { x: number; y: number; z: number };
}) {
  const { set, size } = useThree();

  // Both cameras are created once and live for the lifetime of the Canvas.
  const ortho = useMemo(() => {
    const cam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 5000);
    cam.zoom = 5;
    return cam;
  }, []);

  const persp = useMemo(() => {
    const cam = new THREE.PerspectiveCamera(70, 1, 0.01, 5000);
    cam.position.set(0, 10, 0);
    return cam;
  }, []);

  // Swap the active camera before first paint — prevents one-frame wrong-camera flash.
  // map + 3d both use the iso ortho camera; orbit/ar/cam use perspective.
  // On orbit entry: copy ortho position/orientation to persp so the fly-in starts
  // from the same viewpoint. The dip-to-dark overlay hides the projection change;
  // the FOV dolly-zoom in OrbitFlyIn handles the visual transition.
  const sizeRef = useRef(size);
  sizeRef.current = size;
  const prevViewModeRef = useRef(viewMode);

  useLayoutEffect(() => {
    const prev = prevViewModeRef.current;
    if (viewMode === 'map' || viewMode === '3d') {
      set({ camera: ortho });
    } else if (prev === 'map' || prev === '3d' || prev === 'cam') {
      persp.fov = FLY_IN_FOV_START;
      persp.updateProjectionMatrix();
      persp.position.copy(ortho.position);
      persp.quaternion.copy(ortho.quaternion);
      set({ camera: persp });
    } else {
      set({ camera: persp });
    }
    prevViewModeRef.current = viewMode;
  }, [viewMode, ortho, persp, set]);

  // Keep both cameras' projection matrices in sync with canvas size.
  useEffect(() => {
    ortho.left = -size.width / 2;
    ortho.right = size.width / 2;
    ortho.top = size.height / 2;
    ortho.bottom = -size.height / 2;
    ortho.updateProjectionMatrix();
    persp.aspect = size.width / size.height;
    persp.updateProjectionMatrix();
  }, [size, ortho, persp]);

  // Smooth camera for ~600ms after viewMode change (absorbs invalidateSize jump).
  const smoothUntilRef = useRef(0);
  useEffect(() => {
    smoothUntilRef.current = performance.now() + 800;
  }, [viewMode]);

  // Drive the iso (ortho) camera every frame in MAP and 3D modes.
  // 3D uses the same iso/top-down locked view, just on the dominant panel.
  useFrame(() => {
    if (viewMode !== 'map' && viewMode !== '3d') return;
    const view = isoLeafletViewRef.current;
    let tx: number, ty: number, tz: number, zoom: number;
    if (view) {
      tx = view.slamX; ty = view.slamY; tz = view.slamZ;
      const groundWidthSLAM = view.groundWidthM * view.geoScale;
      zoom = groundWidthSLAM > 0 ? size.width / groundWidthSLAM : 5;
    } else {
      tx = isoFallback.x; ty = isoFallback.y; tz = isoFallback.z;
      zoom = 5;
    }

    const smoothing = performance.now() < smoothUntilRef.current;
    if (smoothing) {
      const f = 0.12;
      ortho.position.x += (tx - ortho.position.x) * f;
      ortho.position.y += ((ty + ISO_H) - ortho.position.y) * f;
      ortho.position.z += ((tz + ISO_D) - ortho.position.z) * f;
      ortho.zoom += (zoom - ortho.zoom) * f;
    } else {
      ortho.position.set(tx, ty + ISO_H, tz + ISO_D);
      ortho.zoom = zoom;
    }
    ortho.lookAt(
      ortho.position.x,
      ortho.position.y - ISO_H,
      ortho.position.z - ISO_D,
    );
    ortho.updateProjectionMatrix();
  });

  return null;
}

// Drives camera from device orientation in immersive mode (existing 1:1 mode)
function ImmersiveCamera({
  alpha,
  beta,
  initialPos,
  recenterSignal,
}: {
  alpha: number | null;
  beta: number | null;
  initialPos: { x: number; y: number; z: number } | null;
  recenterSignal: number;
}) {
  const { camera, invalidate } = useThree();
  const posRef = useRef<THREE.Vector3 | null>(null);

  useEffect(() => {
    if (initialPos) {
      const pos = new THREE.Vector3(initialPos.x, initialPos.y, initialPos.z);
      posRef.current = pos;
      camera.position.copy(pos);
      if ((camera as THREE.PerspectiveCamera).fov !== undefined) {
        (camera as THREE.PerspectiveCamera).fov = 70;
      }
      camera.updateProjectionMatrix();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recenterSignal, camera]);

  useFrame(() => {
    if (posRef.current) camera.position.copy(posRef.current);

    const yaw = alpha !== null ? THREE.MathUtils.degToRad(alpha) : 0;
    const pitchDeg = beta !== null ? beta - 90 : 0;
    const pitch = THREE.MathUtils.degToRad(pitchDeg);

    const euler = new THREE.Euler(pitch, -yaw, 0, 'YXZ');
    camera.quaternion.setFromEuler(euler);
    // Keep the render loop alive while device orientation is driving the camera.
    invalidate();
  });

  return null;
}

// Drives camera in AR Sense mode: GPS-glided + rail-snapped position + damped orientation.
// snappedSlamPos is pre-computed in the parent (GPS glide + rail snap in SLAM world coords).
// camera.y = snappedSlamPos.y + heightOffset  (medianWy + heightOffset from slider)
function ArSenseCamera({
  dampedQRef,
  snappedSlamPos,
  heightOffset,
}: {
  dampedQRef: React.MutableRefObject<THREE.Quaternion | null>;
  snappedSlamPos: { x: number; y: number; z: number } | null;
  heightOffset: number;
}) {
  const { camera, invalidate } = useThree();
  const posRef = useRef(snappedSlamPos);
  const hRef = useRef(heightOffset);

  useEffect(() => { posRef.current = snappedSlamPos; }, [snappedSlamPos]);
  useEffect(() => { hRef.current = heightOffset; }, [heightOffset]);

  useEffect(() => {
    camera.quaternion.copy(AR_INITIAL_CAM_Q);
    if ((camera as THREE.PerspectiveCamera).fov !== undefined) {
      (camera as THREE.PerspectiveCamera).fov = 70;
    }
    camera.updateProjectionMatrix();
  }, [camera]);

  useFrame(() => {
    const pos = posRef.current;
    if (pos) {
      // pos.y = medianWy (from geoReg.toSlam); heightOffset = eye-level fine-tune
      camera.position.set(pos.x, pos.y + hRef.current, pos.z);
    }
    const q = dampedQRef.current;
    if (q) camera.quaternion.copy(q);
    // Keep the render loop alive while AR sense is active.
    invalidate();
  });

  return null;
}

export const NarrativeViewer = ({ title: _title, anchorsUrl, pointCloudUrl, semanticGraphUrl, trajectoryUrl, onGpsStatusChange, lang, onLangChange, gender, onGenderChange }: NarrativeViewerProps) => {
  const [anchors, setAnchors] = useState<AnchorType[]>([]);
  const [graphData, setGraphData] = useState<SemanticGraphData | null>(null);
  const [selectedAnchor, setSelectedAnchor] = useState<AnchorType | null>(null);
  const [selectedLinkIndex, setSelectedLinkIndex] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [clusterFan, setClusterFan] = useState<{ anchors: AnchorType[]; screenX: number; screenY: number } | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('map');
  const [threeDMode, setThreeDMode] = useState<ThreeDMode>('orbit');
  const [showIosOverlay, setShowIosOverlay] = useState(false);
  const [pendingIosMode, setPendingIosMode] = useState<'ar' | 'cam' | null>(null);
  const [immersiveRecenterSignal] = useState(0);
  const [mapFollowMode, setMapFollowMode] = useState(true);
  const gpsAutoFollowDone = useRef(false);
  const [recenterCloudSignal, setRecenterCloudSignal] = useState(0);
  const [flyInActive, setFlyInActive] = useState(false);
  const [orbitDip, setOrbitDip] = useState(false);
  const [skipFlexTransition, setSkipFlexTransition] = useState(false);
  const [followVisitor, setFollowVisitor] = useState(false);
  const [arIdleCountdown, setArIdleCountdown] = useState<number | null>(null);
  const [fadeEnabled, setFadeEnabled] = useState(true);
  const [fadeEnd, setFadeEnd] = useState(18); // metres; camera-distance fade floor at 0.05
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showOriginalTranscript, setShowOriginalTranscript] = useState(false);
  const [showIntro, setShowIntro] = useState(() => !localStorage.getItem('eyesof:introDismissed'));
  const dismissIntro = useCallback(() => {
    setShowIntro(false);
    localStorage.setItem('eyesof:introDismissed', '1');
  }, []);
  const [proximityAutoPlay, setProximityAutoPlay] = useState<boolean>(() => {
    try { return localStorage.getItem('eyesof:proximityAutoPlay') === 'true'; }
    catch { return false; }
  });
  const [arAutoReturn, setArAutoReturn] = useState(() => {
    try { return localStorage.getItem('eyesof:ar-autoreturn') !== 'false'; } catch { return true; }
  });
  // Persisted top-level mode preference ('3d' or 'ar') — restored when re-entering the 3D family.
  const [preferredThreeDMode, setPreferredThreeDMode] = useState<'3d' | 'ar'>(() => {
    try {
      const stored = localStorage.getItem('eyesof:last3dmode');
      return stored === 'ar' || stored === 'arSense' ? 'ar' : '3d';
    } catch { return '3d'; }
  });
  const [gazeOverlayData, setGazeOverlayData] = useState<GazeOverlayData | null>(null);
  const [showGazeBeams, setShowGazeBeams] = useState(true);
  const [showTouchMarks, setShowTouchMarks] = useState(true);
  const [showAnchorMarks, setShowAnchorMarks] = useState(true);
  const [showWelcome, setShowWelcome] = useState(() => localStorage.getItem('eyesof:heard_intro') !== 'true');
  const [camShowGaze, setCamShowGaze] = useState(true);
  const [camShowTouch, setCamShowTouch] = useState(true);
  const [selectedTouch, setSelectedTouch] = useState<import('../types').TouchOverlay | null>(null);
  const [selectedGaze, setSelectedGaze] = useState<import('../types').GazeOverlay | null>(null);
  const [attentionDetail, setAttentionDetail] = useState<{ type: 'gaze'; overlay: import('../types').GazeOverlay } | { type: 'touch'; overlay: import('../types').TouchOverlay } | null>(null);
  const [bubbleMap, setBubbleMap] = useState<Map<number, { gaze?: string; touch?: string }>>(new Map());

  useEffect(() => {
    if (attentionDetail && viewMode !== 'orbit' && viewMode !== '3d') {
      setSelectedGaze(null); setSelectedTouch(null);
    }
  }, [attentionDetail, viewMode]);

  const controlsRef = useRef<OrbitControlsImpl | null>(null);
  const cloudPanelRef = useRef<HTMLDivElement>(null);
  const lastMotionTimeRef = useRef(Date.now());
  const prevSmoothedRef = useRef<{ alpha: number; beta: number; gamma: number } | null>(null);
  // ISO gesture state: drag → Leaflet.panBy, pinch → Leaflet.setZoom
  const isoPointerRef = useRef<{ x: number; y: number } | null>(null);
  const isoPinchRef = useRef<{ dist: number } | null>(null);

  const rawOrientation = useDeviceOrientation();
  const {
    audioEnabled, toggleAudio,
    playAnchor, playAnchorWithUnlock, isPlaying, pauseAudio, resumeAudio, lastEndedId, currentAnchorId: playingAnchorId, setNowPlayingTitle,
  } = useAudio();
  const { aiEnabled, toggleAI, clearMemory, sessionMemory, recordVisit } = useAI();

  // Recording ID derived from anchorsUrl (e.g. "/recordings/riva1/…" → "riva1")
  const recordingId = useMemo(
    () => anchorsUrl.replace(/^\/recordings\//, '').split('/')[0],
    [anchorsUrl],
  );

  // Derive recording base URL from anchorsUrl (e.g. "/recordings/riva1")
  const recordingBaseUrl = useMemo(() => anchorsUrl.replace(/\/[^/]+$/, ''), [anchorsUrl]);

  // Compass offset: corrects per-device heading differences (e.g. Pixel = 180° off Samsung).
  // Persisted globally — same device always needs the same offset regardless of recording.
  const [compassOffset, setCompassOffset] = useState(0);
  useEffect(() => {
    try {
      const stored = localStorage.getItem('eyesof:compassOffset');
      if (stored !== null) setCompassOffset(Number(stored));
    } catch { /* localStorage unavailable */ }
  }, []);
  useEffect(() => {
    try { localStorage.setItem('eyesof:compassOffset', String(compassOffset)); }
    catch { /* ignore */ }
  }, [compassOffset]);

  // Apply compass offset to raw orientation — all consumers use this, not rawOrientation
  const orientation = useMemo(() => ({
    ...rawOrientation,
    alpha: rawOrientation.alpha !== null
      ? ((rawOrientation.alpha + compassOffset) % 360 + 360) % 360
      : null,
  }), [rawOrientation, compassOffset]);

  // Height offset: camera y = medianWy + heightOffset. Defaults to AR_EYE_HEIGHT_M.
  // Persisted per-recording; gated by setupMode so visitors cannot accidentally move it.
  const [heightOffset, setHeightOffset] = useState(AR_EYE_HEIGHT_M);
  useEffect(() => {
    try {
      const stored = localStorage.getItem(`eyesof:height:${recordingId}`);
      if (stored !== null) setHeightOffset(Number(stored));
    } catch { /* localStorage unavailable */ }
  }, [recordingId]);
  useEffect(() => {
    try {
      localStorage.setItem(`eyesof:height:${recordingId}`, String(heightOffset));
    } catch { /* ignore */ }
  }, [recordingId, heightOffset]);

  // ── AR height swipe ──────────────────────────────────────────────────────────
  // Ref keeps latest heightOffset accessible in stable callbacks without extra deps
  const heightOffsetRef = useRef(heightOffset);
  useEffect(() => { heightOffsetRef.current = heightOffset; }, [heightOffset]);

  const [heightReadout, setHeightReadout] = useState<number | null>(null);
  const [heightReadoutFading, setHeightReadoutFading] = useState(false);
  const heightReadoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const swipeGestureRef = useRef<{ startY: number; startHeight: number; isDrag: boolean } | null>(null);

  useEffect(() => {
    try { localStorage.setItem('eyesof:ar-autoreturn', String(arAutoReturn)); } catch { }
  }, [arAutoReturn]);
  useEffect(() => {
    try { localStorage.setItem('eyesof:proximityAutoPlay', String(proximityAutoPlay)); } catch { }
  }, [proximityAutoPlay]);
  useEffect(() => {
    try { localStorage.setItem('eyesof:last3dmode', preferredThreeDMode); } catch { }
  }, [preferredThreeDMode]);

  const arSense = useDampedDeviceOrientation(
    viewMode === 'ar',
    AR_INITIAL_CAM_Q,
    AR_YAW_FACTOR,
    AR_PITCH_FACTOR,
    AR_HORIZON_LOCK,
    AR_HORIZON_PITCH_DEG,
  );

  // CAM orientation: full 3DoF — NO horizon lock, full pitch (1.0) to track real camera tilt
  const camSense = useDampedDeviceOrientation(
    viewMode === 'cam',
    CAM_INITIAL_Q,
    AR_YAW_FACTOR,
    1.0,
    false,
    0,
  );

  // ── Trajectory + GPS + geo-registration ──
  const [trajectoryData, setTrajectoryData] = useState<TrajectoryData | null>(null);
  const [trajectoryError, setTrajectoryError] = useState(false);
  const [devicePos, setDevicePos] = useState<{ lat: number; lon: number } | null>(null);
  const [glidedDevicePos, setGlidedDevicePos] = useState<{ lat: number; lon: number } | null>(null);
  const [gpsStatus, setGpsStatus] = useState<'waiting' | 'active' | 'error' | 'too_far'>('waiting');
  useEffect(() => { onGpsStatusChange?.(gpsStatus); }, [gpsStatus, onGpsStatusChange]);
  const [gpsErrorMsg, setGpsErrorMsg] = useState<string | null>(null);
  const watchIdRef = useRef<number | null>(null);
  const gpsForcedRef = useRef(false);
  // EMA accumulator for GPS glide — lives in a ref so the watchPosition callback sees it
  const glidedGpsRef = useRef<{ lat: number; lon: number } | null>(null);

  // ── Iso↔Leaflet coupling ──────────────────────────────────────────────────────
  // Leaflet is the single source of truth for the 2D viewport.  The iso camera
  // reads this ref in useFrame; NarrativeViewer writes it on every Leaflet event.
  const isoLeafletViewRef = useRef<IsoLeafletView | null>(null);
  // Leaflet map instance — set once via TopDownMap's onMapReady callback.
  // Stored as React state so the subscription useEffect re-runs when it arrives.
  const [leafletMap, setLeafletMap] = useState<LeafletMap | null>(null);
  const handleMapReady = useCallback((map: LeafletMap) => {
    setLeafletMap(map);
    // Leaflet may not know its true container size yet (flex layout still settling)
    setTimeout(() => map.invalidateSize(), 100);
    setTimeout(() => map.invalidateSize(), 600);
  }, []);

  // ── GPS debug overlay — only active when ?debug=1 in the URL ──
  const debugMode = useMemo(() => new URLSearchParams(window.location.search).get('debug') === '1', []);
  const gpsAcceptedRef = useRef(0);
  const gpsRejectedRef = useRef(0);
  const [debugGps, setDebugGps] = useState<{
    rawLat: number; rawLon: number; accuracy: number;
    accepted: number; rejected: number;
  } | null>(null);

  const geoReg = useMemo(() => {
    if (!trajectoryData) return null;
    return fitGeoRegistration(trajectoryData.path);
  }, [trajectoryData]);

  const geoRegRef = useRef(geoReg);
  geoRegRef.current = geoReg;

  // ── Subscribe to Leaflet events; derive iso camera state from the map ─────────
  // Fires on every 'move'/'zoom' (including during animations) so the iso camera
  // stays in lockstep with Leaflet panning and pinch-zoom.  Both leafletMap and
  // geoReg are declared above so there are no forward-reference issues.
  useEffect(() => {
    if (!leafletMap || !geoReg) return;

    const syncIso = () => {
      const center = leafletMap.getCenter();
      const slam = geoReg.toSlam(center.lat, center.lng);
      const bounds = leafletMap.getBounds();
      const mc = leafletMap.getCenter();
      const groundWidthM = leafletMap.distance(
        { lat: mc.lat, lng: bounds.getWest() },
        { lat: mc.lat, lng: bounds.getEast() },
      );
      isoLeafletViewRef.current = {
        slamX: slam.x, slamY: slam.y, slamZ: slam.z,
        groundWidthM,
        geoScale: geoReg.scale,
      };
    };

    leafletMap.on('move', syncIso);
    leafletMap.on('zoom', syncIso);
    leafletMap.on('moveend', syncIso);
    leafletMap.on('zoomend', syncIso);
    syncIso(); // seed on first attach

    return () => {
      leafletMap.off('move', syncIso);
      leafletMap.off('zoom', syncIso);
      leafletMap.off('moveend', syncIso);
      leafletMap.off('zoomend', syncIso);
    };
  }, [leafletMap, geoReg]);

  // ── Invalidate Leaflet size after flip-pair CSS transition completes ──────────
  const prevModeForLeaflet = useRef(viewMode);
  useEffect(() => {
    if (!leafletMap) return;
    const fromCam = prevModeForLeaflet.current === 'cam';
    prevModeForLeaflet.current = viewMode;
    if (fromCam) requestAnimationFrame(() => leafletMap.invalidateSize());
    const t = setTimeout(() => leafletMap.invalidateSize(), 550);
    return () => clearTimeout(t);
  }, [viewMode, leafletMap]);

  // ── Iso panel gestures forward to Leaflet (Leaflet stays source of truth) ─────
  // Both panels share the same width (column layout) and geographic zoom, so
  // horizontal panning is 1:1.  Vertical needs the inverse height ratio because
  // the taller 3D panel shows more geographic area per pixel than the shorter map.
  const handleIsoDrag = useCallback((dx: number, dy: number) => {
    if (!leafletMap) return;
    const mapEl = leafletMap.getContainer();
    const mapH = mapEl.clientHeight || 1;
    const cloudEl = mapEl.closest('.flip-pair-container')?.querySelector('.flip-panel-cloud') as HTMLElement | null;
    const cloudH = cloudEl?.clientHeight || mapH;
    const vRatio = mapH / cloudH;
    leafletMap.panBy([-dx, -dy * vRatio] as [number, number], { animate: false });
  }, [leafletMap]);

  const handleIsoPinch = useCallback((scale: number) => {
    if (!leafletMap) return;
    leafletMap.setZoom(leafletMap.getZoom() + Math.log2(scale), { animate: false });
  }, [leafletMap]);

  // Trajectory in SLAM world space — used for rail-snap blend
  const trajectoryXZ = useMemo((): { x: number; y: number; z: number }[] => {
    if (!trajectoryData) return [];
    return trajectoryData.path
      .filter(p => p.wx !== undefined && p.wz !== undefined)
      .map(p => ({ x: p.wx!, y: p.wy ?? 0, z: p.wz! }));
  }, [trajectoryData]);

  // Raw GPS → SLAM (for map + proximity, snaps every reading)
  const userSlamPos = useMemo(() => {
    if (!devicePos || !geoReg) return null;
    return geoReg.toSlam(devicePos.lat, devicePos.lon);
  }, [devicePos, geoReg]);

  // Glided GPS → SLAM (EMA-smoothed lat/lon, for AR camera)
  const glidedSlamPos = useMemo(() => {
    if (!glidedDevicePos || !geoReg) return null;
    return geoReg.toSlam(glidedDevicePos.lat, glidedDevicePos.lon);
  }, [glidedDevicePos, geoReg]);

  // Rail-snap blend: blend glided position toward nearest trajectory point.
  // w=1 when exactly on path, w=0 when > AR_RAIL_RADIUS_M away.
  // Returns { pos, railWeight } so the debug overlay can show the blend weight live.
  const snapResult = useMemo(() => {
    if (!glidedSlamPos) return { pos: null, railWeight: 0 };
    if (!AR_RAIL_SNAP_ENABLED || !geoReg || trajectoryXZ.length === 0) return { pos: glidedSlamPos, railWeight: 0 };

    const railRadiusSlam = AR_RAIL_RADIUS_M * geoReg.scale;

    let nearestDistSq = Infinity;
    let nearestX = glidedSlamPos.x;
    let nearestZ = glidedSlamPos.z;
    for (const pt of trajectoryXZ) {
      const dx = pt.x - glidedSlamPos.x;
      const dz = pt.z - glidedSlamPos.z;
      const dSq = dx * dx + dz * dz;
      if (dSq < nearestDistSq) {
        nearestDistSq = dSq;
        nearestX = pt.x;
        nearestZ = pt.z;
      }
    }
    const nearestDist = Math.sqrt(nearestDistSq);
    const w = Math.max(0, Math.min(1, 1 - nearestDist / railRadiusSlam));

    return {
      pos: {
        x: glidedSlamPos.x + w * (nearestX - glidedSlamPos.x),
        y: glidedSlamPos.y,
        z: glidedSlamPos.z + w * (nearestZ - glidedSlamPos.z),
      },
      railWeight: w,
    };
  }, [glidedSlamPos, trajectoryXZ, geoReg]);
  const snappedSlamPos = snapResult.pos;
  const railWeight = snapResult.railWeight;

  const handleSelectLink = (_link: Link, index: number) => {
    setSelectedLinkIndex(index);
    setSelectedAnchor(null);
  };

  const getSelectedLinkData = () => {
    if (selectedLinkIndex === null || !graphData) return null;
    const link = graphData.links[selectedLinkIndex];
    return { link, source: anchors[link.source], target: anchors[link.target] };
  };

  const dimmedIds = (selectedLinkIndex !== null && graphData)
    ? [graphData.links[selectedLinkIndex].source, graphData.links[selectedLinkIndex].target]
    : [];

  useEffect(() => {
    fetch(anchorsUrl)
      .then(res => res.json())
      .then(data => {
        const list: AnchorType[] = Array.isArray(data) ? data : data.points ?? data.candidates ?? data;
        for (const a of list) {
          if ((a as any).node_id != null && a.id == null) a.id = (a as any).node_id;
          if (a.lat != null && a.lon != null && !a.gps) a.gps = [a.lat, a.lon];
          if ((a as any).narrative && !a.text) a.text = (a as any).narrative;
          if ((a as any).title && !a.narrative_title) a.narrative_title = (a as any).title;
          if (!a.narrative_title && a.text) {
            const t = a.text['en'] || a.text['it'] || Object.values(a.text)[0] || '';
            a.narrative_title = t.length > 60 ? t.slice(0, 57) + '...' : t;
          }
          if (a.placement === 'cloud' && a.gx == null) a.placement = 'map';
        }
        setAnchors(list);
      })
      .catch(err => console.error(`Error loading anchors from ${anchorsUrl}:`, err));
  }, [anchorsUrl]);

  useEffect(() => {
    if (semanticGraphUrl) {
      fetch(semanticGraphUrl)
        .then(res => res.json())
        .then(data => setGraphData(data))
        .catch(err => console.error(`Error loading graph from ${semanticGraphUrl}:`, err));
    }
  }, [semanticGraphUrl]);

  useEffect(() => {
    if (!trajectoryUrl) return;
    fetch(trajectoryUrl)
      .then(r => r.json())
      .then(setTrajectoryData)
      .catch(() => setTrajectoryError(true));
  }, [trajectoryUrl]);

  useEffect(() => {
    if (!trajectoryData || anchors.length === 0) return;
    const needsPatch = anchors.some(a => a.start_ts == null && a.start_sec != null);
    if (!needsPatch) return;
    const path = trajectoryData.path;
    const t0 = path[0].t;
    const tEnd = path[path.length - 1].t;
    const totalSec = trajectoryData.count / trajectoryData.sample_hz;
    let changed = false;
    for (const a of anchors) {
      if (a.start_ts == null && a.start_sec != null) {
        a.start_ts = t0 + (a.start_sec / totalSec) * (tEnd - t0);
        changed = true;
      }
    }
    if (changed) setAnchors([...anchors]);
  }, [trajectoryData, anchors]);

  useEffect(() => {
    if (!geoReg) return;
    const needsEnrich = anchors.some(a => a.gx == null && a.lat != null && a.lon != null);
    if (!needsEnrich) return;
    const enriched = anchors.map(a => {
      if (a.gx != null || a.lat == null || a.lon == null) return a;
      const slam = geoReg.toSlam(a.lat, a.lon);
      return { ...a, gx: slam.x, gy: slam.y, gz: slam.z };
    });
    setAnchors(enriched);
  }, [anchors, geoReg]);

  // Load gaze overlay data if present alongside narrative_anchors.json
  useEffect(() => {
    const url = `${recordingBaseUrl}/gaze_overlay.json`;
    fetch(url)
      .then(r => { if (!r.ok) throw new Error('not found'); return r.json(); })
      .then((data: GazeOverlayData) => setGazeOverlayData(data))
      .catch(() => { /* no overlay data for this recording */ });
  }, [recordingBaseUrl]);

  useEffect(() => {
    fetch(`${recordingBaseUrl}/bubbles_route/bubble_candidates.json`)
      .then(r => { if (!r.ok) throw new Error('not found'); return r.json(); })
      .then(data => {
        const map = new Map<number, { gaze?: string; touch?: string }>();
        const scores = new Map<number, { gaze?: number; touch?: number }>();
        for (const b of (data.candidates ?? [])) {
          const aid = b.anchor_id as string;
          let nodeId: number;
          if (aid.startsWith('c')) {
            nodeId = parseInt(aid.slice(1), 10);
          } else {
            const m = aid.match(/(\d+)$/);
            if (!m) continue;
            nodeId = parseInt(m[1], 10);
          }
          if (isNaN(nodeId)) continue;
          const prevScores = scores.get(nodeId) ?? {};
          const prevScore = prevScores[b.type as 'gaze' | 'touch'] ?? -1;
          if ((b.score as number) <= prevScore) continue;
          const entry = map.get(nodeId) ?? {};
          const thumbImg = (b.img as string).replace('img/', 'thumb/').replace('.png', '.webp');
          (entry as Record<string, string>)[b.type] = `${recordingBaseUrl}/bubbles_route/${thumbImg}`;
          (entry as Record<string, string>)[`${b.type}_full`] = `${recordingBaseUrl}/bubbles_route/${b.img}`;
          map.set(nodeId, entry);
          prevScores[b.type as 'gaze' | 'touch'] = b.score as number;
          scores.set(nodeId, prevScores);
        }
        setBubbleMap(map);
      })
      .catch(() => { });
  }, [recordingBaseUrl]);

  // Assign each touch overlay to its nearest anchor once both datasets are loaded
  useEffect(() => {
    if (!gazeOverlayData || anchors.length === 0) return;
    let changed = false;
    for (const t of gazeOverlayData.touchOverlays) {
      if (t.anchorId != null) continue;
      let minDist = Infinity, closest = -1;
      for (const a of anchors) {
        const d = Math.hypot(t.pos[0] - a.gx, t.pos[1] - a.gy, t.pos[2] - a.gz);
        if (d < minDist) { minDist = d; closest = a.id; }
      }
      if (closest >= 0) { t.anchorId = closest; changed = true; }
    }
    if (changed) setGazeOverlayData({ ...gazeOverlayData });
  }, [gazeOverlayData, anchors]);

  useEffect(() => {
    let hasLocalGps = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connectWs() {
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
      try { ws = new WebSocket(`wss://${window.location.hostname}/gps`); } catch { return; }

      ws.onmessage = (event) => {
        if (hasLocalGps) return;
        try {
          const data = JSON.parse(event.data);
          if (typeof data.lat === 'number' && typeof data.lon === 'number') {
            const reg = geoRegRef.current;
            if (reg && !gpsForcedRef.current) {
              const dist = haversineDist(data.lat, data.lon, reg.centerLat, reg.centerLon);
              if (dist > GPS_TOO_FAR_M) { setGpsStatus('too_far'); return; }
            }
            const prev = glidedGpsRef.current;
            if (!prev) {
              glidedGpsRef.current = { lat: data.lat, lon: data.lon };
            } else {
              glidedGpsRef.current = {
                lat: prev.lat + AR_GPS_GLIDE_ALPHA * (data.lat - prev.lat),
                lon: prev.lon + AR_GPS_GLIDE_ALPHA * (data.lon - prev.lon),
              };
            }
            setDevicePos({ lat: data.lat, lon: data.lon });
            setGlidedDevicePos({ ...glidedGpsRef.current! });
            setGpsStatus('active');
          }
        } catch { /* ignore malformed frames */ }
      };
      ws.onerror = () => { };
      ws.onclose = () => { reconnectTimer = setTimeout(connectWs, 3000); };
    }
    connectWs();

    if (!navigator.geolocation) {
      setGpsStatus('error');
      setGpsErrorMsg('Geolocation not available');
      return () => { if (reconnectTimer) clearTimeout(reconnectTimer); ws?.close(); };
    }

    watchIdRef.current = navigator.geolocation.watchPosition(
      pos => {
        // Capture raw reading for debug overlay before the guard
        if (debugMode) {
          if (pos.coords.accuracy > AR_GPS_MAX_ACCURACY_M) {
            gpsRejectedRef.current += 1;
          } else {
            gpsAcceptedRef.current += 1;
          }
          setDebugGps({
            rawLat: pos.coords.latitude,
            rawLon: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
            accepted: gpsAcceptedRef.current,
            rejected: gpsRejectedRef.current,
          });
        }
        hasLocalGps = true;
        if (pos.coords.accuracy > AR_GPS_MAX_ACCURACY_M) {
          setGpsStatus(prev => prev === 'waiting' ? 'waiting' : prev);
          return;
        }
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;

        // Always broadcast to relay so other devices get position
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ lat, lon }));
        }

        // Gate: if device is far from the recording area, suppress local GPS
        const reg = geoRegRef.current;
        if (reg && !gpsForcedRef.current) {
          const dist = haversineDist(lat, lon, reg.centerLat, reg.centerLon);
          if (dist > GPS_TOO_FAR_M) {
            setGpsStatus('too_far');
            return;
          }
        }

        setGpsStatus('active');
        setDevicePos({ lat, lon });

        if (!gpsAutoFollowDone.current) {
          gpsAutoFollowDone.current = true;
          setMapFollowMode(true);
        }

        // Apply EMA glide — smooth between readings so camera glides, not snaps
        const prev = glidedGpsRef.current;
        if (!prev) {
          glidedGpsRef.current = { lat, lon };
        } else {
          glidedGpsRef.current = {
            lat: prev.lat + AR_GPS_GLIDE_ALPHA * (lat - prev.lat),
            lon: prev.lon + AR_GPS_GLIDE_ALPHA * (lon - prev.lon),
          };
        }
        setGlidedDevicePos({ ...glidedGpsRef.current! });
      },
      err => {
        setGpsStatus('error');
        setGpsErrorMsg(err.message);
      },
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 5000 },
    );

    return () => {
      if (watchIdRef.current !== null) navigator.geolocation.clearWatch(watchIdRef.current);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);

  const isMobile = useIsMobile();

  const proximityMap = useMemo((): Map<number, ProximityCategory> => {
    const map = new Map<number, ProximityCategory>();
    for (const anchor of anchors) {
      if (anchor.gx != null && anchor.gz != null && userSlamPos && geoReg) {
        const dx = anchor.gx - userSlamPos.x;
        const dz = anchor.gz - userSlamPos.z;
        map.set(anchor.id, classifyDistance(Math.sqrt(dx * dx + dz * dz) / geoReg.scale));
      } else if (anchor.gps && devicePos) {
        map.set(anchor.id, classifyDistance(haversineDist(devicePos.lat, devicePos.lon, anchor.gps[0], anchor.gps[1])));
      }
    }
    return map;
  }, [anchors, userSlamPos, geoReg, devicePos]);


  const isImmersive = threeDMode === 'immersive';
  const isArSense = viewMode === 'ar';

  const fadeStart = fadeEnd / 3; // fadeStart ≈ 6 when fadeEnd = 18

  // ── ISO/MAP computed values ──────────────────────────────────────────────────
  const baked = trajectoryData?.baked ?? false;
  const northRotation = useMemo(() => geoReg?.theta ?? 0, [geoReg]);

  const cloudAnchors = useMemo(() => {
    const filtered = anchors.filter(a => a.gx != null && a.gy != null && a.gz != null);
    if (trajectoryXZ.length === 0) return filtered;
    const K = 5, MAX_R = 15;
    return filtered.map(anchor => {
      const nearby: { wy: number; d: number }[] = [];
      for (const pt of trajectoryXZ) {
        const dx = anchor.gx - pt.x, dz = anchor.gz - pt.z;
        const d = Math.sqrt(dx * dx + dz * dz);
        if (d <= MAX_R) nearby.push({ wy: pt.y, d });
      }
      if (nearby.length === 0) return anchor;
      nearby.sort((a, b) => a.d - b.d);
      const top = nearby.slice(0, K);
      let wSum = 0, wySum = 0;
      for (const { wy, d } of top) { const w = 1 / (d + 0.01); wSum += w; wySum += wy * w; }
      return { ...anchor, gy: wySum / wSum };
    });
  }, [anchors, trajectoryXZ]);

  const anchorPositionMap = useMemo(() => {
    const m = new Map<number, THREE.Vector3>();
    for (const a of cloudAnchors) {
      m.set(a.id, new THREE.Vector3(a.gx, a.gy, a.gz));
    }
    return m;
  }, [cloudAnchors]);

  const narrativeAnim = useNarrativeAnimations({
    animations: gazeOverlayData?.animations,
    selectedAnchorId: selectedAnchor?.id ?? null,
  });

  const anchorCentroid = useMemo(() => {
    if (!cloudAnchors.length) return null;
    return {
      x: cloudAnchors.reduce((s, a) => s + a.gx, 0) / cloudAnchors.length,
      y: cloudAnchors.reduce((s, a) => s + a.gy, 0) / cloudAnchors.length,
      z: cloudAnchors.reduce((s, a) => s + a.gz, 0) / cloudAnchors.length,
    };
  }, [cloudAnchors]);

  const isoFallback = useMemo(() => {
    if (userSlamPos) return userSlamPos;
    if (anchorCentroid) return anchorCentroid;
    return { x: 0, y: 0, z: 0 };
  }, [userSlamPos, anchorCentroid]);

  // Immersive camera initial position — eye-level above GPS-mapped floor
  const immersivePos = useMemo(() => {
    if (!userSlamPos) return null;
    return { ...userSlamPos, y: userSlamPos.y + AR_EYE_HEIGHT_M };
  }, [userSlamPos]);

  // ── AR Sense: idle detection and auto-pause countdown ──
  useEffect(() => {
    if (viewMode !== 'ar' || !arAutoReturn) {
      setArIdleCountdown(null);
      prevSmoothedRef.current = null;
      return;
    }

    lastMotionTimeRef.current = Date.now();

    const interval = setInterval(() => {
      const s = arSense.smoothedRef.current;
      const prev = prevSmoothedRef.current;

      if (s && prev) {
        let da = Math.abs(s.alpha - prev.alpha);
        if (da > 180) da = 360 - da;
        const db = Math.abs(s.beta - prev.beta);
        const dg = Math.abs(s.gamma - prev.gamma);
        const maxDelta = Math.max(da, db, dg);

        if (maxDelta > AR_MOTION_THRESHOLD_DEG) {
          lastMotionTimeRef.current = Date.now();
          setArIdleCountdown(null);
        }
      }

      prevSmoothedRef.current = s ? { ...s } : null;

      const idleMs = Date.now() - lastMotionTimeRef.current;

      if (idleMs > AR_IDLE_TIMEOUT_MS) {
        setArIdleCountdown(prev => {
          if (prev === null) return AR_IDLE_COUNTDOWN_MS / 1000;
          if (prev <= 1) return 0;
          return prev - 1;
        });
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [viewMode, arSense.smoothedRef, arAutoReturn]);

  // When countdown hits 0 → revert to follow-visitor map view
  useEffect(() => {
    if (arIdleCountdown === 0) {
      setViewMode('map');
      setFollowVisitor(true);
      setArIdleCountdown(null);
    }
  }, [arIdleCountdown]);

  // Clear AR state when leaving AR mode
  useEffect(() => {
    if (viewMode !== 'ar') {
      setArIdleCountdown(null);
      if (threeDMode === 'arSense') setThreeDMode('orbit');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode]);

  // Skip flex transition when leaving CAM — useLayoutEffect so transition:none
  // is applied before the browser paints (useEffect would allow one frame of animation).
  const prevModeForTransition = useRef(viewMode);
  useLayoutEffect(() => {
    if (prevModeForTransition.current === 'cam' && viewMode !== 'cam') {
      setSkipFlexTransition(true);
      requestAnimationFrame(() => setSkipFlexTransition(false));
    }
    prevModeForTransition.current = viewMode;
  }, [viewMode]);


  // ── Audio: auto-play on anchor selection (tap path) ──
  // Skipped when a gesture path (handleIAmHere, proximity, queue) already called play
  // directly — those set skipAutoPlayRef to prevent the concurrent second play that
  // aborts the first on iOS when the audio Promise is still pending.
  useEffect(() => {
    const aUrl = selectedAnchor ? resolveAudioUrl(selectedAnchor, lang ?? 'en', gender ?? 'f') : null;
    if (!selectedAnchor || !audioEnabled || !aUrl) return;
    if (skipAutoPlayRef.current) { skipAutoPlayRef.current = false; return; }
    setNowPlayingTitle(selectedAnchor.narrative_titles?.[lang || 'en'] ?? selectedAnchor.narrative_title);
    playAnchorWithUnlock(selectedAnchor.id, `${recordingBaseUrl}/${aUrl}`);
    recordVisit(selectedAnchor.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAnchor?.id]);

  // ── Audio: proximity-triggered playback with hysteresis ──
  // anchorProxStateRef: 'outside' = ready to fire; 'inside' = within R_enter
  const anchorProxStateRef = useRef<Map<number, 'outside' | 'inside'>>(new Map());
  const queuedAnchorRef = useRef<{ id: number; url: string; title: string } | null>(null);
  const isPlayingRef = useRef(isPlaying);
  useEffect(() => { isPlayingRef.current = isPlaying; }, [isPlaying]);
  const skipAutoPlayRef = useRef(false);

  const handleAnchorTap = useCallback((anchor: AnchorType) => {
    if (selectedAnchor?.id === anchor.id) {
      if (playingAnchorId === anchor.id && isPlaying) {
        pauseAudio();
      } else if (playingAnchorId === anchor.id) {
        resumeAudio();
      }
      return;
    }
    if (showWelcome) {
      setShowWelcome(false);
      localStorage.setItem('eyesof:heard_intro', 'true');
    }
    setClusterFan(null);
    setSelectedAnchor(anchor);
    setSelectedLinkIndex(null);
  }, [selectedAnchor?.id, playingAnchorId, isPlaying, pauseAudio, resumeAudio, showWelcome]);

  const fireProximityAnchor = useCallback((anchor: AnchorType) => {
    const aUrl = resolveAudioUrl(anchor, lang ?? 'en', gender ?? 'f');
    if (!aUrl) return;
    const url = `${recordingBaseUrl}/${aUrl}`;
    setNowPlayingTitle(anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title);
    skipAutoPlayRef.current = true;
    playAnchor(anchor.id, url);
    recordVisit(anchor.id);
    setSelectedAnchor(anchor);
    playSoftChime();
    try { navigator.vibrate?.([50, 100, 80, 100, 120]); } catch { /* vibrate not available */ }
  }, [recordingBaseUrl, setNowPlayingTitle, playAnchor, recordVisit]);

  useEffect(() => {
    if (!audioEnabled || !proximityAutoPlay || viewMode === 'cam') return;
    if (!userSlamPos && !devicePos) return;
    const visited = new Set(sessionMemory.visitedAnchorIds);

    for (const anchor of anchors) {
      const proxAUrl = resolveAudioUrl(anchor, lang ?? 'en', gender ?? 'f');
      if (!proxAUrl) continue;

      let distM: number | null = null;
      if (anchor.gx != null && anchor.gz != null && userSlamPos && geoReg) {
        const dx = anchor.gx - userSlamPos.x;
        const dz = anchor.gz - userSlamPos.z;
        distM = Math.sqrt(dx * dx + dz * dz) / geoReg.scale;
      } else if (anchor.gps && devicePos) {
        distM = haversineDist(devicePos.lat, devicePos.lon, anchor.gps[0], anchor.gps[1]);
      }
      if (distM == null) continue;

      const state = anchorProxStateRef.current.get(anchor.id) ?? 'outside';

      if (distM < PROX_ENTER_M) {
        if (state === 'outside' && !visited.has(anchor.id)) {
          anchorProxStateRef.current.set(anchor.id, 'inside');
          if (!isPlayingRef.current) {
            fireProximityAnchor(anchor);
          } else {
            queuedAnchorRef.current = { id: anchor.id, url: `${recordingBaseUrl}/${proxAUrl}`, title: anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title };
            setQueuedTitle(anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title);
            try { navigator.vibrate?.([50, 100, 80, 100, 120]); } catch { /* */ }
          }
        }
      } else if (distM > PROX_EXIT_M && state === 'inside') {
        anchorProxStateRef.current.set(anchor.id, 'outside');
      }
    }
  }, [proximityMap, audioEnabled, proximityAutoPlay, geoReg, userSlamPos, devicePos, viewMode, anchors, recordingBaseUrl,
    sessionMemory.visitedAnchorIds, fireProximityAnchor]);

  useEffect(() => {
    if (lastEndedId === null || !queuedAnchorRef.current) return;
    const q = queuedAnchorRef.current;
    queuedAnchorRef.current = null;
    setQueuedTitle(null);
    const anchor = anchors.find(a => a.id === q.id);
    if (!anchor) return;
    let distM: number | null = null;
    if (anchor.gx != null && anchor.gz != null && userSlamPos && geoReg) {
      const dx = anchor.gx - userSlamPos.x;
      const dz = anchor.gz - userSlamPos.z;
      distM = Math.sqrt(dx * dx + dz * dz) / geoReg.scale;
    } else if (anchor.gps && devicePos) {
      distM = haversineDist(devicePos.lat, devicePos.lon, anchor.gps[0], anchor.gps[1]);
    }
    if (distM != null && distM < PROX_EXIT_M && !sessionMemory.visitedAnchorIds.includes(q.id)) {
      setNowPlayingTitle(q.title);
      skipAutoPlayRef.current = true;
      playAnchor(q.id, q.url);
      recordVisit(q.id);
      const a = anchors.find(x => x.id === q.id);
      if (a) setSelectedAnchor(a);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastEndedId]);

  // ── ISO map gesture handlers (drag → Leaflet.panBy, pinch → Leaflet.setZoom) ──
  const handleIsoPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!e.isPrimary) return;
    isoPointerRef.current = { x: e.clientX, y: e.clientY };
    (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
  }, []);

  const handleIsoPointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (!e.isPrimary || !isoPointerRef.current || isoPinchRef.current) return;
    const dx = e.clientX - isoPointerRef.current.x;
    const dy = e.clientY - isoPointerRef.current.y;
    isoPointerRef.current = { x: e.clientX, y: e.clientY };
    if (dx !== 0 || dy !== 0) handleIsoDrag(dx, dy);
  }, [handleIsoDrag]);

  const handleIsoPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (e.isPrimary) isoPointerRef.current = null;
  }, []);

  const handleIsoWheel = useCallback((e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    handleIsoPinch(e.deltaY < 0 ? 1.15 : 1 / 1.15);
  }, [handleIsoPinch]);

  const handleIsoTouchStart = useCallback((e: React.TouchEvent<HTMLDivElement>) => {
    if (e.touches.length === 1) {
      isoPointerRef.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    } else if (e.touches.length === 2) {
      isoPointerRef.current = null;
      const dx = e.touches[1].clientX - e.touches[0].clientX;
      const dy = e.touches[1].clientY - e.touches[0].clientY;
      isoPinchRef.current = { dist: Math.hypot(dx, dy) };
    }
  }, []);

  const handleIsoTouchMove = useCallback((e: React.TouchEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (e.touches.length === 1 && isoPointerRef.current && !isoPinchRef.current) {
      const dx = e.touches[0].clientX - isoPointerRef.current.x;
      const dy = e.touches[0].clientY - isoPointerRef.current.y;
      isoPointerRef.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      if (dx !== 0 || dy !== 0) handleIsoDrag(dx, dy);
    } else if (e.touches.length === 2 && isoPinchRef.current) {
      const dx = e.touches[1].clientX - e.touches[0].clientX;
      const dy = e.touches[1].clientY - e.touches[0].clientY;
      const newDist = Math.hypot(dx, dy);
      if (isoPinchRef.current.dist > 0) handleIsoPinch(newDist / isoPinchRef.current.dist);
      isoPinchRef.current = { dist: newDist };
    }
  }, [handleIsoDrag, handleIsoPinch]);

  const handleIsoTouchEnd = useCallback((e: React.TouchEvent<HTMLDivElement>) => {
    if (e.touches.length < 2) isoPinchRef.current = null;
    if (e.touches.length < 1) isoPointerRef.current = null;
  }, []);

  // ── Enter 3D top-down view (iso camera locked, same as MAP but cloud dominant) ──
  const enter3DView = useCallback(() => {
    setShowIosOverlay(false);
    setPendingIosMode(null);
    setViewMode('3d');
    setPreferredThreeDMode('3d');
  }, []);

  // ── Enter ORBIT view (free OrbitControls, cloud dominant) ──
  // Uses a dip-to-dark overlay to mask the ortho→persp camera swap.
  // Sequence: dip goes dark → switch viewMode (starts panel resize) →
  // wait for flex transition to finish → start fly-in once canvas is stable.
  const doOrbitSwap = useCallback((fromCam?: boolean) => {
    setShowIosOverlay(false);
    setPendingIosMode(null);

    if (fromCam) {
      setViewMode('orbit');
      setThreeDMode('orbit');
      setPreferredThreeDMode('3d');
      requestAnimationFrame(() => setFlyInActive(true));
      return;
    }

    setOrbitDip(true);
    setTimeout(() => {
      setViewMode('orbit');
      setThreeDMode('orbit');
      setPreferredThreeDMode('3d');
    }, 200);
    setTimeout(() => {
      setFlyInActive(true);
    }, 750);
  }, []);

  const enterOrbitView = useCallback(() => {
    const fromCam = viewMode === 'cam';
    setFollowVisitor(gpsStatus === 'active');
    setShowGazeBeams(true);
    setShowTouchMarks(true);
    doOrbitSwap(fromCam);
  }, [doOrbitSwap, viewMode, gpsStatus]);

  const handleIosPermission = useCallback(async () => {
    if (!orientation.requestPermission) return;
    const granted = await orientation.requestPermission();
    setShowIosOverlay(false);
    const mode = pendingIosMode;
    setPendingIosMode(null);
    if (granted && mode === 'cam') {
      setViewMode('cam');
      camSense.resetRest();
    } else if (granted) {
      setViewMode('ar');
      setThreeDMode('arSense');
      setPreferredThreeDMode('ar');
      lastMotionTimeRef.current = Date.now();
      arSense.resetRest();
      setArIdleCountdown(null);
    } else {
      setViewMode('3d');
      setThreeDMode('orbit');
    }
  }, [orientation, arSense, camSense, pendingIosMode]);

  const handleIosDeny = useCallback(() => {
    setShowIosOverlay(false);
    setPendingIosMode(null);
    setViewMode('3d');
    setThreeDMode('orbit');
  }, []);

  // ── Enter AR street-view mode (GPS-pinned horizon-lock) ──
  const enterArMode = useCallback(() => {
    if (orientation.requestPermission) {
      setPendingIosMode('ar');
      setShowIosOverlay(true);
      return;
    }
    setViewMode('ar');
    setThreeDMode('arSense');
    setPreferredThreeDMode('ar');
    lastMotionTimeRef.current = Date.now();
    arSense.resetRest();
    setArIdleCountdown(null);
  }, [orientation.requestPermission, arSense]);

  const exitArMode = useCallback(() => {
    setOrbitDip(true);
    setTimeout(() => {
      setViewMode('3d');
      setThreeDMode('orbit');
      setPreferredThreeDMode('3d');
    }, 200);
    setTimeout(() => {
      setFlyInActive(true);
    }, 750);
  }, []);

  // ── Enter CAM mode (live rear-camera overlay) ──
  const enterCamMode = useCallback(() => {
    if (orientation.requestPermission) {
      setPendingIosMode('cam');
      setShowIosOverlay(true);
      return;
    }
    setViewMode('cam');
    camSense.resetRest();
  }, [camSense, orientation.requestPermission]);

  // ── CAM: play a narrative from the cluster overlay (user-initiated, no auto-play) ──
  const handleCamPlayAnchor = useCallback((anchor: AnchorType) => {
    const camAUrl = resolveAudioUrl(anchor, lang ?? 'en', gender ?? 'f');
    if (!camAUrl) return;
    const url = `${recordingBaseUrl}/${camAUrl}`;
    setNowPlayingTitle(anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title);
    skipAutoPlayRef.current = true;
    playAnchorWithUnlock(anchor.id, url);
    recordVisit(anchor.id);
    setSelectedAnchor(anchor);
  }, [recordingBaseUrl, setNowPlayingTitle, playAnchorWithUnlock, recordVisit]);

  const cancelArPause = useCallback(() => {
    lastMotionTimeRef.current = Date.now();
    setArIdleCountdown(null);
  }, []);

  const handleFlushMemory = useCallback(() => {
    clearMemory();
  }, [clearMemory]);

  const handleRestartSession = useCallback(() => {
    handleFlushMemory();
    setHeardIds(new Set());
    localStorage.removeItem(`eyesof:heard:${recordingId}`);
    localStorage.removeItem('eyesof:heard_intro');
    setShowWelcome(true);
    setPreferredThreeDMode('3d');
    setViewMode('map');
    setThreeDMode('orbit');
    setFollowVisitor(true);
    setArIdleCountdown(null);
    setSettingsOpen(false);
  }, [handleFlushMemory, recordingId]);

  const handleRetryGps = useCallback(() => {
    setGpsStatus('waiting');
    setGpsErrorMsg(null);
    navigator.geolocation.getCurrentPosition(
      pos => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        const reg = geoRegRef.current;
        if (reg && !gpsForcedRef.current) {
          const dist = haversineDist(lat, lon, reg.centerLat, reg.centerLon);
          if (dist > GPS_TOO_FAR_M) { setGpsStatus('too_far'); return; }
        }
        setGpsStatus('active');
        setDevicePos({ lat, lon });
        const prev = glidedGpsRef.current;
        if (!prev) {
          glidedGpsRef.current = { lat, lon };
        } else {
          glidedGpsRef.current = {
            lat: prev.lat + AR_GPS_GLIDE_ALPHA * (lat - prev.lat),
            lon: prev.lon + AR_GPS_GLIDE_ALPHA * (lon - prev.lon),
          };
        }
        setGlidedDevicePos({ ...glidedGpsRef.current! });
      },
      err => {
        setGpsStatus('error');
        setGpsErrorMsg(err.message);
      },
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 10000 },
    );
  }, []);

  const handleForceGps = useCallback(() => {
    if (!window.confirm('You appear to be far from this recording area. Activate GPS anyway?')) return;
    gpsForcedRef.current = true;
    handleRetryGps();
  }, [handleRetryGps]);

  // ISO camera is now Leaflet-driven; recenter is handled by TopDownMap internally.
  const handleRecenterPointCloud = useCallback(() => { }, []);


  const handleCloudLoaded = useCallback(() => {
    setRecenterCloudSignal(s => s + 1);
  }, []);

  const handleSelectTouch = useCallback((o: import('../types').TouchOverlay) => {
    setSelectedGaze(null);
    setSelectedTouch(o);
    if (viewMode === 'map') {
      setAttentionDetail({ type: 'touch', overlay: o });
    }
  }, [viewMode]);

  const handleSelectGaze = useCallback((o: import('../types').GazeOverlay) => {
    setSelectedTouch(null);
    setSelectedGaze(o);
  }, []);

  const connectionLines = useMemo(() => {
    const group = selectedGaze?._connectionGroup;
    if (!group || !gazeOverlayData?.connections) return undefined;
    const conn = gazeOverlayData.connections.find(c => c.id === group);
    if (!conn || conn.anchorIds.length < 2) return undefined;
    const pts = conn.anchorIds
      .map(id => anchors.find(a => a.id === id))
      .filter((a): a is AnchorType => !!a && a.gps != null);
    if (pts.length < 2) return undefined;
    const lines: [number, number][][] = [];
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        lines.push([pts[i].gps!, pts[j].gps!]);
      }
    }
    return lines;
  }, [selectedGaze, gazeOverlayData, anchors]);

  const animPhase = narrativeAnim.active?.phase;
  const animConnectionLines = useMemo(() => {
    if (!narrativeAnim.activeEffects.length || narrativeAnim.opacity <= 0 || animPhase === 'fadeout') return undefined;
    const lines: [number, number][][] = [];
    for (const eff of narrativeAnim.activeEffects) {
      if (eff.type !== 'connection_lines') continue;
      const pts = eff.anchorIds
        .map((id: number) => anchors.find((a: AnchorType) => a.id === id))
        .filter((a: AnchorType | undefined): a is AnchorType => !!a && a.gps != null);
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          lines.push([pts[i].gps!, pts[j].gps!]);
        }
      }
    }
    return lines.length > 0 ? lines : undefined;
  }, [narrativeAnim.activeEffects, narrativeAnim.opacity, animPhase, anchors]);

  const mergedConnectionLines = useMemo(() => {
    if (!connectionLines && !animConnectionLines) return undefined;
    return [...(connectionLines ?? []), ...(animConnectionLines ?? [])];
  }, [connectionLines, animConnectionLines]);

  const handleCluster = useCallback((group: AnchorType[], screenX: number, screenY: number) => {
    setClusterFan({ anchors: group, screenX, screenY });
  }, []);

  const [heardIds, setHeardIds] = useState<Set<number>>(() => {
    try {
      const raw = localStorage.getItem(`eyesof:heard:${recordingId}`);
      if (raw) return new Set(JSON.parse(raw) as number[]);
    } catch { /* ignore */ }
    return new Set();
  });
  useEffect(() => {
    if (lastEndedId === null) return;
    setHeardIds(prev => {
      if (prev.has(lastEndedId)) return prev;
      const next = new Set(prev);
      next.add(lastEndedId);
      localStorage.setItem(`eyesof:heard:${recordingId}`, JSON.stringify([...next]));
      return next;
    });
  }, [lastEndedId, recordingId]);

  // Seed proximity hysteresis from persisted heard set so auto-play
  // won't re-fire for already-heard anchors after a page refresh.
  useEffect(() => {
    heardIds.forEach(id => recordVisit(id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const nearbyAnchors = useMemo((): NearbyAnchorInfo[] => {
    const results: NearbyAnchorInfo[] = [];
    const scale = geoReg?.scale ?? 1;
    const theta = geoReg?.theta ?? 0;
    const refX = userSlamPos?.x ?? 0;
    const refZ = userSlamPos?.z ?? 0;
    const hasRef = !!userSlamPos;
    for (const anchor of anchors) {
      if (!resolveAudioUrl(anchor, lang ?? 'en', gender ?? 'f')) continue;
      const dx = anchor.gx - refX;
      const dz = anchor.gz - refZ;
      const distM = hasRef ? Math.sqrt(dx * dx + dz * dz) / scale : 0;
      const slamAngle = Math.atan2(dx, dz);
      const bearingDeg = ((THREE.MathUtils.radToDeg(slamAngle + theta) % 360) + 360) % 360;
      results.push({ anchor, distanceM: distM, bearingDeg, heard: heardIds.has(anchor.id) });
    }
    return results.sort((a, b) => a.distanceM - b.distanceM).slice(0, 4);
  }, [anchors, userSlamPos, geoReg, heardIds]);

  const playingTitle = useMemo(() => {
    if (!playingAnchorId) return null;
    const found = anchors.find(a => a.id === playingAnchorId);
    return found ? (found.narrative_titles?.[lang || 'en'] ?? found.narrative_title) : null;
  }, [playingAnchorId, anchors]);

  const [queuedTitle, setQueuedTitle] = useState<string | null>(null);

  const handleBubblePlay = useCallback((anchor: AnchorType) => {
    if (!resolveAudioUrl(anchor, lang ?? 'en', gender ?? 'f')) return;
    setSelectedAnchor(anchor);
    setSelectedLinkIndex(null);
  }, [lang, gender]);

  // ── AR height swipe handlers ──────────────────────────────────────────────────
  const handleHeightTouchStart = useCallback((e: React.TouchEvent<HTMLDivElement>) => {
    if (e.touches.length !== 1) return;
    if (heightReadoutTimerRef.current) {
      clearTimeout(heightReadoutTimerRef.current);
      heightReadoutTimerRef.current = null;
    }
    setHeightReadoutFading(false);
    swipeGestureRef.current = {
      startY: e.touches[0].clientY,
      startHeight: heightOffsetRef.current,
      isDrag: false,
    };
  }, []);

  const handleHeightTouchMove = useCallback((e: React.TouchEvent<HTMLDivElement>) => {
    const g = swipeGestureRef.current;
    if (!g || e.touches.length !== 1) return;
    const dy = e.touches[0].clientY - g.startY;
    if (!g.isDrag && Math.abs(dy) < AR_HEIGHT_SWIPE_TAP_THRESHOLD_PX) return;
    g.isDrag = true;
    // Swipe UP (dy < 0) → RAISE height; swipe DOWN → lower
    const newH = Math.max(AR_HEIGHT_SWIPE_MIN_M, Math.min(AR_HEIGHT_SWIPE_MAX_M,
      g.startHeight - dy * AR_HEIGHT_SWIPE_M_PER_PX,
    ));
    setHeightOffset(newH);
    setHeightReadout(newH);
  }, [setHeightOffset]);

  const handleHeightTouchEnd = useCallback(() => {
    const g = swipeGestureRef.current;
    swipeGestureRef.current = null;
    if (!g?.isDrag) return;
    setHeightReadoutFading(true);
    heightReadoutTimerRef.current = setTimeout(() => {
      setHeightReadout(null);
      setHeightReadoutFading(false);
    }, 1500);
  }, []);

  return (
    <div className="viewer-wrapper">
      <div className="viewer-title">
        <div className="view-mode-toggle">
          <button
            className={`view-mode-btn${viewMode === 'map' ? ' active' : ''}`}
            onClick={() => { setShowIosOverlay(false); setPendingIosMode(null); setViewMode('map'); }}
          >
            MAP
          </button>
          <button
            className={`view-mode-btn${viewMode === '3d' ? ' active' : ''}`}
            onClick={enter3DView}
          >
            3D
          </button>
          <button
            className={`view-mode-btn${viewMode === 'orbit' ? ' active' : ''}`}
            onClick={enterOrbitView}
          >
            ORBIT
          </button>
          {(orientation.isAvailable || orientation.requestPermission) && (
            <button
              className={`view-mode-btn${viewMode === 'cam' ? ' active' : ''}`}
              onClick={enterCamMode}
            >
              CAM
            </button>
          )}
          <button
            className={`settings-hamburger${settingsOpen ? ' active' : ''}`}
            onClick={() => setSettingsOpen(v => !v)}
            title="Settings"
            aria-label="Settings"
            aria-expanded={settingsOpen}
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="3" y1="4.5" x2="15" y2="4.5" />
              <line x1="3" y1="9" x2="15" y2="9" />
              <line x1="3" y1="13.5" x2="15" y2="13.5" />
            </svg>
          </button>
        </div>
      </div>

      <div className="app-container">
        {/*
         * Flip-pair: cloud panel and Leaflet panel are BOTH ALWAYS MOUNTED.
         * Flex-grow transitions animate the 4:1 dominant/strip ratio.
         * Neither panel is unmounted on mode switch — preserves WebGL context
         * and Leaflet tile cache across MAP ↔ 3D ↔ ORBIT transitions.
         */}
        <div className="flip-pair-container">
          {/*
           * CAM overlay: covers the flip-pair while canvas stays mounted below
           * (visibility:hidden) so the WebGL context survives CAM ↔ any switch.
           */}
          {viewMode === 'cam' && (
            <div style={{ position: 'absolute', inset: 0, zIndex: 10, display: 'flex', background: '#000' }}>
              <CamView
                anchors={anchors}
                dampedQRef={camSense.dampedQRef}
                snappedSlamPos={snappedSlamPos}
                heightOffset={heightOffset}
                geoReg={geoReg}
                onPlayAnchor={handleCamPlayAnchor}
                playingAnchorId={playingAnchorId}
                audioToast={null}
                heardIds={heardIds}
                gazeOverlays={gazeOverlayData?.gazeOverlays}
                touchOverlays={gazeOverlayData?.touchOverlays}
                showGaze={camShowGaze}
                showTouch={camShowTouch}
                devicePos={devicePos}
                compassAlpha={orientation.alpha}
                trajectoryData={trajectoryData}
                lang={lang}
                gender={gender}
              />
            </div>
          )}

          {/* ── Cloud panel (three.js) ── */}
          <div
            ref={cloudPanelRef}
            className="flip-panel flip-panel-cloud"
            style={{
              flexGrow: viewMode === 'map' ? 0.02 : viewMode === 'orbit' ? 50 : 3,
              visibility: viewMode === 'cam' ? 'hidden' : undefined,
              transition: skipFlexTransition ? 'none' : undefined,
              pointerEvents: viewMode === 'cam' ? 'none' : undefined,
            }}
            onClick={() => {
              if (isArSense && arIdleCountdown !== null) cancelArPause();
            }}
            onPointerDown={(viewMode === 'map' || viewMode === '3d') ? handleIsoPointerDown : undefined}
            onPointerMove={(viewMode === 'map' || viewMode === '3d') ? handleIsoPointerMove : undefined}
            onPointerUp={(viewMode === 'map' || viewMode === '3d') ? handleIsoPointerUp : undefined}
            onPointerCancel={(viewMode === 'map' || viewMode === '3d') ? handleIsoPointerUp : undefined}
            onWheel={(viewMode === 'map' || viewMode === '3d') ? handleIsoWheel : undefined}
            onTouchStart={(viewMode === 'map' || viewMode === '3d') ? handleIsoTouchStart : (isArSense ? handleHeightTouchStart : undefined)}
            onTouchMove={(viewMode === 'map' || viewMode === '3d') ? handleIsoTouchMove : (isArSense ? handleHeightTouchMove : undefined)}
            onTouchEnd={(viewMode === 'map' || viewMode === '3d') ? handleIsoTouchEnd : (isArSense ? handleHeightTouchEnd : undefined)}
          >
            {viewMode === 'map' && (
              <div className="topdown-label iso-panel-label">
                Iso View
                {gpsStatus === 'active' && <span className="topdown-gps-active"> · GPS</span>}
                {gpsStatus === 'waiting' && <span className="topdown-gps-waiting"> · GPS…</span>}
                {gpsStatus === 'error' && <span className="topdown-gps-error"> · GPS err</span>}
                {gpsStatus === 'too_far' && (
                  <span className="topdown-gps-toofar" onClick={handleForceGps}> · GPS off (too far) — tap to force</span>
                )}
              </div>
            )}

            {viewMode === 'map' && (
              <div className="iso-zoom-controls">
                <button className="iso-zoom-btn" onClick={() => leafletMap?.zoomIn()}>+</button>
                <button className="iso-zoom-btn" onClick={() => leafletMap?.zoomOut()}>−</button>
              </div>
            )}

            <Canvas shadows={true} frameloop="demand" onPointerMissed={() => { setSelectedGaze(null); setSelectedTouch(null); }}>
              <WebGLContextRecovery />
              <ContextDisposer />
              <ViewModeInvalidator viewMode={viewMode} />
              {/*
               * CameraController: ortho for MAP and 3D (iso top-down Leaflet-driven);
               * persp for ORBIT / AR / CAM (free camera or device orientation).
               */}
              <CameraController
                viewMode={viewMode}
                isoLeafletViewRef={isoLeafletViewRef}
                isoFallback={isoFallback}
              />
              {/* IsoAnimator: keeps canvas rendering every frame in MAP and 3D modes */}
              {(viewMode === 'map' || viewMode === '3d') && <IsoAnimator />}

              {isImmersive && (
                <ImmersiveCamera
                  alpha={orientation.alpha}
                  beta={orientation.beta}
                  initialPos={immersivePos}
                  recenterSignal={immersiveRecenterSignal}
                />
              )}
              {isArSense && (
                <ArSenseCamera
                  dampedQRef={arSense.dampedQRef}
                  snappedSlamPos={snappedSlamPos}
                  heightOffset={heightOffset}
                />
              )}

              {/* ORBIT: free OrbitControls + cinematic fly-in */}
              {viewMode === 'orbit' && (
                <>
                  <OrbitControls
                    ref={controlsRef}
                    makeDefault
                    enabled={!flyInActive}
                    enableDamping={true}
                    dampingFactor={0.1}
                    rotateSpeed={0.8}
                    minDistance={1.0}
                    maxDistance={2000}
                    zoomSpeed={2}
                    panSpeed={1.5}
                    screenSpacePanning={true}
                    touches={{ ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN }}
                    onStart={() => { if (followVisitor) setFollowVisitor(false); setClusterFan(null); }}
                  />
                  <OrbitFlyIn
                    active={flyInActive}
                    onComplete={() => setFlyInActive(false)}
                    userSlamPos={gpsStatus === 'active' ? userSlamPos : null}
                    compassAlpha={orientation.alpha}
                    isoLeafletViewRef={isoLeafletViewRef}
                    controlsRef={controlsRef}
                  />
                  <FollowCamera
                    active={followVisitor && !flyInActive}
                    userSlamPos={gpsStatus === 'active' ? userSlamPos : null}
                    compassAlpha={orientation.alpha}
                    northRotation={northRotation}
                    controlsRef={controlsRef}
                  />
                  <DoubleClickFocus controlsRef={controlsRef} />
                  <OrbitAutoRecenter controlsRef={controlsRef} active={!followVisitor && !flyInActive} />
                  <RecenterToCloud signal={recenterCloudSignal} controlsRef={controlsRef} />
                </>
              )}

              <color attach="background" args={[(viewMode === 'map' || viewMode === '3d') ? '#1a1e2e' : '#1e2233']} />
              <ambientLight intensity={(viewMode === 'map' || viewMode === '3d') ? 2.5 : 2.0} />
              {viewMode !== 'map' && viewMode !== '3d' && <pointLight position={[10, 20, 10]} intensity={2.5} />}

              <Suspense fallback={null}>
                {/*
                 * Coordinate frame: non-baked clouds need northRotation+Z-flip for ISO view
                 * (MAP and 3D both use iso ortho camera). Baked clouds are identity in all modes.
                 * PointCloud stays mounted across all mode switches.
                 */}
                <group
                  rotation={(viewMode === 'map' || viewMode === '3d') && !baked ? [0, northRotation, 0] : [0, 0, 0]}
                  scale={(viewMode === 'map' || viewMode === '3d') && !baked ? [1, 1, -1] : [1, 1, 1]}
                >
                  <PointCloud
                    url={pointCloudUrl}
                    focusRef={viewMode === 'orbit' ? controlsRef : undefined}
                    fadeEnabled={(viewMode === 'orbit' || viewMode === 'ar') && fadeEnabled}
                    fadeStart={fadeStart}
                    fadeEnd={fadeEnd}
                    proximityFade={viewMode === 'orbit'}
                    proximityPos={userSlamPos}
                    proximityRadius={4}
                    geoScale={geoReg?.scale ?? 1}
                    followFadeDist={followVisitor ? FOLLOW_CAM_DISTANCE : 0}
                    onLoad={handleCloudLoaded}
                  />

                  {/* MAP and 3D: iso AnchorMarkers; ORBIT/AR: 3D Hotspots; CAM: own overlay */}
                  {showAnchorMarks && viewMode !== 'cam' && ((viewMode === 'map' || viewMode === '3d') ? (
                    cloudAnchors.map(a => (
                      <AnchorMarker
                        key={a.id}
                        anchor={a}
                        selected={selectedAnchor?.id === a.id}
                        proximity={proximityMap.get(a.id)}
                        isPlaying={playingAnchorId === a.id}
                        isHeard={heardIds.has(a.id)}
                      />
                    ))
                  ) : (
                    <Hotspots
                      anchors={cloudAnchors}
                      onSelect={handleAnchorTap}
                      onCluster={handleCluster}
                      selectedId={selectedAnchor?.id}
                      dimmedIds={dimmedIds}
                      proximityMap={proximityMap}
                      visitedAnchorIds={heardIds}
                      playingAnchorId={playingAnchorId}
                    />
                  ))}

                  {/* Zoom-proximity anchor labels — 3D and orbit modes */}
                  {showAnchorMarks && (viewMode === '3d' || viewMode === 'orbit') && (
                    <AnchorLabels
                      anchors={cloudAnchors}
                      onSelect={handleAnchorTap}
                      visitedAnchorIds={heardIds}
                      playingAnchorId={playingAnchorId}
                      userSlamPos={userSlamPos}
                      bubbleMinZoom={12}
                      lang={lang}
                    />
                  )}

                  {(viewMode === 'orbit' || viewMode === '3d') && gazeOverlayData && showGazeBeams && (
                    <GazeBeams overlays={gazeOverlayData.gazeOverlays} anchors={cloudAnchors} selectedOverlay={selectedGaze} activeAnchorId={selectedAnchor?.id ?? null} onSelect={handleSelectGaze} connections={gazeOverlayData.connections} />
                  )}
                  {(viewMode === 'orbit' || viewMode === '3d') && gazeOverlayData && showTouchMarks && (
                    <TouchMarks overlays={gazeOverlayData.touchOverlays} selectedOverlay={selectedTouch} activeAnchorId={selectedAnchor?.id ?? null} onSelect={handleSelectTouch} />
                  )}
                  {(viewMode === 'orbit' || viewMode === '3d') && narrativeAnim.activeEffects.length > 0 && (
                    <AnimatedOverlays effects={narrativeAnim.activeEffects} anchorPositions={anchorPositionMap} opacity={narrativeAnim.opacity} />
                  )}
                  {(viewMode === 'orbit' || viewMode === '3d') && (selectedGaze || selectedTouch) && (
                    <ScenePopup
                      gazeOverlay={selectedGaze}
                      touchOverlay={selectedTouch}
                      onOpenDetail={setAttentionDetail}
                      onClose={() => { setSelectedGaze(null); setSelectedTouch(null); }}
                      recordingBaseUrl={recordingBaseUrl}
                      lang={lang}
                    />
                  )}

                  {viewMode === 'map' && gazeOverlayData && showGazeBeams && (
                    <MapGazeLines overlays={gazeOverlayData.gazeOverlays} anchors={cloudAnchors} activeAnchorId={selectedAnchor?.id ?? null} />
                  )}
                  {viewMode === 'map' && gazeOverlayData && showTouchMarks && (
                    <MapTouchDots overlays={gazeOverlayData.touchOverlays} activeAnchorId={selectedAnchor?.id ?? null} onSelect={handleSelectTouch} />
                  )}

                  {(viewMode === 'map' || viewMode === '3d' || viewMode === 'orbit') && userSlamPos && (
                    <GpsMarker
                      pos={userSlamPos}
                      compassAlpha={orientation.alpha}
                      mode={viewMode === 'orbit' ? 'orbit' : 'iso'}
                      northRotation={northRotation}
                      zFlipped={(viewMode === 'map' || viewMode === '3d') && !baked}
                    />
                  )}

                  {viewMode !== 'map' && viewMode !== '3d' && (
                    <SemanticConnections
                      graphData={graphData}
                      onSelectLink={handleSelectLink}
                      selectedLinkIndex={selectedLinkIndex}
                    />
                  )}
                </group>
              </Suspense>
            </Canvas>

            {/* Dip-to-dark overlay masks ortho→persp camera swap */}
            {orbitDip && (
              <div
                className="orbit-dip-overlay"
                onAnimationEnd={() => setOrbitDip(false)}
              />
            )}


            {/* Anchor cluster fan — disambiguate packed hotspots */}
            {clusterFan && viewMode === 'orbit' && (() => {
              const panel = cloudPanelRef.current;
              if (!panel) return null;
              const pr = panel.getBoundingClientRect();
              const fanW = 210, fanH = Math.min(clusterFan.anchors.length * 48 + 16, 280);
              const x = Math.max(8, Math.min(pr.width - fanW - 8, clusterFan.screenX - fanW / 2));
              const y = Math.max(8, Math.min(pr.height - fanH - 8, clusterFan.screenY + 12));
              return (
                <>
                  <div className="anchor-fan-backdrop" onClick={() => setClusterFan(null)} />
                  <div className="anchor-fan" style={{ left: x, top: y }}>
                    {clusterFan.anchors.map(a => {
                      const heard = heardIds.has(a.id);
                      const playing = playingAnchorId === a.id;
                      return (
                        <button
                          key={a.id}
                          className={`anchor-fan__item${heard ? ' heard' : ''}${playing ? ' playing' : ''}`}
                          onClick={() => {
                            setClusterFan(null);
                            setSelectedAnchor(a);
                            setSelectedLinkIndex(null);
                          }}
                        >
                          <span className="anchor-fan__play">{playing ? '◼' : '▶'}</span>
                          <span className="anchor-fan__title">{a.narrative_titles?.[lang || 'en'] ?? a.narrative_title}</span>
                          {heard && <span className="anchor-fan__badge">heard</span>}
                        </button>
                      );
                    })}
                  </div>
                </>
              );
            })()}



            {/* ORBIT-mode overlays */}
            {viewMode === 'orbit' && (
              <button
                className={`follow-visitor-btn${followVisitor ? ' active' : ''}${gpsStatus === 'too_far' ? ' gps-too-far' : ''}`}
                onClick={() => {
                  if (gpsStatus === 'too_far') return;
                  setFollowVisitor(v => !v);
                }}
                title={gpsStatus === 'too_far' ? 'GPS too far from recording area' : followVisitor ? 'Switch to free camera' : 'Follow visitor GPS position'}
                disabled={!userSlamPos && gpsStatus !== 'too_far'}
              >
                <svg width="14" height="14" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                  <path d="M9 2L4 16L9 12L14 16Z" stroke="currentColor" strokeWidth="1.5"
                    fill={followVisitor ? 'currentColor' : 'none'} strokeLinejoin="round" />
                </svg>
                {gpsStatus === 'too_far' ? 'GPS too far' : followVisitor ? 'Following' : 'Follow Me'}
              </button>
            )}

            {/* Overlay + marks toggles — MAP, 3D and orbit */}
            {(viewMode === 'orbit' || viewMode === '3d' || viewMode === 'map') && (
              <div className="orbit-overlay-toggles">
                {gazeOverlayData && (
                  <>
                    <button
                      className={`orbit-overlay-btn orbit-overlay-btn--gaze${showGazeBeams ? ' active' : ''}`}
                      onClick={() => setShowGazeBeams(v => !v)}
                      title={showGazeBeams ? 'Hide expert gaze' : 'Show expert gaze'}
                    >
                      <svg width="24" height="24" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <ellipse cx="8" cy="8" rx="7" ry="4.5" stroke="currentColor" strokeWidth="1.2" />
                        <circle cx="8" cy="8" r="2" fill={showGazeBeams ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.2" />
                      </svg>
                    </button>
                    <button
                      className={`orbit-overlay-btn orbit-overlay-btn--touch${showTouchMarks ? ' active' : ''}`}
                      onClick={() => setShowTouchMarks(v => !v)}
                      title={showTouchMarks ? 'Hide expert touch' : 'Show expert touch'}
                    >
                      <svg width="24" height="24" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path d="M8 1C8 1 5 3 5 6.5C5 8 6 9 7 9.5L7 14C7 14.6 7.4 15 8 15C8.6 15 9 14.6 9 14L9 9.5C10 9 11 8 11 6.5C11 3 8 1 8 1Z"
                          stroke="currentColor" strokeWidth="1.2" fill={showTouchMarks ? 'currentColor' : 'none'} strokeLinejoin="round" />
                      </svg>
                    </button>
                  </>
                )}
                <button
                  className={`orbit-overlay-btn orbit-overlay-btn--marks${showAnchorMarks ? ' active' : ''}`}
                  onClick={() => setShowAnchorMarks(v => !v)}
                  title={showAnchorMarks ? 'Hide anchor marks' : 'Show anchor marks'}
                >
                  <svg width="24" height="24" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <rect x="4" y="4" width="8" height="8" transform="rotate(45 8 8)"
                      stroke="currentColor" strokeWidth="1.4"
                      fill={showAnchorMarks ? 'currentColor' : 'none'} />
                  </svg>
                </button>
              </div>
            )}

            {/* Expert overlay info bubble — map mode only (orbit/3d uses ScenePopup inside Canvas) */}
            {viewMode === 'map' && selectedTouch && (
              <div className="overlay-info-bubble">
                <button className="overlay-info-bubble__close" onClick={() => setSelectedTouch(null)}>✕</button>
                {selectedTouch.frameUrl ? (
                  <div className="overlay-info-bubble__frame-wrap">
                    <img className="overlay-info-bubble__frame" src={`${recordingBaseUrl}/${selectedTouch.frameUrl}`} alt={selectedTouch.label} />
                  </div>
                ) : (
                  <div className="overlay-info-bubble__placeholder overlay-info-bubble__placeholder--touch">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <path d="M12 2C12 2 8 5 8 9.5C8 11.5 9.5 13 11 13.5V21C11 21.6 11.4 22 12 22C12.6 22 13 21.6 13 21V13.5C14.5 13 16 11.5 16 9.5C16 5 12 2 12 2Z" strokeLinejoin="round" />
                    </svg>
                  </div>
                )}
                <div className="overlay-info-bubble__label">{lang === 'it' ? (selectedTouch.label_it || selectedTouch.label) : selectedTouch.label}</div>
                <div className="overlay-info-bubble__hint">{lang === 'it' ? 'Tocco dell\'esperta' : 'Expert touched this'}</div>
                <button className="overlay-info-bubble__expand" onClick={() => setAttentionDetail({ type: 'touch', overlay: selectedTouch })}>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4,10 8,6 12,10" /></svg>
                </button>
              </div>
            )}
            {viewMode === 'map' && selectedGaze && (
              <div className="overlay-info-bubble overlay-info-bubble--gaze">
                <button className="overlay-info-bubble__close" onClick={() => setSelectedGaze(null)}>✕</button>
                {selectedGaze.frameUrl ? (
                  <div className="overlay-info-bubble__frame-wrap">
                    <img className="overlay-info-bubble__frame" src={`${recordingBaseUrl}/${selectedGaze.frameUrl}`} alt={selectedGaze.objectLabel ?? 'Expert view'} />
                  </div>
                ) : (
                  <div className="overlay-info-bubble__placeholder overlay-info-bubble__placeholder--gaze">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                      <ellipse cx="12" cy="12" rx="10" ry="6" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  </div>
                )}
                <div className="overlay-info-bubble__label">
                  {lang === 'it' ? (selectedGaze._note_it || selectedGaze.objectLabel_it || selectedGaze._note || selectedGaze.objectLabel || 'L\'esperta guardava qui') : (selectedGaze._note || selectedGaze.objectLabel || 'Expert was looking here')}
                </div>
                <div className="overlay-info-bubble__hint">{lang === 'it' ? 'Vista dell\'esperta' : 'Expert\'s view'}</div>
                <button className="overlay-info-bubble__expand" onClick={() => setAttentionDetail({ type: 'gaze', overlay: selectedGaze })}>
                  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="4,10 8,6 12,10" /></svg>
                </button>
              </div>
            )}

            {/* attention detail moved to floating bubble in flip-pair-container */}

            {/* AR-mode overlays */}
            {isArSense && arSense.compassAlpha !== null && (
              <div className="ar-compass" aria-label={`Heading ${Math.round(arSense.compassAlpha)}°`}>
                <svg width="64" height="64" viewBox="0 0 64 64">
                  <circle cx="32" cy="32" r="30" stroke="rgba(255,255,255,0.25)" strokeWidth="1.5" fill="rgba(0,0,0,0.65)" />
                  <g transform={`rotate(${-arSense.compassAlpha}, 32, 32)`}>
                    <polygon points="32,6 28.5,32 35.5,32" fill="#ff4444" />
                    <polygon points="32,58 28.5,32 35.5,32" fill="rgba(255,255,255,0.45)" />
                    <text x="32" y="15" textAnchor="middle" fill="#ff4444" fontSize="9" fontWeight="bold" fontFamily="system-ui">N</text>
                  </g>
                </svg>
              </div>
            )}
            {isArSense && arIdleCountdown === null && snappedSlamPos === null && gpsStatus !== 'active' && (
              <div className="ar-status-bar">waiting for GPS</div>
            )}
            {isArSense && heightReadout !== null && (
              <div
                className={`ar-height-readout${heightReadoutFading ? ' fading' : ''}`}
                aria-live="assertive"
                aria-atomic="true"
              >
                {heightReadout.toFixed(1)} m
              </div>
            )}
            {isArSense && arIdleCountdown !== null && (
              <div className="ar-pause-overlay" onClick={cancelArPause}>
                <p className="ar-pause-title">AR paused — phone idle</p>
                <p className="ar-pause-countdown">Returning to map view in {arIdleCountdown}s…</p>
                <p className="ar-pause-hint">Tap or move to stay</p>
              </div>
            )}
            {showIosOverlay && (
              <div className="ios-permission-overlay">
                <div className="ios-permission-card">
                  <p className="ios-permission-hint">Hold your device up to look around</p>
                  <button className="ios-permission-btn" onClick={handleIosPermission}>Enable</button>
                  <button className="ios-permission-cancel" onClick={handleIosDeny}>Use 3D View</button>
                </div>
              </div>
            )}
          </div>

          {/* ── Leaflet panel (always mounted) ── */}
          <div
            className="flip-panel flip-panel-leaflet"
            style={{
              flexGrow: viewMode === 'map' ? 50 : viewMode === 'orbit' ? 0.02 : 1.5,
              visibility: viewMode === 'cam' ? 'hidden' : undefined,
              transition: skipFlexTransition ? 'none' : undefined,
            }}
          >
            <TopDownMap
              trajectoryData={trajectoryData}
              trajectoryError={trajectoryError}
              anchors={anchors}
              selectedAnchor={selectedAnchor}
              onSelectAnchor={(a) => {
                setSelectedAnchor(a);
                setSelectedLinkIndex(null);
              }}
              devicePos={devicePos}
              gpsStatus={gpsStatus}
              gpsErrorMsg={gpsErrorMsg}
              isMobile={isMobile}
              compassAlpha={orientation.alpha}
              followMode={mapFollowMode}
              onFollowModeChange={setMapFollowMode}
              onRecenterPointCloud={handleRecenterPointCloud}
              proximityMap={proximityMap}
              currentAnchorId={playingAnchorId}
              visitedAnchorIds={heardIds}
              onMapReady={handleMapReady}
              popupOpen={selectedAnchor !== null}
              connectionLines={mergedConnectionLines}
            />
          </div>

          {/* ── Floating attention bubble (overlays map, no layout shift) ── */}
          {attentionDetail && (
            <div className="attention-bubble-backdrop" onClick={() => setAttentionDetail(null)}>
              <div className={`attention-bubble attention-bubble--${attentionDetail.type}`} onClick={(e) => e.stopPropagation()}>
                <button className="attention-bubble__close" onClick={() => setAttentionDetail(null)}>✕</button>
                <div className="attention-bubble__circle">
                  {(() => {
                    const rawFrame = attentionDetail.type === 'gaze'
                      ? attentionDetail.overlay.frameUrl
                      : attentionDetail.overlay.frameUrl;
                    const frameSrc = rawFrame ? `${recordingBaseUrl}/${rawFrame}` : undefined;
                    if (frameSrc) {
                      return <img className="attention-bubble__img" src={frameSrc} alt={attentionDetail.type === 'gaze' ? (attentionDetail.overlay.objectLabel ?? 'Expert view') : attentionDetail.overlay.label} />;
                    }
                    return attentionDetail.type === 'gaze' ? (
                      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2">
                        <ellipse cx="12" cy="12" rx="10" ry="6" />
                        <circle cx="12" cy="12" r="3" />
                      </svg>
                    ) : (
                      <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2">
                        <path d="M12 2C12 2 8 5 8 9.5C8 11.5 9.5 13 11 13.5V21C11 21.6 11.4 22 12 22C12.6 22 13 21.6 13 21V13.5C14.5 13 16 11.5 16 9.5C16 5 12 2 12 2Z" strokeLinejoin="round" />
                      </svg>
                    );
                  })()}
                </div>
                <div className="attention-bubble__type">
                  {attentionDetail.type === 'gaze' ? (lang === 'it' ? 'Sguardo' : 'Gaze') : (lang === 'it' ? 'Tocco' : 'Touch')}
                </div>
                <div className="attention-bubble__label">
                  {attentionDetail.type === 'gaze'
                    ? (lang === 'it' ? (attentionDetail.overlay._note_it || attentionDetail.overlay.objectLabel_it || attentionDetail.overlay._note || attentionDetail.overlay.objectLabel || 'L\'esperta guardava qui') : (attentionDetail.overlay._note || attentionDetail.overlay.objectLabel || 'Expert was looking here'))
                    : (lang === 'it' ? (attentionDetail.overlay.label_it || attentionDetail.overlay.label) : attentionDetail.overlay.label)}
                </div>
              </div>
            </div>
          )}
        </div>

        <Sidebar
          anchors={anchors}
          selectedAnchor={selectedAnchor}
          selectedLink={getSelectedLinkData()}
          onSelect={(a) => {
            setSelectedAnchor(a);
            setSelectedLinkIndex(null);
          }}
          onClearSelection={() => setSelectedAnchor(null)}
          onClearLink={() => setSelectedLinkIndex(null)}
          isMobile={isMobile}
          recordingBaseUrl={recordingBaseUrl}
          gazeOverlays={gazeOverlayData?.gazeOverlays.filter(o => o.anchorId === selectedAnchor?.id)}
          touchOverlays={gazeOverlayData?.touchOverlays.filter(o => o.anchorId === selectedAnchor?.id)}
          onShowAttentionDetail={(item) => {
            if (viewMode === 'orbit' || viewMode === '3d') {
              if (item.type === 'gaze') { setSelectedTouch(null); setSelectedGaze(item.overlay as import('../types').GazeOverlay); }
              else { setSelectedGaze(null); setSelectedTouch(item.overlay as import('../types').TouchOverlay); }
              const target = item.type === 'gaze'
                ? (item.overlay as import('../types').GazeOverlay).gazeTarget
                : (item.overlay as import('../types').TouchOverlay).pos;
              if (controlsRef.current && target) {
                controlsRef.current.target.set(target[0], target[1], target[2]);
                controlsRef.current.update();
              }
            } else {
              setAttentionDetail(item);
            }
          }}
          lang={lang}
          gender={gender}
          bubbleMap={bubbleMap}
          showOriginalTranscript={showOriginalTranscript}
          mobileOpen={sidebarOpen}
          onMobileOpenChange={setSidebarOpen}
        />

        <NarrativeBubble
          nearbyAnchors={nearbyAnchors}
          playingTitle={playingTitle}
          queuedTitle={queuedTitle}
          onPlayAnchor={handleBubblePlay}
          onSelectAnchor={(a) => { setSelectedAnchor(a); setSelectedLinkIndex(null); }}
          viewMode={viewMode}
          compassHeading={orientation.alpha}
          lang={lang}
          sidebarCollapsed={isMobile && selectedAnchor !== null && !sidebarOpen}
          onReopenSidebar={() => setSidebarOpen(true)}
        />

        {/* MiniPlayer removed — NarrativeBubble handles playback state */}
      </div>

      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        fadeEnabled={fadeEnabled}
        onFadeEnabled={setFadeEnabled}
        fadeEnd={fadeEnd}
        onFadeEnd={setFadeEnd}
        heightOffset={heightOffset}
        onHeightOffset={setHeightOffset}
        audioEnabled={audioEnabled}
        onToggleAudio={toggleAudio}
        proximityAutoPlay={proximityAutoPlay}
        onProximityAutoPlay={setProximityAutoPlay}
        compassOffset={compassOffset}
        onCompassOffset={setCompassOffset}
        arAutoReturn={arAutoReturn}
        onArAutoReturn={setArAutoReturn}
        gpsStatus={gpsStatus}
        onRetryGps={gpsStatus === 'too_far' ? handleForceGps : handleRetryGps}
        camShowGaze={camShowGaze}
        onCamShowGaze={setCamShowGaze}
        camShowTouch={camShowTouch}
        onCamShowTouch={setCamShowTouch}
        showOriginalTranscript={showOriginalTranscript}
        onShowOriginalTranscript={setShowOriginalTranscript}
        aiEnabled={aiEnabled}
        onToggleAI={toggleAI}
        onFlushMemory={handleFlushMemory}
        onRestartSession={handleRestartSession}
        onEnterAR={orientation.isAvailable ? enterArMode : undefined}
        onExitAR={exitArMode}
        isArAvailable={orientation.isAvailable}
        viewMode={viewMode}
        lang={lang}
        onLangChange={onLangChange}
        gender={gender}
        onGenderChange={onGenderChange}
      />

      {showIntro && (
        <div className="intro-overlay" onClick={dismissIntro}>
          <div className="intro-card" onClick={e => e.stopPropagation()}>
            <p className="intro-text">
              Audio plays automatically as you approach narrative points — keep
              the phone with you and listen.
            </p>
            <button className="intro-dismiss" onClick={dismissIntro}>Got it</button>
          </div>
        </div>
      )}

      {debugMode && (
        <div className="ar-debug-overlay">
          <div className="ar-debug-title">GPS Debug</div>
          <div>Raw: {debugGps ? `${debugGps.rawLat.toFixed(6)}, ${debugGps.rawLon.toFixed(6)}` : '—'}</div>
          <div>Accuracy: {debugGps ? `${debugGps.accuracy.toFixed(1)} m` : '—'}</div>
          <div>Glided: {glidedDevicePos ? `${glidedDevicePos.lat.toFixed(6)}, ${glidedDevicePos.lon.toFixed(6)}` : '—'}</div>
          <div>SLAM: {snappedSlamPos ? `(${snappedSlamPos.x.toFixed(2)}, ${snappedSlamPos.y.toFixed(2)}, ${snappedSlamPos.z.toFixed(2)})` : '—'}</div>
          <div>Rail w: {railWeight.toFixed(3)}</div>
          <div>Eye h: {heightOffset.toFixed(2)} m</div>
          <div>Accept: {debugGps?.accepted ?? 0} / Reject: {debugGps?.rejected ?? 0}</div>
        </div>
      )}

      <WelcomeOverlay
        visible={showWelcome}
        lang={lang || 'en'}
        onDismiss={() => { setShowWelcome(false); localStorage.setItem('eyesof:heard_intro', 'true'); }}
      />
    </div>
  );
};
