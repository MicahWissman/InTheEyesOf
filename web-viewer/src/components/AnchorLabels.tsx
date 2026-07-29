import { useRef, useState, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import type { Anchor } from '../types';

const DIAMOND_FRAC = 0.55;
const BUBBLE_FRAC = 0.20;
const MAX_DIAMONDS = 15;
const MAX_BUBBLES = 3;
const FALLBACK_DIAMOND = 45;
const FALLBACK_BUBBLE = 25;

interface AnchorLabelsProps {
  anchors: Anchor[];
  onSelect: (anchor: Anchor) => void;
  visitedAnchorIds?: Set<number>;
  playingAnchorId?: number | null;
  userSlamPos?: { x: number; y: number; z: number } | null;
  bubbleDist?: number;
  bubbleMinZoom?: number;
  lang?: string;
}

interface LabelState {
  showDiamond: boolean;
  showBubble: boolean;
  dist: number;
}

export function AnchorLabels({ anchors, onSelect, visitedAnchorIds, playingAnchorId, userSlamPos, bubbleDist: bubbleDistOverride, bubbleMinZoom = 0, lang }: AnchorLabelsProps) {
  const [labelStates, setLabelStates] = useState<Map<number, LabelState>>(new Map());
  const prevKeyRef = useRef('');
  const userPosRef = useRef(userSlamPos);
  userPosRef.current = userSlamPos;

  const anchorPositions = useMemo(() => {
    const m = new Map<number, THREE.Vector3>();
    for (const a of anchors) m.set(a.id, new THREE.Vector3(a.gx, a.gy, a.gz));
    return m;
  }, [anchors]);

  const { diamondDist, bubbleDist } = useMemo(() => {
    if (anchors.length < 2) return { diamondDist: FALLBACK_DIAMOND, bubbleDist: bubbleDistOverride ?? FALLBACK_BUBBLE };
    const box = new THREE.Box3();
    for (const a of anchors) box.expandByPoint(new THREE.Vector3(a.gx, a.gy, a.gz));
    const radius = box.getCenter(new THREE.Vector3()).distanceTo(box.max);
    return {
      diamondDist: Math.max(FALLBACK_DIAMOND, radius * DIAMOND_FRAC),
      bubbleDist: bubbleDistOverride ?? Math.max(FALLBACK_BUBBLE, radius * BUBBLE_FRAC),
    };
  }, [anchors, bubbleDistOverride]);

  useFrame(({ camera }) => {
    const isOrtho = camera instanceof THREE.OrthographicCamera;
    const zoomScale = isOrtho ? Math.max(camera.zoom, 0.1) : 1;

    const gps = userPosRef.current;
    const refPoint = gps
      ? new THREE.Vector3(gps.x, gps.y, gps.z)
      : camera.position;

    const dists: { id: number; dist: number; camDist: number }[] = [];

    for (const a of anchors) {
      const pos = anchorPositions.get(a.id)!;
      const rawCamDist = camera.position.distanceTo(pos);
      const camDist = isOrtho ? rawCamDist / zoomScale : rawCamDist;
      const gpsDist = gps ? refPoint.distanceTo(pos) : camDist;
      dists.push({ id: a.id, dist: gpsDist, camDist });
    }

    dists.sort((a, b) => a.dist - b.dist);

    const next = new Map<number, LabelState>();
    let bubbleCount = 0;
    let diamondCount = 0;

    for (const { id, camDist, dist } of dists) {
      if (camDist > diamondDist) continue;
      if (diamondCount >= MAX_DIAMONDS) continue;
      diamondCount++;
      const zoomOk = !isOrtho || camera.zoom >= bubbleMinZoom;
      const wantBubble = zoomOk && dist < bubbleDist && bubbleCount < MAX_BUBBLES;
      if (wantBubble) bubbleCount++;
      next.set(id, { showDiamond: true, showBubble: wantBubble, dist: camDist });
    }

    const key = Array.from(next.entries())
      .map(([id, s]) => `${id}:${s.showBubble ? 'b' : 'd'}`)
      .join(',');

    if (key !== prevKeyRef.current) {
      prevKeyRef.current = key;
      setLabelStates(next);
    }
  });

  return (
    <>
      {anchors.map((anchor) => {
        const state = labelStates.get(anchor.id);
        if (!state) return null;

        const isPlaying = playingAnchorId === anchor.id;
        const isHeard = visitedAnchorIds?.has(anchor.id) ?? false;
        const isContext = anchor.source === 'context';

        const diamondClass = [
          'anchor-diamond',
          isPlaying && 'anchor-diamond--playing',
          isHeard && !isPlaying && 'anchor-diamond--heard',
          isContext && 'anchor-diamond--context',
        ].filter(Boolean).join(' ');

        const bubbleClass = [
          'anchor-bubble',
          isPlaying && 'anchor-bubble--playing',
          isContext && 'anchor-bubble--context',
        ].filter(Boolean).join(' ');

        return (
          <Html
            key={anchor.id}
            position={[anchor.gx, anchor.gy + 0.6, anchor.gz]}
            center
            zIndexRange={[100, 0]}
            style={{ pointerEvents: 'none' }}
          >
            <div
              className="anchor-label"
              style={{ pointerEvents: 'auto' }}
              onClick={(e) => { e.stopPropagation(); onSelect(anchor); }}
            >
              {state.showBubble && (
                <button className={bubbleClass} type="button">
                  <span className="anchor-bubble__dot" />
                  <span className="anchor-bubble__title">
                    {anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title}
                  </span>
                  <div className="anchor-bubble__caret" />
                </button>
              )}
              <div className={diamondClass} />
            </div>
          </Html>
        );
      })}
    </>
  );
}
