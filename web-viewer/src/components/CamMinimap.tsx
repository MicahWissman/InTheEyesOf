import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Polyline, Polygon, useMap } from 'react-leaflet';
import type { Anchor, TrajectoryData, TrajectoryPoint } from '../types';

const MINIMAP_ZOOM = 19;
const FOV_DEG = 36;
const FOV_REACH_M = 0.00012;
const DEFAULT_SIZE = 220;
const MIN_SIZE = 100;
const MAX_SIZE = 300;

function findClosestPoint(path: TrajectoryPoint[], t: number): TrajectoryPoint | null {
  if (!path.length) return null;
  let lo = 0;
  let hi = path.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (path[mid].t < t) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(path[lo - 1].t - t) < Math.abs(path[lo].t - t)) return path[lo - 1];
  return path[lo];
}

function FollowCenter({ lat, lon }: { lat: number; lon: number }) {
  const map = useMap();
  const didInit = useRef(false);
  useEffect(() => {
    if (!didInit.current) {
      map.setView([lat, lon], MINIMAP_ZOOM, { animate: false });
      didInit.current = true;
    } else {
      map.setView([lat, lon], map.getZoom(), { animate: false });
    }
  }, [map, lat, lon]);
  return null;
}

function InvalidateOnResize({ size }: { size: number }) {
  const map = useMap();
  useEffect(() => { map.invalidateSize(); }, [map, size]);
  return null;
}

interface CamMinimapProps {
  devicePos: { lat: number; lon: number };
  compassAlpha: number | null;
  anchors: Anchor[];
  trajectoryData?: TrajectoryData | null;
  playingAnchorId?: number | null;
  heardIds?: Set<number>;
}

export function CamMinimap({
  devicePos,
  compassAlpha,
  anchors,
  trajectoryData,
  playingAnchorId,
  heardIds,
}: CamMinimapProps) {
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [size, setSize] = useState(DEFAULT_SIZE);

  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);
  const pinchRef = useRef<{ startDist: number; origSize: number } | null>(null);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2) {
      const dx = e.touches[1].clientX - e.touches[0].clientX;
      const dy = e.touches[1].clientY - e.touches[0].clientY;
      pinchRef.current = { startDist: Math.hypot(dx, dy), origSize: size };
      dragRef.current = null;
    } else if (e.touches.length === 1) {
      dragRef.current = {
        startX: e.touches[0].clientX, startY: e.touches[0].clientY,
        origX: pos.x, origY: pos.y,
      };
    }
  }, [pos, size]);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 2 && pinchRef.current) {
      const dx = e.touches[1].clientX - e.touches[0].clientX;
      const dy = e.touches[1].clientY - e.touches[0].clientY;
      const dist = Math.hypot(dx, dy);
      const ratio = dist / pinchRef.current.startDist;
      setSize(Math.round(Math.min(MAX_SIZE, Math.max(MIN_SIZE, pinchRef.current.origSize * ratio))));
    } else if (e.touches.length === 1 && dragRef.current) {
      const dx = e.touches[0].clientX - dragRef.current.startX;
      const dy = e.touches[0].clientY - dragRef.current.startY;
      setPos({ x: dragRef.current.origX + dx, y: dragRef.current.origY + dy });
    }
  }, []);

  const onTouchEnd = useCallback(() => {
    dragRef.current = null;
    pinchRef.current = null;
  }, []);

  const anchorPoints = useMemo(() => {
    if (!trajectoryData?.path?.length) return [];
    return anchors
      .filter(a => a.start_ts != null)
      .map(a => ({ anchor: a, pt: findClosestPoint(trajectoryData.path, a.start_ts!) }))
      .filter((x): x is { anchor: Anchor; pt: TrajectoryPoint } => x.pt !== null);
  }, [anchors, trajectoryData]);

  const trajectoryLine = useMemo((): [number, number][] => {
    if (!trajectoryData?.path?.length) return [];
    const step = Math.max(1, Math.floor(trajectoryData.path.length / 400));
    const pts: [number, number][] = [];
    for (let i = 0; i < trajectoryData.path.length; i += step) {
      const p = trajectoryData.path[i];
      pts.push([p.lat, p.lon]);
    }
    return pts;
  }, [trajectoryData]);

  const heading = compassAlpha !== null ? (360 - compassAlpha + 180) % 360 : 0;

  const fovWedge = useMemo((): [number, number][] => {
    const rad = (heading * Math.PI) / 180;
    const halfFov = (FOV_DEG * Math.PI) / 360;
    const cosLat = Math.cos((devicePos.lat * Math.PI) / 180);
    const tip: [number, number] = [devicePos.lat, devicePos.lon];
    const left: [number, number] = [
      devicePos.lat + Math.cos(rad - halfFov) * FOV_REACH_M,
      devicePos.lon + (Math.sin(rad - halfFov) * FOV_REACH_M) / cosLat,
    ];
    const right: [number, number] = [
      devicePos.lat + Math.cos(rad + halfFov) * FOV_REACH_M,
      devicePos.lon + (Math.sin(rad + halfFov) * FOV_REACH_M) / cosLat,
    ];
    return [tip, left, right];
  }, [devicePos.lat, devicePos.lon, heading]);

  const rotation = -heading;

  return (
    <div
      className="cam-minimap"
      style={{
        width: size, height: size,
        transform: `translate(${pos.x}px, ${pos.y}px) rotate(${rotation}deg)`,
      }}
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
    >
      <MapContainer
        center={[devicePos.lat, devicePos.lon]}
        zoom={MINIMAP_ZOOM}
        zoomControl={false}
        dragging={false}
        scrollWheelZoom={false}
        doubleClickZoom={false}
        touchZoom={false}
        attributionControl={false}
        style={{ width: '100%', height: '100%' }}
      >
        <FollowCenter lat={devicePos.lat} lon={devicePos.lon} />
        <InvalidateOnResize size={size} />
        <TileLayer
          url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
          maxZoom={22}
          maxNativeZoom={16}
          opacity={0.15}
        />

        {trajectoryLine.length > 1 && (
          <Polyline
            positions={trajectoryLine}
            pathOptions={{ color: '#00ff88', weight: 8, opacity: 0.15, lineCap: 'round', lineJoin: 'round' }}
          />
        )}

        {anchorPoints.map(({ anchor, pt }) => {
          const isPlaying = playingAnchorId === anchor.id;
          const isHeard = heardIds?.has(anchor.id) ?? false;
          const color = isPlaying ? '#00ff88' : isHeard ? '#666666' : '#00cc6a';
          return (
            <CircleMarker
              key={anchor.id}
              center={[pt.lat, pt.lon]}
              radius={isPlaying ? 7 : 5}
              pathOptions={{
                color,
                fillColor: color,
                fillOpacity: isPlaying ? 1 : isHeard ? 0.4 : 0.8,
                weight: 1,
              }}
            />
          );
        })}

        <Polygon
          positions={fovWedge}
          pathOptions={{
            color: '#4488ff',
            fillColor: '#4488ff',
            fillOpacity: 0.18,
            weight: 1,
            opacity: 0.5,
          }}
        />
        <CircleMarker
          center={[devicePos.lat, devicePos.lon]}
          radius={4}
          pathOptions={{
            color: '#4488ff',
            fillColor: '#4488ff',
            fillOpacity: 1,
            weight: 2,
          }}
        />
      </MapContainer>

      <div
        className="cam-minimap__north"
        style={{ transform: `rotate(${heading}deg)` }}
      >
        N
      </div>
    </div>
  );
}
