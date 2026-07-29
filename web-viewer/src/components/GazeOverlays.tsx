import { useRef, useMemo, useState } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import type { GazeOverlay, TouchOverlay, GazeConnection } from '../types';

const BEAM_COLOR = new THREE.Color('#44bbff');
const BEAM_SEGMENTS = 12;
const HIT_MAT = new THREE.MeshBasicMaterial({ opacity: 0, transparent: true, depthWrite: false });
const FADE_NEAR = 6;
const FADE_FAR = 28;
const GAZE_BASE_OPACITY = 0.5;
const GAZE_SELECTED_OPACITY = 0.8;
const OPACITY_FLOOR = 0.25;

interface GazeBeamFromAnchorProps {
  anchorPos: THREE.Vector3;
  overlay: GazeOverlay;
  selected?: boolean;
  highlighted?: boolean;
  onSelect?: (o: GazeOverlay) => void;
}

function GazeBeamFromAnchor({ anchorPos, overlay, selected, highlighted, onSelect }: GazeBeamFromAnchorProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const { camera } = useThree();

  const { geometry, material, midpoint, quaternion } = useMemo(() => {
    const target = new THREE.Vector3(...overlay.gazeTarget);
    const dir = target.clone().sub(anchorPos).normalize();
    const depth = overlay.gazeDepth;
    const tipRadius = Math.tan(overlay.gazeSpread) * depth * 3;

    const geo = new THREE.ConeGeometry(tipRadius, depth, BEAM_SEGMENTS, 1, true);
    // Tip (narrow end) at the eye origin, base (wide end) toward the gaze target.
    // Default cone: tip at +Y. Flip so tip faces -Y (origin), then shift so tip sits at origin.
    geo.rotateX(Math.PI);
    geo.translate(0, depth / 2, 0);

    // Quaternion to rotate local +Y to the beam direction
    const q = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0),
      dir,
    );

    const mat = new THREE.MeshBasicMaterial({
      color: BEAM_COLOR,
      transparent: true,
      opacity: GAZE_BASE_OPACITY,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
      depthWrite: false,
    });

    return { geometry: geo, material: mat, midpoint: anchorPos.clone(), quaternion: q };
  }, [anchorPos, overlay]);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    const dist = camera.position.distanceTo(midpoint);
    const t = Math.max(0, Math.min(1, (dist - FADE_NEAR) / (FADE_FAR - FADE_NEAR)));
    const base = selected ? GAZE_SELECTED_OPACITY : highlighted ? 0.65 : GAZE_BASE_OPACITY;
    const fadedOpacity = OPACITY_FLOOR + (base - OPACITY_FLOOR) * (1 - t);
    const pulseAmp = selected ? 0.15 : highlighted ? 0.18 : 0.25;
    const pulseHz = selected ? 1.6 : highlighted ? 1.2 : 0.8;
    const pulse = 1.0 + pulseAmp * Math.sin(clock.elapsedTime * Math.PI * pulseHz);
    material.opacity = fadedOpacity * pulse;
  });

  return (
    <group
      position={[midpoint.x, midpoint.y, midpoint.z]}
      quaternion={quaternion}
      onClick={(e) => { e.stopPropagation(); onSelect?.(overlay); }}
    >
      <mesh ref={meshRef} geometry={geometry} material={material} />
      <mesh material={HIT_MAT}>
        <cylinderGeometry args={[Math.tan(overlay.gazeSpread) * overlay.gazeDepth * 1.5, 0.3, overlay.gazeDepth * 0.8, 8]} />
      </mesh>
    </group>
  );
}

// ── Touch mark: billboard sprite ──────────────────────────────────────────────

const TOUCH_COLOR_PERMANENT = new THREE.Color('#ff8844');
const TOUCH_COLOR_EPHEMERAL = new THREE.Color('#ff8844');

