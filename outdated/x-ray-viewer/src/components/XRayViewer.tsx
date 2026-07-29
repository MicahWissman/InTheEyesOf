import { useState, useEffect, useRef, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { useThree } from '@react-three/fiber';
import { OrbitControls, PerspectiveCamera, Center, Grid } from '@react-three/drei';
import * as THREE from 'three';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';
import { XRayPointCloud } from './XRayPointCloud';
import { Hotspots } from './Hotspots';
import { BottomSheet } from './BottomSheet';
import { AlignmentControls } from './AlignmentControls';
import type { Anchor, XRayConfig, Transform } from '../lib/types';

interface XRayViewerProps {
  title: string;
  anchorsUrl: string;
  pointCloudUrl: string;
}

function DoubleClickFocus({
  controlsRef,
}: {
  controlsRef: React.RefObject<OrbitControlsImpl | null>;
}) {
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

export function XRayViewer({ title, anchorsUrl, pointCloudUrl }: XRayViewerProps) {
  const [anchors, setAnchors] = useState<Anchor[]>([]);
  const [selectedAnchor, setSelectedAnchor] = useState<Anchor | null>(null);
  const controlsRef = useRef<OrbitControlsImpl | null>(null);

  const [transform, setTransform] = useState<Transform>({
    position: [0, 0, 0],
    rotationY: 0,
    scale: 1,
  });

  const [xrayConfig, setXrayConfig] = useState<XRayConfig>({
    radius: 50,
    fadeRange: 10,
    intensity: 1,
    pointSize: 2.5,
  });

  useEffect(() => {
    fetch(anchorsUrl)
      .then((r) => r.json())
      .then(setAnchors)
      .catch((err) => console.error('Failed to load anchors:', err));
  }, [anchorsUrl]);

  return (
    <div className="relative w-full h-full" style={{ touchAction: 'none' }}>
      {/* 3D Canvas */}
      <Canvas>
        <PerspectiveCamera makeDefault position={[5, 18, 5]} fov={50} near={0.01} far={5000} />
        <OrbitControls
          ref={controlsRef}
          makeDefault
          enableDamping
          dampingFactor={0.1}
          target={[0.5, 17.5, 0]}
          minDistance={0.05}
          maxDistance={2000}
          zoomSpeed={2}
          panSpeed={1.5}
          screenSpacePanning
        />
        <DoubleClickFocus controlsRef={controlsRef} />

        <color attach="background" args={['#0a0a0a']} />
        <ambientLight intensity={1.5} />

        <Suspense fallback={null}>
          <Center top>
            <XRayPointCloud
              url={pointCloudUrl}
              transform={transform}
              config={xrayConfig}
            />
            <Hotspots
              anchors={anchors}
              onSelect={setSelectedAnchor}
              selectedId={selectedAnchor?.id}
            />
          </Center>
          <Grid
            infiniteGrid
            fadeDistance={50}
            fadeStrength={5}
            sectionColor="#222"
            cellColor="#333"
          />
        </Suspense>
      </Canvas>

      {/* Top bar */}
      <div className="absolute top-0 left-0 right-0 h-12 pointer-events-none flex items-center px-4 gap-2"
        style={{ background: 'linear-gradient(to bottom, rgba(0,0,0,0.65), transparent)' }}
      >
        <div className="w-6 h-6 bg-orange-500 rounded-md flex items-center justify-center text-black font-black text-xs flex-shrink-0">
          A
        </div>
        <span className="text-white/70 font-mono text-xs truncate">{title}</span>
        <div className="ml-auto flex items-center gap-1.5 px-2 py-0.5 bg-black/30 rounded-full border border-white/10 flex-shrink-0">
          <div className="w-1.5 h-1.5 rounded-full bg-orange-500" />
          <span className="text-white/50 font-mono text-[9px] uppercase tracking-wider">
            X-Ray
          </span>
        </div>
      </div>

      {/* Alignment controls (top-right FAB) */}
      <AlignmentControls
        transform={transform}
        config={xrayConfig}
        onTransformChange={setTransform}
        onConfigChange={setXrayConfig}
      />

      {/* Bottom sheet */}
      <BottomSheet
        anchors={anchors}
        selectedAnchor={selectedAnchor}
        onSelect={setSelectedAnchor}
        onClear={() => setSelectedAnchor(null)}
      />
    </div>
  );
}
