import { useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import * as THREE from 'three';
import type { AnimationEffect, AnimationEffectConnectionLines, AnimationEffectCompassArrow } from '../types';

// ── Glowing connection lines between anchors ────────────────────────────────

interface AnimatedConnectionLinesProps {
  effect: AnimationEffectConnectionLines;
  anchorPositions: Map<number, THREE.Vector3>;
  opacity: number;
}

function AnimatedConnectionLines({ effect, anchorPositions, opacity }: AnimatedConnectionLinesProps) {
  const lineRef = useRef<THREE.LineSegments>(null);
  const glowRef = useRef<THREE.LineSegments>(null);

  const { geo, mat, glowGeo, glowMat } = useMemo(() => {
    const positions: number[] = [];
    const pts = effect.anchorIds
      .map(id => anchorPositions.get(id))
      .filter((p): p is THREE.Vector3 => !!p);

    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        positions.push(pts[i].x, pts[i].y + 0.8, pts[i].z);
        positions.push(pts[j].x, pts[j].y + 0.8, pts[j].z);
      }
    }

    const g = new THREE.BufferGeometry();
    if (positions.length > 0) {
      g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    }

    const color = new THREE.Color(effect.color);
    const m = new THREE.LineDashedMaterial({
      color,
      transparent: true,
      opacity: 0.6,
      depthWrite: false,
      linewidth: 1,
      dashSize: 0.4,
      gapSize: 0.25,
    });

    const gg = g.clone();
    const gm = new THREE.LineDashedMaterial({
      color,
      transparent: true,
      opacity: 0.2,
      depthWrite: false,
      linewidth: 1,
      dashSize: 0.4,
      gapSize: 0.25,
      blending: THREE.AdditiveBlending,
    });

    return { geo: g, mat: m, glowGeo: gg, glowMat: gm };
  }, [effect, anchorPositions]);

  useFrame(({ clock }) => {
    if (!lineRef.current) return;
    const pulse = effect.glowPulse
      ? 0.7 + 0.3 * Math.sin(clock.elapsedTime * Math.PI * 0.8)
      : 1.0;
    mat.opacity = 0.6 * opacity * pulse;
    if (glowRef.current) {
      glowMat.opacity = 0.25 * opacity * pulse;
    }
  });

  if (geo.attributes.position?.count === 0) return null;

  // LineDashedMaterial requires line distances
  useMemo(() => { geo.computeBoundingSphere(); glowGeo.computeBoundingSphere(); }, [geo, glowGeo]);

  return (
    <>
      <lineSegments ref={lineRef} geometry={geo} material={mat}
        onUpdate={(self) => (self as THREE.LineSegments).computeLineDistances()} />
      <lineSegments ref={glowRef} geometry={glowGeo} material={glowMat}
        onUpdate={(self) => (self as THREE.LineSegments).computeLineDistances()} />
    </>
  );
}

// ── Compass arrow pointing from one anchor to another ───────────────────────

interface CompassArrowProps {
  effect: AnimationEffectCompassArrow;
  anchorPositions: Map<number, THREE.Vector3>;
  opacity: number;
}

function CompassArrow({ effect, anchorPositions, opacity }: CompassArrowProps) {
  const meshRef = useRef<THREE.Group>(null);
  const { camera } = useThree();

  const { from, to, color } = useMemo(() => {
    const f = anchorPositions.get(effect.fromAnchorId);
    const t = anchorPositions.get(effect.toAnchorId);
    return { from: f, to: t, color: new THREE.Color(effect.color) };
  }, [effect, anchorPositions]);

  const arrowGeo = useMemo(() => {
    const shape = new THREE.Shape();
    shape.moveTo(0, 1.5);
    shape.lineTo(-0.6, -0.3);
    shape.lineTo(-0.15, 0);
    shape.lineTo(-0.15, -1.2);
    shape.lineTo(0.15, -1.2);
    shape.lineTo(0.15, 0);
    shape.lineTo(0.6, -0.3);
    shape.closePath();
    return new THREE.ShapeGeometry(shape);
  }, []);

  useFrame(({ clock }) => {
    if (!meshRef.current || !from || !to) return;
    // Position at the from anchor, elevated
    meshRef.current.position.set(from.x, from.y + 3, from.z);
    // Face camera (billboard) but rotate arrow to point toward target
    const dir = new THREE.Vector2(to.x - from.x, to.z - from.z).normalize();
    const angle = Math.atan2(dir.x, dir.y);
    meshRef.current.quaternion.copy(camera.quaternion);
    meshRef.current.rotateZ(-angle);

    const pulse = 0.7 + 0.3 * Math.sin(clock.elapsedTime * Math.PI * 1.2);
    meshRef.current.scale.setScalar(1.2 * pulse);
  });

  if (!from || !to) return null;

  return (
    <group ref={meshRef}>
      <mesh geometry={arrowGeo}>
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.7 * opacity}
          side={THREE.DoubleSide}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  );
}

// ── Public: renders all active animation effects ────────────────────────────

interface AnimatedOverlaysProps {
  effects: AnimationEffect[];
  anchorPositions: Map<number, THREE.Vector3>;
  opacity: number;
}

export function AnimatedOverlays({ effects, anchorPositions, opacity }: AnimatedOverlaysProps) {
  if (effects.length === 0 || opacity <= 0) return null;

  return (
    <>
      {effects.map((e, i) => {
        if (e.type === 'connection_lines') {
          return (
            <AnimatedConnectionLines
              key={`conn-${i}`}
              effect={e}
              anchorPositions={anchorPositions}
              opacity={opacity}
            />
          );
        }
        if (e.type === 'compass_arrow') {
          return (
            <CompassArrow
              key={`arrow-${i}`}
              effect={e}
              anchorPositions={anchorPositions}
              opacity={opacity}
            />
          );
        }
        return null;
      })}
    </>
  );
}