function TouchMark({ overlay, selected, highlighted, onSelect }: { overlay: TouchOverlay; selected?: boolean; highlighted?: boolean; onSelect?: (o: TouchOverlay) => void }) {
  const meshRef = useRef<THREE.Group>(null);
  const { camera } = useThree();

  const baseOpacity = 0.5;

  const material = useMemo(() => {
    return new THREE.MeshBasicMaterial({
      color: overlay.ephemeral ? TOUCH_COLOR_EPHEMERAL : TOUCH_COLOR_PERMANENT,
      transparent: true,
      opacity: baseOpacity,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
  }, [overlay.ephemeral, baseOpacity]);

  const ringGeo = useMemo(() => new THREE.RingGeometry(0.54, 1.05, 16), []);
  const dotGeo = useMemo(() => new THREE.CircleGeometry(0.24, 12), []);

  useFrame(({ clock }) => {
    if (!meshRef.current) return;
    meshRef.current.quaternion.copy(camera.quaternion);

    const selScale = selected ? 1.5 : highlighted ? 1.25 : 1.0;
    const pulse = selScale * (1.0 + 0.15 * Math.sin(clock.elapsedTime * Math.PI * 0.9));
    meshRef.current.scale.setScalar(pulse);

    const pulse01 = 0.5 + 0.5 * Math.sin(clock.elapsedTime * Math.PI * 0.9);
    material.opacity = selected ? 0.8 : highlighted ? 0.7 : (0.2 + 0.5 * pulse01);
  });

  return (
    <group
      ref={meshRef}
      position={[overlay.pos[0], overlay.pos[1], overlay.pos[2]]}
      onClick={(e) => { e.stopPropagation(); onSelect?.(overlay); }}
    >
      <mesh geometry={ringGeo} material={material} />
      <mesh geometry={dotGeo} material={material} />
      <mesh material={HIT_MAT}>
        <sphereGeometry args={[1.5, 6, 6]} />
      </mesh>
    </group>
  );
}

// ── Connection lines between related gaze overlays ──────────────────────────

const CONN_COLOR = new THREE.Color('#44bbff');
const CONN_DASH_COLOR = new THREE.Color('#88aaff');

function ConnectionLines({
  connections,
  activeGroup,
  anchorMap,
}: {
  connections: GazeConnection[];
  activeGroup: string | null;
  anchorMap: Map<number, THREE.Vector3>;
}) {
  const lineRef = useRef<THREE.LineSegments>(null);

  const { geometry, material } = useMemo(() => {
    const positions: number[] = [];
    const dashPositions: number[] = [];
    for (const conn of connections) {
      if (conn.id !== activeGroup) continue;
      const pts = conn.anchorIds
        .map(id => anchorMap.get(id))
        .filter((p): p is THREE.Vector3 => !!p);
      if (pts.length < 2) continue;
      const target = conn.style === 'dotted' ? dashPositions : positions;
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          target.push(pts[i].x, pts[i].y + 0.5, pts[i].z);
          target.push(pts[j].x, pts[j].y + 0.5, pts[j].z);
        }
      }
    }

    const geo = new THREE.BufferGeometry();
    if (positions.length > 0) {
      geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    }
    const mat = new THREE.LineBasicMaterial({
      color: CONN_COLOR,
      transparent: true,
      opacity: 0.4,
      depthWrite: false,
      linewidth: 1,
    });

    const dashGeo = new THREE.BufferGeometry();
    if (dashPositions.length > 0) {
      dashGeo.setAttribute('position', new THREE.Float32BufferAttribute(dashPositions, 3));
    }
    const dashMat = new THREE.LineDashedMaterial({
      color: CONN_DASH_COLOR,
      transparent: true,
      opacity: 0.3,
      depthWrite: false,
      dashSize: 1.5,
      gapSize: 1.0,
    });

    return { geometry: geo, material: mat, dashGeometry: dashGeo, dashMaterial: dashMat };
  }, [connections, activeGroup, anchorMap]);

  useFrame(({ clock }) => {
    if (lineRef.current) {
      const pulse = 0.3 + 0.15 * Math.sin(clock.elapsedTime * Math.PI * 0.6);
      material.opacity = pulse;
    }
  });

  if (!activeGroup) return null;

  return (
    <lineSegments ref={lineRef} geometry={geometry} material={material} />
  );
}

// ── Public components ─────────────────────────────────────────────────────────

interface GazeBeamsProps {
  overlays: GazeOverlay[];
  anchors: { id: number; gx: number; gy: number; gz: number }[];
  selectedOverlay?: GazeOverlay | null;
  activeAnchorId?: number | null;
  onSelect?: (o: GazeOverlay) => void;
  connections?: GazeConnection[];
}

