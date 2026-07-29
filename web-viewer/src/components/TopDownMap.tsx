import { useEffect, useRef, useCallback, useState } from 'react';
import { MapContainer, TileLayer, Polyline, CircleMarker, useMap, Marker, useMapEvents } from 'react-leaflet';
import type { LatLngTuple, Map as LeafletMap } from 'leaflet';
import L from 'leaflet';

// Initial zoom for both panels — ~2 levels tighter than the old z18.
// At z20 Leaflet shows ~19 m per 256 px tile (~20–30 m viewport on typical phones).
const MAP_INITIAL_ZOOM = 20;
import 'leaflet/dist/leaflet.css';
import type { Anchor, TrajectoryData, TrajectoryPoint } from '../types';
import type { ProximityCategory } from '../utils/proximity';


function findClosestPoint(path: TrajectoryPoint[], t: number): TrajectoryPoint | null {
  if (!path.length) return null;
  let lo = 0;
  let hi = path.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (path[mid].t < t) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(path[lo - 1].t - t) < Math.abs(path[lo].t - t)) {
    return path[lo - 1];
  }
  return path[lo];
}

// Fires onReady once with the Leaflet map instance so parents can subscribe to
// move/zoom events for iso-camera coupling without importing Leaflet themselves.
function WhenReady({ onReady }: { onReady: (map: LeafletMap) => void }) {
  const map = useMap();
  const called = useRef(false);
  useEffect(() => {
    if (!called.current) { called.current = true; onReady(map); }
  }, [map, onReady]);
  return null;
}

function MapFlyTo({ center, zoom }: { center: LatLngTuple; zoom?: number }) {
  const map = useMap();
  const didFly = useRef(false);
  useEffect(() => {
    if (!didFly.current) {
      map.setView(center, zoom ?? MAP_INITIAL_ZOOM);
      didFly.current = true;
    }
  }, [map, center, zoom]);
  return null;
}

// Continuously tracks devicePos when followMode is true
function FollowController({
  devicePos,
  followMode,
}: {
  devicePos: { lat: number; lon: number } | null;
  followMode: boolean;
}) {
  const map = useMap();
  const firstFix = useRef(true);
  useEffect(() => {
    if (followMode && devicePos) {
      if (firstFix.current) {
        firstFix.current = false;
        map.flyTo([devicePos.lat, devicePos.lon], MAP_INITIAL_ZOOM, { duration: 1.2 });
      } else {
        map.setView([devicePos.lat, devicePos.lon], map.getZoom());
      }
    }
  }, [map, devicePos, followMode]);
  return null;
}

interface RecenterControlProps {
  devicePos: { lat: number; lon: number } | null;
  followMode: boolean;
  onRecenter: () => void;
  popupOpen?: boolean;
}

