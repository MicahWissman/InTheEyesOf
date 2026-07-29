import { useState, useEffect } from 'react';
import { useAudio } from '../contexts/AudioContext';
import type { Anchor } from '../types';

export interface NearbyAnchorInfo {
  anchor: Anchor;
  distanceM: number;
  bearingDeg: number;
  heard: boolean;
}

export interface NarrativeBubbleProps {
  nearbyAnchors: NearbyAnchorInfo[];
  playingTitle: string | null;
  queuedTitle: string | null;
  onPlayAnchor: (anchor: Anchor) => void;
  onSelectAnchor?: (anchor: Anchor) => void;
  viewMode: string;
  compassHeading: number | null;
  lang?: string;
  sidebarCollapsed?: boolean;
  onReopenSidebar?: () => void;
}

const CLOSE_M = 10;

function bearingLabel(deg: number): string {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  return dirs[Math.round(((deg % 360) + 360) % 360 / 45) % 8];
}

function relativeArrowDeg(geoBearing: number, compass: number | null): number {
  if (compass === null) return geoBearing;
  return ((geoBearing - compass) % 360 + 360) % 360;
}

function glowOffset(bearingDeg: number, compass: number | null, radius: number) {
  const rel = relativeArrowDeg(bearingDeg, compass);
  const rad = rel * Math.PI / 180;
  return { x: -Math.sin(rad) * radius, y: -Math.cos(rad) * radius };
}

const R = 18;
const C = 2 * Math.PI * R;
const CX = 20;
const CY = 20;