export function GazeBeams({ overlays, anchors, selectedOverlay, activeAnchorId, onSelect, connections }: GazeBeamsProps) {
  const anchorMap = useMemo(() => {
    const m = new Map<number, THREE.Vector3>();
    for (const a of anchors) {
      m.set(a.id, new THREE.Vector3(a.gx, a.gy, a.gz));
    }
    return m;
  }, [anchors]);

  const dwelling = overlays.filter(o => o.bodyState === 'dwelling' || o.bodyState === 'scanning');
  const activeGroup = selectedOverlay?._connectionGroup ?? null;

  return (
    <>
      {dwelling.map((o, i) => {
        const pos = anchorMap.get(o.anchorId);
        if (!pos) return null;
        return <GazeBeamFromAnchor key={`gaze-${o.anchorId}-${i}`} anchorPos={pos} overlay={o} selected={selectedOverlay === o} highlighted={activeAnchorId != null && o.anchorId === activeAnchorId} onSelect={onSelect} />;
      })}
      {connections && connections.length > 0 && activeGroup && (
        <ConnectionLines connections={connections} activeGroup={activeGroup} anchorMap={anchorMap} />
      )}
    </>
  );
}

interface TouchMarksProps {
  overlays: TouchOverlay[];
  selectedOverlay?: TouchOverlay | null;
  activeAnchorId?: number | null;
  onSelect?: (o: TouchOverlay) => void;
}

export function TouchMarks({ overlays, selectedOverlay, activeAnchorId, onSelect }: TouchMarksProps) {
  return (
    <>
      {overlays.map((o, i) => (
        <TouchMark key={`touch-${i}`} overlay={o} selected={selectedOverlay === o} highlighted={activeAnchorId != null && o.anchorId === activeAnchorId} onSelect={onSelect} />
      ))}
    </>
  );
}

// ── Floating 3D popups — circular preview at gaze/touch point ────────────────

interface ScenePopupProps {
  gazeOverlay?: GazeOverlay | null;
  touchOverlay?: TouchOverlay | null;
  onOpenDetail?: (item: { type: 'gaze'; overlay: GazeOverlay } | { type: 'touch'; overlay: TouchOverlay }) => void;
  onClose?: () => void;
  recordingBaseUrl?: string;
  lang?: string;
}