function RecenterControl({ devicePos, followMode, onRecenter, popupOpen }: RecenterControlProps) {
  if (popupOpen) return null;
  const map = useMap();

  const handleClick = useCallback(() => {
    if (devicePos) {
      map.flyTo([devicePos.lat, devicePos.lon], map.getZoom());
    }
    onRecenter();
  }, [map, devicePos, onRecenter]);

  // Position above zoom controls (bottom-right, offset upward)
  return (
    <div
      className="leaflet-bottom leaflet-right"
      style={{ marginBottom: '80px', pointerEvents: 'auto' }}
    >
      <div className="leaflet-control">
        <button
          className={`map-recenter-btn${followMode ? ' follow-active' : ''}`}
          onClick={handleClick}
          title={followMode ? 'Following GPS (tap to exit)' : 'Fly to GPS position'}
          disabled={!devicePos}
        >
          {followMode ? (
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <circle cx="9" cy="9" r="7" fill="#4488ff" stroke="white" strokeWidth="1.5" />
              <line x1="9" y1="1" x2="9" y2="4" stroke="white" strokeWidth="2" strokeLinecap="round" />
              <line x1="9" y1="14" x2="9" y2="17" stroke="white" strokeWidth="2" strokeLinecap="round" />
              <line x1="1" y1="9" x2="4" y2="9" stroke="white" strokeWidth="2" strokeLinecap="round" />
              <line x1="14" y1="9" x2="17" y2="9" stroke="white" strokeWidth="2" strokeLinecap="round" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <circle cx="9" cy="9" r="3" fill="#4488ff" />
              <circle cx="9" cy="9" r="6" stroke="#4488ff" strokeWidth="1.5" fill="none" />
              <line x1="9" y1="1" x2="9" y2="4" stroke="#4488ff" strokeWidth="2" strokeLinecap="round" />
              <line x1="9" y1="14" x2="9" y2="17" stroke="#4488ff" strokeWidth="2" strokeLinecap="round" />
              <line x1="1" y1="9" x2="4" y2="9" stroke="#4488ff" strokeWidth="2" strokeLinecap="round" />
              <line x1="14" y1="9" x2="17" y2="9" stroke="#4488ff" strokeWidth="2" strokeLinecap="round" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}

function makeCompassIcon(alpha: number | null): L.DivIcon {
  const hasCompass = alpha !== null;
  const rot = hasCompass ? (360 - alpha! + 180) % 360 : 0;
  // Google Maps style: pulsating blue dot + wide heading cone with gradient fade
  const S = 160;
  const C = S / 2;
  const R_DOT = 8;
  const R_CONE = 72;
  const HALF_ANGLE = 35;
  const ax = -Math.sin(HALF_ANGLE * Math.PI / 180) * R_CONE;
  const ay = -Math.cos(HALF_ANGLE * Math.PI / 180) * R_CONE;
  const bx = Math.sin(HALF_ANGLE * Math.PI / 180) * R_CONE;
  const by = ay;

  const svgContent = hasCompass
    ? `<svg width="${S}" height="${S}" viewBox="${-C} ${-C} ${S} ${S}" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <radialGradient id="cone-grad" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse"
                          fx="0" fy="0" gradientTransform="scale(${R_CONE})">
            <stop offset="0.15" stop-color="#4488ff" stop-opacity="0.8"/>
            <stop offset="0.7"  stop-color="#4488ff" stop-opacity="0.25"/>
            <stop offset="1"    stop-color="#4488ff" stop-opacity="0"/>
          </radialGradient>
        </defs>
        <g transform="rotate(${rot})">
          <path d="M0,0 L${ax.toFixed(1)},${ay.toFixed(1)} A${R_CONE},${R_CONE} 0 0,1 ${bx.toFixed(1)},${by.toFixed(1)} Z"
                fill="url(#cone-grad)" stroke="none"/>
        </g>
        <circle class="gps-pulse" r="${R_DOT + 5}" fill="rgba(68,136,255,0.2)" stroke="none"/>
        <circle r="${R_DOT}" fill="#4488ff" stroke="white" stroke-width="2.5"/>
      </svg>`
    : `<svg width="28" height="28" viewBox="-14 -14 28 28" xmlns="http://www.w3.org/2000/svg">
        <circle class="gps-pulse" r="${R_DOT + 5}" fill="rgba(68,136,255,0.2)" stroke="none"/>
        <circle r="${R_DOT}" fill="#4488ff" stroke="white" stroke-width="2.5"/>
      </svg>`;

  return L.divIcon({
    html: svgContent,
    className: 'compass-marker',
    iconAnchor: hasCompass ? [C, C] : [14, 14],
    iconSize: hasCompass ? [S, S] : [28, 28],
  });
}

function useCurrentZoom() {
  const [zoom, setZoom] = useState(18);
  useMapEvents({
    zoomend: (e) => setZoom(e.target.getZoom()),
  });
  return zoom;
}

function ZoomAwareMarkers({
  anchorPoints,
  selectedAnchor,
  onSelectAnchor,
  selectedPt,
  proximityMap,
  currentAnchorId,
  visitedAnchorIds,
}: {
  anchorPoints: { anchor: Anchor; pt: TrajectoryPoint }[];
  selectedAnchor: Anchor | null;
  onSelectAnchor: (anchor: Anchor) => void;
  selectedPt: TrajectoryPoint | null;
  proximityMap?: Map<number, ProximityCategory>;
  currentAnchorId?: number | null;
  visitedAnchorIds?: Set<number>;
}) {
  const currentZoom = useCurrentZoom();
  const dynamicRadius = Math.max(4, Math.min(20, (currentZoom - 12) * 2.5));
  const dynamicRadiusSelected = dynamicRadius * 1.6;

  return (
    <>
      {anchorPoints.map(({ anchor, pt }) => {
        const isSelected = selectedAnchor?.id === anchor.id;
        const isPlaying = currentAnchorId === anchor.id;
        const isVisited = visitedAnchorIds?.has(anchor.id) ?? false;
        const proximity = proximityMap?.get(anchor.id);

        const isContext = anchor.source === 'context';
        const categoryColor = anchor.contentCategory === 'personal' ? '#ff4444'
          : anchor.contentCategory === 'heritage' ? '#00cc66'
          : anchor.contentCategory === 'nature' ? '#4488ff'
          : anchor.contentCategory === 'context' ? '#888888'
          : anchor.contentCategory === 'review' ? '#ffaa00'
          : isContext ? '#4488ff' : '#00ff88';
        const color = isPlaying ? '#00ff88'
          : isSelected || proximity === 'in_range' ? '#00ff88'
          : isVisited && !isSelected ? '#999999'
          : categoryColor;
        const fillOpacity = isPlaying
          ? 1.0
          : isVisited && !isSelected
          ? 0.4
          : proximity === 'distant'
          ? 0.5
          : isSelected || proximity === 'in_range'
          ? 1.0
          : 0.9;
        const weight = isPlaying ? 3 : isSelected || proximity === 'in_range' ? 3 : proximity === 'discoverable' ? 2 : 1;
        const className = isPlaying
          ? 'anchor-playing'
          : proximity === 'in_range'
          ? 'anchor-in-range'
          : proximity === 'discoverable'
          ? 'anchor-discoverable'
          : undefined;

        const isMajor = (anchor.score ?? 0) >= 0.35;
        const scaleBase = isMajor ? dynamicRadius : dynamicRadius * 0.7;
        const baseRadius = isVisited && !isPlaying ? scaleBase * 0.8 : scaleBase;
        const r = isSelected ? dynamicRadiusSelected : baseRadius;
        const container = r * 2 + 4;
        const shape = isMajor
          ? `border-radius:50%;`
          : `border-radius:2px;transform:rotate(45deg);`;
        const icon = L.divIcon({
          html: `<div style="width:${container}px;height:${container}px;display:flex;align-items:center;justify-content:center;"><div class="${className ?? ''}" style="width:${r * 2}px;height:${r * 2}px;background:${color};opacity:${fillOpacity};${shape}border:${weight}px solid rgba(0,0,0,0.25);box-sizing:border-box;"></div></div>`,
          className: '',
          iconSize: [container, container],
          iconAnchor: [container / 2, container / 2],
        });

        return (
          <Marker
            key={anchor.id}
            position={[pt.lat, pt.lon]}
            icon={icon}
            eventHandlers={{ click: () => onSelectAnchor(anchor) }}
          />
        );
      })}

      {selectedPt && (
        <CircleMarker
          center={[selectedPt.lat, selectedPt.lon]}
          radius={12}
          pathOptions={{ color: '#00ff88', fillColor: '#00ff88', fillOpacity: 0.3, weight: 2 }}
        />
      )}

      {/* Pulse ring around the currently-playing anchor */}
      {anchorPoints.map(({ anchor, pt }) =>
        currentAnchorId === anchor.id ? (
          <CircleMarker
            key={`playing-ring-${anchor.id}`}
            center={[pt.lat, pt.lon]}
            radius={dynamicRadiusSelected + 6}
            pathOptions={{ color: '#ffffff', fillColor: 'transparent', fillOpacity: 0, weight: 1.5, opacity: 0.6, className: 'anchor-playing-ring' }}
          />
        ) : null,
      )}
    </>
  );
}

interface TopDownMapProps {
  trajectoryData: TrajectoryData | null;
  trajectoryError: boolean;
  anchors: Anchor[];
  selectedAnchor: Anchor | null;
  onSelectAnchor: (anchor: Anchor) => void;
  devicePos: { lat: number; lon: number } | null;
  gpsStatus: 'waiting' | 'active' | 'error' | 'too_far';
  gpsErrorMsg: string | null;
  isMobile?: boolean;
  compassAlpha?: number | null;
  followMode: boolean;
  onFollowModeChange: (v: boolean) => void;
  onRecenterPointCloud?: () => void;
  proximityMap?: Map<number, ProximityCategory>;
  currentAnchorId?: number | null;     // currently-playing anchor — shows pulse ring
  visitedAnchorIds?: Set<number>;      // already-heard anchors — visually muted
  onMapReady?: (map: LeafletMap) => void;  // called once with the Leaflet instance
  popupOpen?: boolean;                 // anchor detail popup is open — hide map chrome
  connectionLines?: LatLngTuple[][];   // connection polylines to render when a connected gaze is active
}

export const TopDownMap = ({
  trajectoryData,
  trajectoryError,
  anchors,
  selectedAnchor,
  onSelectAnchor,
  devicePos,
  gpsStatus: _gpsStatus,
  gpsErrorMsg: _gpsErrorMsg,
  compassAlpha = null,
  followMode,
  onFollowModeChange,
  onRecenterPointCloud,
  proximityMap,
  currentAnchorId = null,
  visitedAnchorIds,
  onMapReady,
  popupOpen = false,
  connectionLines,
}: TopDownMapProps) => {
  const handleRecenter = useCallback(() => {
    if (followMode) {
      onFollowModeChange(false);
    } else {
      onFollowModeChange(true);
      onRecenterPointCloud?.();
    }
  }, [followMode, onFollowModeChange, onRecenterPointCloud]);

  if (trajectoryError) {
    return (
      <div className="topdown-map-container topdown-map-error">
        <p>trajectory_latlon.json not found for this recording.</p>
        <p className="topdown-map-hint">Run: python scripts/export_trajectory_latlon.py &lt;mps_slam_dir&gt; &lt;output&gt;</p>
      </div>
    );
  }

  if (!trajectoryData) {
    return <div className="topdown-map-container topdown-map-loading">Loading trajectory...</div>;
  }

  const path = trajectoryData.path;
  const polyline: LatLngTuple[] = path.map(p => [p.lat, p.lon]);
  const mid = Math.floor(path.length / 2);
  const center: LatLngTuple = path.length ? [path[mid].lat, path[mid].lon] : [0, 0];

  const anchorPoints = anchors
    .filter(a => a.start_ts !== undefined || a.gps)
    .map(a => {
      const trajPt = a.start_ts ? findClosestPoint(path, a.start_ts) : null;
      if (trajPt) return { anchor: a, pt: trajPt };
      if (a.gps) return { anchor: a, pt: { t: 0, lat: a.gps[0], lon: a.gps[1], alt: 0 } as TrajectoryPoint };
      return null;
    })
    .filter(x => x !== null) as { anchor: Anchor; pt: TrajectoryPoint }[];

  const selectedPt = selectedAnchor
    ? (selectedAnchor.start_ts ? findClosestPoint(path, selectedAnchor.start_ts) : null)
      ?? (selectedAnchor.gps ? { t: 0, lat: selectedAnchor.gps[0], lon: selectedAnchor.gps[1], alt: 0 } as TrajectoryPoint : null)
    : null;

  const compassIcon = devicePos ? makeCompassIcon(compassAlpha) : null;

  return (
    <div className={`topdown-map-container${popupOpen ? ' popup-open' : ''}`}>
      <div className="topdown-label">
        Map View
        <span className="topdown-attribution"> · Tiles © Esri</span>
      </div>
      <MapContainer
        style={{ width: '100%', height: '100%' }}
        zoom={MAP_INITIAL_ZOOM}
        minZoom={10}
        maxZoom={22}
        zoomSnap={0}
        center={center}
        zoomControl={false}
        scrollWheelZoom={true}
      >
        {onMapReady && <WhenReady onReady={onMapReady} />}
        <MapFlyTo center={center} zoom={MAP_INITIAL_ZOOM} />
        <FollowController devicePos={devicePos} followMode={followMode} />
        <RecenterControl
          devicePos={devicePos}
          followMode={followMode}
          onRecenter={handleRecenter}
          popupOpen={popupOpen}
        />
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
          maxZoom={22}
          maxNativeZoom={19}
          crossOrigin="anonymous"
        />
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}"
          maxZoom={22}
          maxNativeZoom={16}
          opacity={0.25}
          className="hillshade-multiply"
        />
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
          maxZoom={22}
          maxNativeZoom={19}
          opacity={0.7}
        />

        {polyline.length > 1 && (
          <>
            <Polyline positions={polyline} color="#00ff88" weight={6} opacity={0.06} className="expert-path-glow" />
            <Polyline positions={polyline} color="#00ff88" weight={1.5} opacity={0.3} dashArray="1 6" lineCap="round" />
          </>
        )}

        {connectionLines && connectionLines.map((line, i) => (
          <Polyline key={`conn-${i}`} positions={line} color="#44bbff" weight={2} opacity={0.5} dashArray="8 6" />
        ))}

        <ZoomAwareMarkers
          anchorPoints={anchorPoints}
          selectedAnchor={selectedAnchor}
          onSelectAnchor={onSelectAnchor}
          selectedPt={selectedPt}
          proximityMap={proximityMap}
          currentAnchorId={currentAnchorId}
          visitedAnchorIds={visitedAnchorIds}
        />

        {devicePos && compassIcon && (
          <Marker
            position={[devicePos.lat, devicePos.lon]}
            icon={compassIcon}
          />
        )}
      </MapContainer>
    </div>
  );
};
