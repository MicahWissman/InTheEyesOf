import { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import * as THREE from 'three';
import type { Anchor, GazeOverlay, TouchOverlay, TrajectoryData } from '../types';
import type { GeoRegistration } from '../utils/geoRegistration';
import { resolveAudioUrl } from '../utils/audioResolver';
import { CamMinimap } from './CamMinimap';

const CAM_FOV_DEG = 60;
const CAM_CLUSTER_RADIUS_M = 5;

// Distance bands (metres)
const DIST_CLOSE = 5;
const DIST_APPROACHING = 20;
const DIST_DISTANT = 50;

// Edge-arrow margin from viewport edge (px)
const EDGE_MARGIN = 36;

type Band = 'close' | 'approaching' | 'distant';

interface AnchorEntry {
  anchor: Anchor;
  distM: number;
  band: Band;
}

interface Cluster {
  id: number;
  cx: number;
  cy: number;
  cz: number;
  members: AnchorEntry[];
  minDistM: number;
  band: Band;
}

export interface CamViewProps {
  anchors: Anchor[];
  dampedQRef: React.MutableRefObject<THREE.Quaternion | null>;
  snappedSlamPos: { x: number; y: number; z: number } | null;
  heightOffset: number;
  geoReg: GeoRegistration | null;
  onPlayAnchor: (anchor: Anchor) => void;
  playingAnchorId: number | null;
  audioToast: string | null;
  heardIds?: Set<number>;
  gazeOverlays?: GazeOverlay[];
  touchOverlays?: TouchOverlay[];
  showGaze?: boolean;
  showTouch?: boolean;
  devicePos?: { lat: number; lon: number } | null;
  compassAlpha?: number | null;
  trajectoryData?: TrajectoryData | null;
  lang?: string;
  gender?: string;
}

export function CamView({
  anchors,
  dampedQRef,
  snappedSlamPos,
  heightOffset,
  geoReg,
  onPlayAnchor,
  playingAnchorId,
  audioToast,
  heardIds,
  gazeOverlays,
  touchOverlays,
  showGaze = false,
  showTouch = false,
  devicePos,
  compassAlpha,
  trajectoryData,
  lang,
  gender,
}: CamViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const pillRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const arrowRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const gazeRefs = useRef<(HTMLDivElement | null)[]>([]);
  const touchRefs = useRef<(HTMLDivElement | null)[]>([]);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const posRef = useRef(snappedSlamPos);
  const hRef = useRef(heightOffset);
  const gazeRef = useRef(gazeOverlays);
  const touchRef = useRef(touchOverlays);
  const showGazeRef = useRef(showGaze);
  const showTouchRef = useRef(showTouch);
  useEffect(() => { posRef.current = snappedSlamPos; }, [snappedSlamPos]);
  useEffect(() => { hRef.current = heightOffset; }, [heightOffset]);
  useEffect(() => { gazeRef.current = gazeOverlays; }, [gazeOverlays]);
  useEffect(() => { touchRef.current = touchOverlays; }, [touchOverlays]);
  useEffect(() => { showGazeRef.current = showGaze; }, [showGaze]);
  useEffect(() => { showTouchRef.current = showTouch; }, [showTouch]);

  // Start rear camera — guard against unmount during async getUserMedia
  useEffect(() => {
    let disposed = false;
    let mediaStream: MediaStream | null = null;

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'environment' } })
      .then(stream => {
        if (disposed) {
          stream.getTracks().forEach(t => t.stop());
          return;
        }
        mediaStream = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          video.play().catch(() => {});
        }
      })
      .catch(err => console.warn('[CamView] camera access denied:', err));

    return () => {
      disposed = true;
      mediaStream?.getTracks().forEach(t => t.stop());
      const video = videoRef.current;
      if (video) video.srcObject = null;
    };
  }, []);

  // Filter + distance-gate anchors, then cluster close ones
  const { clusters, soloEntries } = useMemo(() => {
    if (!snappedSlamPos || !geoReg) return { clusters: [] as Cluster[], soloEntries: [] as AnchorEntry[] };

    const entries: AnchorEntry[] = [];
    for (const a of anchors) {
      if (!resolveAudioUrl(a, lang ?? 'en', gender ?? 'f')) continue;
      const dx = a.gx - snappedSlamPos.x;
      const dz = a.gz - snappedSlamPos.z;
      const distSlam = Math.sqrt(dx * dx + dz * dz);
      const distM = distSlam / geoReg.scale;
      if (distM > DIST_DISTANT) continue;
      const band: Band = distM < DIST_CLOSE ? 'close' : distM < DIST_APPROACHING ? 'approaching' : 'distant';
      entries.push({ anchor: a, distM, band });
    }

    // Cluster only close-range anchors (<5m) — at further range they spread out enough
    const closeEntries = entries.filter(e => e.band === 'close');
    const farEntries = entries.filter(e => e.band !== 'close');

    const radiusSq = (CAM_CLUSTER_RADIUS_M * geoReg.scale) ** 2;
    const remaining = [...closeEntries];
    const clustered: Cluster[] = [];

    while (remaining.length) {
      const seed = remaining.shift()!;
      const group: AnchorEntry[] = [seed];
      for (let i = remaining.length - 1; i >= 0; i--) {
        const e = remaining[i];
        const dx = e.anchor.gx - seed.anchor.gx;
        const dz = e.anchor.gz - seed.anchor.gz;
        if (dx * dx + dz * dz < radiusSq) {
          group.push(e);
          remaining.splice(i, 1);
        }
      }
      const cx = group.reduce((s, e) => s + e.anchor.gx, 0) / group.length;
      const cy = group.reduce((s, e) => s + e.anchor.gy, 0) / group.length;
      const cz = group.reduce((s, e) => s + e.anchor.gz, 0) / group.length;
      const minDistM = Math.min(...group.map(e => e.distM));
      clustered.push({ id: clustered.length, cx, cy, cz, members: group, minDistM, band: 'close' });
    }

    return { clusters: clustered, soloEntries: farEntries };
  }, [anchors, snappedSlamPos, geoReg]);

  // All items that need projection: clusters (close) + solo entries (approaching/distant)
  const allItems = useMemo(() => {
    const items: { key: number; wx: number; wy: number; wz: number; type: 'cluster' | 'solo'; band: Band; distM: number }[] = [];
    for (const c of clusters) {
      items.push({ key: c.id, wx: c.cx, wy: c.cy, wz: c.cz, type: 'cluster', band: c.band, distM: c.minDistM });
    }
    for (const e of soloEntries) {
      items.push({ key: 1000 + e.anchor.id, wx: e.anchor.gx, wy: e.anchor.gy, wz: e.anchor.gz, type: 'solo', band: e.band, distM: e.distM });
    }
    return items;
  }, [clusters, soloEntries]);

  const allItemsRef = useRef(allItems);
  useEffect(() => { allItemsRef.current = allItems; }, [allItems]);

  // rAF loop: project each item to screen coordinates.
  // Reads all mutable data from refs so the loop never restarts mid-session.
  useEffect(() => {
    const camera = new THREE.PerspectiveCamera(CAM_FOV_DEG, 1, 0.01, 5000);
    const _v = new THREE.Vector3();
    let rafId = 0;

    const tick = () => {
      rafId = requestAnimationFrame(tick);

      const container = containerRef.current;
      if (!container) return;
      const W = container.clientWidth;
      const H = container.clientHeight;
      if (W === 0 || H === 0) return;

      camera.aspect = W / H;
      camera.updateProjectionMatrix();

      const q = dampedQRef.current;
      if (q) camera.quaternion.copy(q);
      else camera.quaternion.identity();

      const pos = posRef.current;
      camera.position.set(pos?.x ?? 0, (pos?.y ?? 0) + hRef.current, pos?.z ?? 0);
      camera.updateMatrixWorld();

      const items = allItemsRef.current;
      for (const item of items) {
        const pill = pillRefs.current.get(item.key);
        const arrow = arrowRefs.current.get(item.key);

        const v = _v.set(item.wx, item.wy, item.wz);
        v.project(camera);

        const behind = v.z >= 1;
        const offScreen = behind || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1;

        if (pill) {
          if (offScreen || item.band === 'distant') {
            pill.style.left = '-9999px';
            pill.style.top = '-9999px';
          } else {
            const px = (v.x * 0.5 + 0.5) * W;
            const py = (1 - (v.y * 0.5 + 0.5)) * H;
            pill.style.left = `${px}px`;
            pill.style.top = `${py}px`;
          }
        }

        if (arrow) {
          if (item.band === 'distant') {
            let ndcX = v.x;
            let ndcY = v.y;
            if (behind) { ndcX = -ndcX; ndcY = -ndcY; }

            const len = Math.sqrt(ndcX * ndcX + ndcY * ndcY) || 1;
            ndcX /= len;
            ndcY /= len;

            const edgeX = Math.max(EDGE_MARGIN, Math.min(W - EDGE_MARGIN,
              (ndcX * 0.5 + 0.5) * W));
            const edgeY = Math.max(EDGE_MARGIN, Math.min(H - EDGE_MARGIN,
              (1 - (ndcY * 0.5 + 0.5)) * H));

            const angle = Math.atan2(-ndcX, ndcY) * (180 / Math.PI);

            arrow.style.left = `${edgeX}px`;
            arrow.style.top = `${edgeY}px`;
            arrow.style.transform = `translate(-50%, -50%) rotate(${angle}deg)`;
            arrow.style.display = 'flex';
          } else {
            arrow.style.display = 'none';
          }
        }
      }

      if (showGazeRef.current && gazeRef.current) {
        gazeRef.current.forEach((g, i) => {
          const el = gazeRefs.current[i];
          if (!el) return;
          const gv = _v.set(...g.gazeTarget);
          gv.project(camera);
          if (gv.z >= 1 || Math.abs(gv.x) > 1.1 || Math.abs(gv.y) > 1.1) {
            el.style.left = '-9999px';
          } else {
            el.style.left = `${(gv.x * 0.5 + 0.5) * W}px`;
            el.style.top = `${(1 - (gv.y * 0.5 + 0.5)) * H}px`;
          }
        });
      }

      if (showTouchRef.current && touchRef.current) {
        touchRef.current.forEach((t, i) => {
          const el = touchRefs.current[i];
          if (!el) return;
          const tv = _v.set(...t.pos);
          tv.project(camera);
          if (tv.z >= 1 || Math.abs(tv.x) > 1.1 || Math.abs(tv.y) > 1.1) {
            el.style.left = '-9999px';
          } else {
            el.style.left = `${(tv.x * 0.5 + 0.5) * W}px`;
            el.style.top = `${(1 - (tv.y * 0.5 + 0.5)) * H}px`;
          }
        });
      }
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);


  const setPillRef = useCallback((key: number) => (el: HTMLDivElement | null) => {
    if (el) pillRefs.current.set(key, el);
    else pillRefs.current.delete(key);
  }, []);

  const setArrowRef = useCallback((key: number) => (el: HTMLDivElement | null) => {
    if (el) arrowRefs.current.set(key, el);
    else arrowRefs.current.delete(key);
  }, []);

  return (
    <div ref={containerRef} className="cam-container">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video ref={videoRef} className="cam-video" autoPlay playsInline muted />

      <div className="cam-overlay">
        {/* ── Close-range clusters: full context cards ── */}
        {clusters.map(cluster => {
          const isExpanded = expandedId === cluster.id;
          const isSingle = cluster.members.length === 1;
          const entry = cluster.members[0];
          const heard = isSingle && heardIds?.has(entry.anchor.id);
          return (
            <div
              key={`close-${cluster.id}`}
              ref={setPillRef(cluster.id)}
              className={`cam-anchor-card${isExpanded ? ' expanded' : ''}${heard ? ' heard' : ''}`}
              role="button"
              aria-label={
                isSingle
                  ? `Play: ${entry.anchor.narrative_titles?.[lang || 'en'] ?? entry.anchor.narrative_title}`
                  : `${cluster.members.length} narratives here`
              }
              onClick={() => {
                if (isSingle) {
                  onPlayAnchor(entry.anchor);
                } else {
                  setExpandedId(prev => (prev === cluster.id ? null : cluster.id));
                }
              }}
            >
              <div className="cam-anchor-card__header">
                <span className="cam-anchor-play">
                  {isSingle
                    ? (playingAnchorId === entry.anchor.id ? '◼' : '▶')
                    : cluster.members.length}
                </span>
                <span className="cam-anchor-title">
                  {isSingle ? (entry.anchor.narrative_titles?.[lang || 'en'] ?? entry.anchor.narrative_title) : `${cluster.members.length} narratives`}
                </span>
              </div>
              {isSingle && entry.anchor.spatialContext && (
                <div className="cam-anchor-spatial">{entry.anchor.spatialContext}</div>
              )}
              <div className="cam-anchor-dist">{Math.round(cluster.minDistM)}m</div>

              {isExpanded && !isSingle && (
                <div className="cam-narrative-list" onClick={e => e.stopPropagation()}>
                  {cluster.members.map(({ anchor: a }) => (
                    <button
                      key={a.id}
                      className={`cam-narrative-btn${playingAnchorId === a.id ? ' playing' : ''}${heardIds?.has(a.id) ? ' heard' : ''}`}
                      onClick={() => { onPlayAnchor(a); setExpandedId(null); }}
                    >
                      {a.narrative_titles?.[lang || 'en'] ?? a.narrative_title}
                    </button>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {/* ── Approaching anchors: compact pills ── */}
        {soloEntries.filter(e => e.band === 'approaching').map(({ anchor: a, distM }) => {
          const heard = heardIds?.has(a.id);
          return (
            <div
              key={`approach-${a.id}`}
              ref={setPillRef(1000 + a.id)}
              className={`cam-anchor-pill${heard ? ' heard' : ''}`}
              role="button"
              aria-label={`${a.narrative_titles?.[lang || 'en'] ?? a.narrative_title} — ${Math.round(distM)}m`}
              onClick={() => onPlayAnchor(a)}
            >
              <span className="cam-anchor-title">{a.narrative_titles?.[lang || 'en'] ?? a.narrative_title}</span>
              <span className="cam-anchor-dist">{Math.round(distM)}m</span>
            </div>
          );
        })}

        {/* ── Edge arrows for distant anchors (always shown) ── */}
        {soloEntries.filter(e => e.band === 'distant').map(({ anchor: a, distM }) => (
          <div
            key={`arrow-${a.id}`}
            ref={setArrowRef(1000 + a.id)}
            className="cam-anchor-arrow"
            style={{ display: 'none' }}
          >
            <span className="cam-anchor-arrow__chevron">&#x25B2;</span>
            <span className="cam-anchor-arrow__dist">{Math.round(distM)}m</span>
          </div>
        ))}

        {/* ── Gaze marks ── */}
        {showGaze && gazeOverlays?.map((_g, i) => (
          <div
            key={`gaze-${i}`}
            ref={el => { gazeRefs.current[i] = el; }}
            className="cam-gaze-mark"
          />
        ))}

        {/* ── Touch marks ── */}
        {showTouch && touchOverlays?.map((_t, i) => (
          <div
            key={`touch-${i}`}
            ref={el => { touchRefs.current[i] = el; }}
            className="cam-touch-mark"
          />
        ))}
      </div>

      {devicePos && (
        <CamMinimap
          devicePos={devicePos}
          compassAlpha={compassAlpha ?? null}
          anchors={anchors}
          trajectoryData={trajectoryData}
          playingAnchorId={playingAnchorId}
          heardIds={heardIds}
        />
      )}

      {/* status bar removed — narrative pills are self-explanatory */}

      {audioToast && (
        <div className="audio-toast" role="status" aria-live="polite">
          <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor" style={{ flexShrink: 0 }}>
            <path d="M3 7h3l5-4v14l-5-4H3V7z" />
            <path d="M14 7a5 5 0 0 1 0 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" />
          </svg>
          {audioToast}
        </div>
      )}
    </div>
  );
}
