import { useRef, useMemo, useCallback } from 'react';
import { useFrame, type ThreeEvent } from '@react-three/fiber';
import * as THREE from 'three';
import type { Anchor } from '../types';
import type { ProximityCategory } from '../utils/proximity';

const FADE_NEAR_FRAC       = 0.07;
const FADE_FAR_FRAC        = 0.55;
const FALLBACK_FADE_NEAR   = 6;
const FALLBACK_FADE_FAR    = 40;
const ANCHOR_OPACITY_FLOOR = 0.15;
const CLUSTER_RADIUS       = 1.5;

const COLOR_PLAYING = new THREE.Color('#00ff88');
const COLOR_UNHEARD = new THREE.Color('#00cc6a');
const COLOR_HEARD   = new THREE.Color('#666666');
const COLOR_CONTEXT = new THREE.Color('#4488ff');

function makeDiamond(r: number): THREE.BufferGeometry {
  const shape = new THREE.Shape();
  shape.moveTo(0, r);
  shape.lineTo(r, 0);
  shape.lineTo(0, -r);
  shape.lineTo(-r, 0);
  shape.closePath();
  return new THREE.ShapeGeometry(shape);
}
function makeDiamondRing(inner: number, outer: number): THREE.BufferGeometry {
  const shape = new THREE.Shape();
  shape.moveTo(0, outer);
  shape.lineTo(outer, 0);
  shape.lineTo(0, -outer);
  shape.lineTo(-outer, 0);
  shape.closePath();
  const hole = new THREE.Path();
  hole.moveTo(0, inner);
  hole.lineTo(inner, 0);
  hole.lineTo(0, -inner);
  hole.lineTo(-inner, 0);
  hole.closePath();
  shape.holes.push(hole);
  return new THREE.ShapeGeometry(shape);
}

const CIRCLE_LG = new THREE.CircleGeometry(0.45, 24);
const CIRCLE_GLOW_LG = new THREE.RingGeometry(0.4, 0.7, 24);
const DIAMOND_SM = makeDiamond(0.32);
const DIAMOND_GLOW_SM = makeDiamondRing(0.28, 0.52);
const HIT_CIRCLE = new THREE.CircleGeometry(0.7, 12);
const HIT_DIAMOND = makeDiamond(0.7);
const HIT_MAT = new THREE.MeshBasicMaterial({ opacity: 0, transparent: true, depthWrite: false });

interface HotspotPrismProps {
  anchor: Anchor;
  isDimmed: boolean;
  isPlaying: boolean;
  isHeard: boolean;
  isSelected: boolean;
  onSelect: (anchor: Anchor, event: ThreeEvent<MouseEvent>) => void;
  fadeNear: number;
  fadeFar: number;
}

function HotspotPrism({ anchor, isDimmed, isPlaying, isHeard, isSelected, onSelect, fadeNear, fadeFar }: HotspotPrismProps) {
  const groupRef = useRef<THREE.Group>(null);
  const matRef = useRef<THREE.MeshBasicMaterial>(null);
  const glowRef = useRef<THREE.MeshBasicMaterial>(null);

  const anchorPos = useMemo(
    () => new THREE.Vector3(anchor.gx, anchor.gy, anchor.gz),
    [anchor.gx, anchor.gy, anchor.gz],
  );

  const isMajor = (anchor.score ?? 0) >= 0.35 || anchor.hasAudio;

  useFrame(({ camera, clock }) => {
    if (!matRef.current || !glowRef.current || !groupRef.current) return;

    const isContext = anchor.source === 'context';
    const baseColor = isContext ? COLOR_CONTEXT : COLOR_UNHEARD;
    const color = isPlaying ? COLOR_PLAYING : isHeard ? COLOR_HEARD : baseColor;
    matRef.current.color.copy(color);
    glowRef.current.color.copy(color);

    const dist = camera.position.distanceTo(anchorPos);
    const t    = Math.max(0, Math.min(1, (dist - fadeNear) / (fadeFar - fadeNear)));
    const fade = ANCHOR_OPACITY_FLOOR + (1.0 - ANCHOR_OPACITY_FLOOR) * (1.0 - t);
    const opacity = isSelected ? fade * 0.14
      : isDimmed ? fade * 0.35
      : isHeard && !isPlaying ? fade * 0.4
      : fade;
    matRef.current.opacity = opacity;
    glowRef.current.opacity = opacity * 0.3;

    groupRef.current.quaternion.copy(camera.quaternion);

    const scale = isPlaying
      ? 1.0 + 0.12 * Math.sin(clock.elapsedTime * Math.PI * 3.0)
      : 1.0;
    groupRef.current.scale.setScalar(scale);
  });

  return (
    <group
      ref={groupRef}
      position={[anchor.gx, anchor.gy, anchor.gz]}
      onClick={(e) => { e.stopPropagation(); onSelect(anchor, e); }}
    >
      <mesh geometry={isMajor ? CIRCLE_LG : DIAMOND_SM}>
        <meshBasicMaterial ref={matRef} transparent depthWrite={false} />
      </mesh>
      <mesh geometry={isMajor ? CIRCLE_GLOW_LG : DIAMOND_GLOW_SM}>
        <meshBasicMaterial ref={glowRef} transparent depthWrite={false} />
      </mesh>
      <mesh geometry={isMajor ? HIT_CIRCLE : HIT_DIAMOND} material={HIT_MAT} />
    </group>
  );
}