export function NarrativeBubble({
  nearbyAnchors,
  playingTitle,
  queuedTitle,
  onPlayAnchor,
  viewMode,
  compassHeading,
  lang,
  sidebarCollapsed,
  onReopenSidebar,
}: NarrativeBubbleProps) {
  const {
    isPlaying, currentTime, duration,
    pauseAudio, resumeAudio, audioEnabled,
    currentAnchorId,
  } = useAudio();
  const [expanded, setExpanded] = useState(false);

  const nearest = nearbyAnchors[0] ?? null;
  const isNearestClose = nearest !== null && nearest.distanceM < CLOSE_M;
  const isPaused = !isPlaying && currentAnchorId != null && currentTime > 0;
  const state: 'idle' | 'discoverable' | 'playing' =
    (isPlaying || isPaused || playingTitle != null) ? 'playing' : nearest ? 'discoverable' : 'idle';

  useEffect(() => {
    if (isPlaying) setExpanded(false);
  }, [isPlaying]);

  if (!audioEnabled || viewMode === 'cam') return null;

  const progressFraction = duration > 0 ? currentTime / duration : 0;
  const dashOffset = C * (1 - progressFraction);

  const handleTap = () => {
    if (state === 'playing' && sidebarCollapsed && onReopenSidebar) {
      onReopenSidebar();
      return;
    }
    if (state === 'playing') {
      if (isPlaying) pauseAudio();
      else resumeAudio();
    } else if (state === 'discoverable') {
      if (nearbyAnchors.length === 1) {
        onPlayAnchor(nearest!.anchor);
      } else {
        setExpanded(v => !v);
      }
    }
  };

  // Directional glow for close-range bubble
  let mainStyle: React.CSSProperties | undefined;
  if (state === 'discoverable' && isNearestClose) {
    const g = glowOffset(nearest!.bearingDeg, compassHeading, 14);
    mainStyle = {
      boxShadow: `${g.x.toFixed(1)}px ${g.y.toFixed(1)}px 22px 4px rgba(0, 255, 136, 0.4)`,
      animation: 'none',
    };
  }

  const ariaLabel =
    state === 'idle' ? 'No anchors nearby'
    : state === 'discoverable'
      ? nearbyAnchors.length === 1
        ? `Play: ${nearest!.anchor.narrative_titles?.[lang || 'en'] ?? nearest!.anchor.narrative_title}`
        : `${nearbyAnchors.length} anchors nearby`
    : `Playing: ${playingTitle ?? 'audio'}`;

  return (
    <div className={`narrative-bubble narrative-bubble--${state}${expanded ? ' narrative-bubble--expanded' : ''}`}>
      <button
        className={`narrative-bubble__main${isNearestClose && state === 'discoverable' ? ' narrative-bubble__main--close' : ''}`}
        onClick={handleTap}
        aria-label={ariaLabel}
        style={mainStyle}
      >
        <svg className="narrative-bubble__ring" width="40" height="40" viewBox="0 0 40 40">
          <circle className="narrative-bubble__track" cx={CX} cy={CY} r={R} />
          {state === 'playing' && (
            <circle
              className="narrative-bubble__progress"
              cx={CX} cy={CY} r={R}
              strokeDasharray={C}
              strokeDashoffset={dashOffset}
            />
          )}
        </svg>

        <div className="narrative-bubble__icon">
          {state === 'playing' ? (
            isPlaying ? (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <rect x="3" y="2" width="3.5" height="12" rx="1" />
                <rect x="9.5" y="2" width="3.5" height="12" rx="1" />
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                <polygon points="4,2 14,8 4,14" />
              </svg>
            )
          ) : state === 'discoverable' ? (
            nearbyAnchors.length > 1 && !isNearestClose ? (
              <span className="narrative-bubble__count">{nearbyAnchors.length}</span>
            ) : (
              <span className="narrative-bubble__pulse-dot" />
            )
          ) : (
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <path d="M3 10V8a5 5 0 0 1 10 0v2" />
              <rect x="1" y="10" width="3" height="4" rx="1" fill="currentColor" stroke="none" />
              <rect x="12" y="10" width="3" height="4" rx="1" fill="currentColor" stroke="none" />
            </svg>
          )}
        </div>

        {state === 'discoverable' && !expanded && (
          <div className="narrative-bubble__label">
            <span className="narrative-bubble__title">{nearest!.anchor.narrative_titles?.[lang || 'en'] ?? nearest!.anchor.narrative_title}</span>
            <span className="narrative-bubble__dist">
              {isNearestClose ? (
                `${Math.round(nearest!.distanceM)}m`
              ) : (
                <>
                  <span
                    className="narrative-bubble__arrow narrative-bubble__arrow--inline"
                    style={{ transform: `rotate(${relativeArrowDeg(nearest!.bearingDeg, compassHeading)}deg)` }}
                    aria-hidden="true"
                  >↑</span>
                  {bearingLabel(nearest!.bearingDeg)} · {Math.round(nearest!.distanceM)}m
                </>
              )}
            </span>
          </div>
        )}
        {state === 'playing' && (
          <div className="narrative-bubble__label">
            <span className="narrative-bubble__title">{playingTitle ?? 'Playing…'}</span>
            {sidebarCollapsed ? (
              <span className="narrative-bubble__subtitle narrative-bubble__subtitle--pullup">
                <svg width="10" height="8" viewBox="0 0 10 8" fill="currentColor" aria-hidden="true">
                  <polygon points="5,0 10,8 0,8" />
                </svg>
                Tap to open
              </span>
            ) : queuedTitle ? (
              <span className="narrative-bubble__subtitle">Up next: {queuedTitle}</span>
            ) : null}
          </div>
        )}
      </button>

      {expanded && state === 'discoverable' && (
        <div className="narrative-bubble__nearby">
          {nearbyAnchors.map(({ anchor, distanceM, bearingDeg, heard }) => {
            const isClose = distanceM < CLOSE_M;
            const itemGlow = isClose
              ? (() => {
                  const g = glowOffset(bearingDeg, compassHeading, 8);
                  return {
                    boxShadow: `inset ${g.x.toFixed(1)}px ${g.y.toFixed(1)}px 10px rgba(0,255,136,0.25)`,
                  } as React.CSSProperties;
                })()
              : undefined;

            return (
              <button
                key={anchor.id}
                className={`narrative-bubble__nearby-item${isClose ? ' narrative-bubble__nearby-item--close' : ''}${heard ? ' narrative-bubble__nearby-item--heard' : ''}`}
                onClick={() => { onPlayAnchor(anchor); setExpanded(false); }}
                style={itemGlow}
              >
                {isClose ? (
                  <span className="narrative-bubble__pulse-dot" />
                ) : (
                  <span
                    className="narrative-bubble__arrow"
                    style={{ transform: `rotate(${relativeArrowDeg(bearingDeg, compassHeading)}deg)` }}
                    aria-hidden="true"
                  >↑</span>
                )}
                <span className="narrative-bubble__nearby-title">
                  {anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title}
                </span>
                <span className="narrative-bubble__nearby-dist">
                  {isClose
                    ? `${Math.round(distanceM)}m`
                    : `${bearingLabel(bearingDeg)} · ${Math.round(distanceM)}m`}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
