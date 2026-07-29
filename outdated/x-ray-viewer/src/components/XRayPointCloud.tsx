import { useLoader, useFrame, useThree } from '@react-three/fiber';
import { PLYLoader } from 'three-stdlib';
import * as THREE from 'three';
import { useMemo, useRef } from 'react';
import { XRayShader } from '../lib/shaders';
import type { XRayConfig, Transform } from '../lib/types';

interface XRayPointCloudProps {
  url: string;
  transform: Transform;
  config: XRayConfig;
}

export function XRayPointCloud({ url, transform, config }: XRayPointCloudProps) {
  const geometry = useLoader(PLYLoader, url);
  const materialRef = useRef<THREE.ShaderMaterial>(null);
  const { camera } = useThree();

  const uniforms = useMemo(() => ({
    uTime: { value: 0 },
    uCenter: { value: new THREE.Vector3() },
    uRadius: { value: config.radius },
    uFadeRange: { value: config.fadeRange },
    uIntensity: { value: config.intensity },
    uPointSize: { value: config.pointSize },
  }), []);

  useFrame((state) => {
    if (!materialRef.current) return;
    const u = materialRef.current.uniforms;
    u.uTime.value = state.clock.getElapsedTime();
    u.uCenter.value.copy(camera.position);
    u.uRadius.value = config.radius;
    u.uFadeRange.value = config.fadeRange;
    u.uIntensity.value = config.intensity;
    u.uPointSize.value = config.pointSize;
  });

  return (
    <points
      geometry={geometry}
      position={transform.position}
      rotation={[0, transform.rotationY, 0]}
      scale={transform.scale}
    >
      <shaderMaterial
        ref={materialRef}
        vertexShader={XRayShader.vertexShader}
        fragmentShader={XRayShader.fragmentShader}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        vertexColors
      />
    </points>
  );
}