interface HotspotsProps {
  anchors: Anchor[];
  onSelect: (anchor: Anchor) => void;
  onCluster?: (anchors: Anchor[], screenX: number, screenY: number) => void;
  selectedId?: number;
  dimmedIds?: number[];
  proximityMap?: Map<number, ProximityCategory>;
  visitedAnchorIds?: Set<number>;
  playingAnchorId?: number | null;
}

export const Hotspots = ({
  anchors,
  onSelect,
  onCluster,
  selectedId,
  dimmedIds,
  proximityMap: _proximityMap,
  visitedAnchorIds,
  playingAnchorId,
}: HotspotsProps) => {
  const { fadeNear, fadeFar } = useMemo(() => {
    if (anchors.length < 2) return { fadeNear: FALLBACK_FADE_NEAR, fadeFar: FALLBACK_FADE_FAR };
    const box = new THREE.Box3();
    for (const a of anchors) box.expandByPoint(new THREE.Vector3(a.gx, a.gy, a.gz));
    const radius = box.getCenter(new THREE.Vector3()).distanceTo(box.max);
    return {
      fadeNear: Math.max(FALLBACK_FADE_NEAR, radius * FADE_NEAR_FRAC),
      fadeFar: Math.max(FALLBACK_FADE_FAR, radius * FADE_FAR_FRAC),
    };
  }, [anchors]);

  const handlePrismClick = useCallback((anchor: Anchor, event: ThreeEvent<MouseEvent>) => {
    const rSq = CLUSTER_RADIUS * CLUSTER_RADIUS;
    const neighbors = anchors.filter(a => {
      if (a.id === anchor.id) return false;
      const dx = a.gx - anchor.gx;
      const dy = a.gy - anchor.gy;
      const dz = a.gz - anchor.gz;
      return dx * dx + dy * dy + dz * dz < rSq;
    });

    if (neighbors.length === 0 || !onCluster) {
      onSelect(anchor);
      return;
    }

    const group = [anchor, ...neighbors];
    const canvas = (event.nativeEvent.target as HTMLElement).closest('canvas');
    if (!canvas) { onSelect(anchor); return; }
    const rect = canvas.getBoundingClientRect();
    const v = new THREE.Vector3(anchor.gx, anchor.gy, anchor.gz);
    v.project(event.camera);
    const screenX = (v.x * 0.5 + 0.5) * rect.width;
    const screenY = (1 - (v.y * 0.5 + 0.5)) * rect.height;
    onCluster(group, screenX, screenY);
  }, [anchors, onSelect, onCluster]);

  return (
    <>
      {anchors.map((anchor) => {
        const isDimmed = !!(dimmedIds && dimmedIds.length > 0 && !dimmedIds.includes(anchor.id));
        return (
          <HotspotPrism
            key={anchor.id}
            anchor={anchor}
            isDimmed={isDimmed}
            isPlaying={playingAnchorId === anchor.id}
            isHeard={visitedAnchorIds?.has(anchor.id) ?? false}
            isSelected={selectedId === anchor.id}
            onSelect={handlePrismClick}
            fadeNear={fadeNear}
            fadeFar={fadeFar}
          />
        );
      })}
    </>
  );
};