export function ScenePopup({ gazeOverlay, touchOverlay, onOpenDetail, onClose, recordingBaseUrl = '', lang }: ScenePopupProps) {
  const [zoomed, setZoomed] = useState(false);

  if (!gazeOverlay && !touchOverlay) return null;

  const pos: [number, number, number] = gazeOverlay
    ? gazeOverlay.gazeTarget
    : touchOverlay!.pos;

  const rawFrame = gazeOverlay?.frameUrl ?? touchOverlay?.frameUrl;
  const frameUrl = rawFrame ? `${recordingBaseUrl}/${rawFrame}` : undefined;
  const label = gazeOverlay
    ? (lang === 'it' ? (gazeOverlay._note_it || gazeOverlay.objectLabel_it || gazeOverlay._note || gazeOverlay.objectLabel || 'Sguardo esperto') : (gazeOverlay._note || gazeOverlay.objectLabel || 'Expert gaze'))
    : (lang === 'it' ? (touchOverlay!.label_it || touchOverlay!.label) : touchOverlay!.label);
  const type = gazeOverlay ? 'gaze' : 'touch';
  const colorClass = `scene-popup--${type}`;

  const handleCircleClick = () => {
    if (gazeOverlay) onOpenDetail?.({ type: 'gaze', overlay: gazeOverlay });
    else if (touchOverlay) onOpenDetail?.({ type: 'touch', overlay: touchOverlay });
  };

  const handleDismiss = () => {
    if (zoomed) setZoomed(false);
    else onClose?.();
  };

  return (
    <Html position={pos} center zIndexRange={[200, 100]} style={{ pointerEvents: 'none' }}>
      <div className={`scene-popup ${colorClass}${zoomed ? ' scene-popup--zoomed' : ''}`} style={{ pointerEvents: 'auto' }}>
        <button className="scene-popup__close" onClick={(e) => { e.stopPropagation(); handleDismiss(); }}>✕</button>
        <div className="scene-popup__circle" onClick={handleCircleClick}>
          {frameUrl ? (
            <img className="scene-popup__img" src={frameUrl} alt={label} />
          ) : (
            <div className="scene-popup__icon">
              {type === 'gaze' ? (
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <ellipse cx="12" cy="12" rx="10" ry="6" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              ) : (
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M12 2C12 2 8 5 8 9.5C8 11.5 9.5 13 11 13.5V21C11 21.6 11.4 22 12 22C12.6 22 13 21.6 13 21V13.5C14.5 13 16 11.5 16 9.5C16 5 12 2 12 2Z" strokeLinejoin="round" />
                </svg>
              )}
            </div>
          )}
        </div>
        <div className="scene-popup__label">{label}</div>
        <button className="scene-popup__expand" onClick={(e) => { e.stopPropagation(); handleCircleClick(); }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="4,10 8,6 12,10" />
          </svg>
        </button>
      </div>
    </Html>
  );
}

// ── Schematic MAP overlays — flat, subtle, non-intrusive ─────────────────────

const MAP_GAZE_COLOR = new THREE.Color('#44bbff');
const MAP_TOUCH_COLOR = new THREE.Color('#ff8844');
const MAP_TOUCH_RING_GEO = new THREE.RingGeometry(0.25, 0.4, 16);
const MAP_TOUCH_DOT_GEO = new THREE.CircleGeometry(0.1, 12);

function MapGazeLine({ anchorPos, overlay, active }: { anchorPos: THREE.Vector3; overlay: GazeOverlay; active: boolean }) {
  const geo = useMemo(() => {
    const target = new THREE.Vector3(...overlay.gazeTarget);
    return new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(anchorPos.x, anchorPos.y + 0.3, anchorPos.z),
      new THREE.Vector3(target.x, target.y + 0.3, target.z),
    ]);
  }, [anchorPos, overlay]);

  const mat = useMemo(() => new THREE.LineBasicMaterial({
    color: MAP_GAZE_COLOR, transparent: true, opacity: active ? 0.5 : 0.2, depthWrite: false,
  }), [active]);

  return <lineSegments geometry={geo} material={mat} />;
}

export function MapGazeLines({ overlays, anchors, activeAnchorId }: {
  overlays: GazeOverlay[];
  anchors: { id: number; gx: number; gy: number; gz: number }[];
  activeAnchorId?: number | null;
}) {
  const anchorMap = useMemo(() => {
    const m = new Map<number, THREE.Vector3>();
    for (const a of anchors) m.set(a.id, new THREE.Vector3(a.gx, a.gy, a.gz));
    return m;
  }, [anchors]);

  const dwelling = overlays.filter(o => o.bodyState === 'dwelling' || o.bodyState === 'scanning');

  return (
    <>
      {dwelling.map((o, i) => {
        const pos = anchorMap.get(o.anchorId);
        if (!pos) return null;
        const active = activeAnchorId != null && o.anchorId === activeAnchorId;
        return <MapGazeLine key={`mg-${o.anchorId}-${i}`} anchorPos={pos} overlay={o} active={active} />;
      })}
    </>
  );
}

export function MapTouchDots({ overlays, activeAnchorId, onSelect }: {
  overlays: TouchOverlay[];
  activeAnchorId?: number | null;
  onSelect?: (o: TouchOverlay) => void;
}) {
  return (
    <>
      {overlays.map((o, i) => {
        const active = activeAnchorId != null && o.anchorId === activeAnchorId;
        return (
          <group
            key={`mt-${i}`}
            position={[o.pos[0], o.pos[1] + 0.3, o.pos[2]]}
            rotation={[-Math.PI / 2, 0, 0]}
            onClick={(e) => { e.stopPropagation(); onSelect?.(o); }}
          >
            <mesh geometry={MAP_TOUCH_RING_GEO}>
              <meshBasicMaterial color={MAP_TOUCH_COLOR} transparent opacity={active ? 0.5 : 0.22} depthWrite={false} />
            </mesh>
            <mesh geometry={MAP_TOUCH_DOT_GEO}>
              <meshBasicMaterial color={MAP_TOUCH_COLOR} transparent opacity={active ? 0.6 : 0.3} depthWrite={false} />
            </mesh>
          </group>
        );
      })}
    </>
  );
}
