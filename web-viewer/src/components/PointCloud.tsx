import { useLoader, useFrame } from '@react-three/fiber';
import { PLYLoader } from 'three-stdlib';
import * as THREE from 'three';
import { useMemo, useRef, useEffect } from 'react';
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib';

interface PointCloudProps {
  url: string;
  focusRef?: React.RefObject<OrbitControlsImpl | null>;
  fadeEnabled?: boolean;
  fadeStart?: number;
  fadeEnd?: number;
  proximityFade?: boolean;
  proximityPos?: { x: number; y: number; z: number } | null;
  proximityRadius?: number;
  geoScale?: number;
  followFadeDist?: number;
  onBoundingRadius?: (r: number) => void;
  onLoad?: () => void;
}

// Camera-to-cloud distance thresholds for the fly-in/out opacity ease.
// When the camera enters the cloud's interior, opacity fades to OPACITY_INSIDE
// so the dense geometry doesn't block the view. Lerp factor ~0.04 → ~30 frames.
const OPACITY_OUTSIDE = 1.0;
const OPACITY_INSIDE  = 0.8;
const OPACITY_LERP_K  = 0.04;
const INSIDE_FRACTION = 0.55; // camera within this fraction of radius → "inside"

// Raster budget: clouds above this are stride-decimated after load.
// Keeps GPU fill load bounded — a faded point is still rasterized.
// riva1 / gilbert are well under 1M; only the ~3M Steger cloud gets thinned.
const MAX_POINTS = 600_000;

export const PointCloud = ({
  url,
  focusRef,
  fadeEnabled = false,
  fadeStart = 6,
  fadeEnd = 18,
  proximityFade = false,
  proximityPos = null,
  proximityRadius = 3,
  geoScale = 1,
  followFadeDist = 0,
  onBoundingRadius,
  onLoad,
}: PointCloudProps) => {
  const rawGeometry = useLoader(PLYLoader, url);

  // Stride-decimate oversized clouds so raster/fill load stays within budget.
  // PLYLoader returns Float32 for both position and color attributes.
  const geometry = useMemo(() => {
    const posAttr = rawGeometry.attributes.position as THREE.BufferAttribute | undefined;
    if (!posAttr || posAttr.count <= MAX_POINTS) {
      return rawGeometry;
    }

    const count = posAttr.count;
    const k = Math.ceil(count / MAX_POINTS);
    const keptCount = Math.floor(count / k);
    const dec = new THREE.BufferGeometry();

    for (const name of Object.keys(rawGeometry.attributes)) {
      const src = rawGeometry.attributes[name] as THREE.BufferAttribute;
      const is = src.itemSize;
      const sa = src.array;
      const da = new Float32Array(keptCount * is);
      for (let i = 0; i < keptCount; i++) {
        for (let j = 0; j < is; j++) da[i * is + j] = sa[i * k * is + j];
      }
      dec.setAttribute(name, new THREE.BufferAttribute(da, is, src.normalized));
    }
    return dec;
  }, [rawGeometry]);

  // Dispose the decimated BufferGeometry on unmount (or when rawGeometry changes).
  // rawGeometry is owned by the PLY loader cache — never dispose it here.
  useEffect(() => {
    return () => {
      if (geometry !== rawGeometry) geometry.dispose();
    };
  }, [geometry, rawGeometry]);

  const uniformsRef = useRef<Record<string, THREE.IUniform> | null>(null);
  const cloudCenterRef = useRef(new THREE.Vector3());
  const cloudRadiusRef = useRef(10);
  const currentOpacityRef = useRef(OPACITY_OUTSIDE);

  useEffect(() => {
    geometry.computeBoundingSphere();
    const sphere = geometry.boundingSphere;
    const r = sphere?.radius ?? 10;
    onBoundingRadius?.(r);
    cloudRadiusRef.current = r;
    if (sphere) cloudCenterRef.current.copy(sphere.center);
  // geometry reference changes when the PLY resolves; callbacks are stable
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry]);

  useEffect(() => {
    onLoad?.();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry]);

  const material = useMemo(() => {
    uniformsRef.current = null;

    const mat = new THREE.PointsMaterial({
      size: 0.025,
      vertexColors: true,
      transparent: true,
      opacity: 0.7,
      toneMapped: false,
      depthWrite: false,
    });

    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uFocus       = { value: new THREE.Vector3() };
      shader.uniforms.uFadeStart   = { value: 6.0 };
      shader.uniforms.uFadeEnd     = { value: 18.0 };
      shader.uniforms.uEnabled     = { value: 0.0 };
      shader.uniforms.uGlobalOpacity = { value: 1.0 };
      shader.uniforms.uCamPos      = { value: new THREE.Vector3() };
      shader.uniforms.uProxPos     = { value: new THREE.Vector3() };
      shader.uniforms.uProxRadius  = { value: 4.0 };
      shader.uniforms.uProxEnabled = { value: 0.0 };
      shader.uniforms.uGeoScale    = { value: 1.0 };
      shader.uniforms.uFollowFade  = { value: 0.0 };
      shader.uniforms.uMaxPointPx  = { value: 6.0 };

      uniformsRef.current = shader.uniforms;

      shader.vertexShader =
        'uniform vec3 uFocus;\nuniform vec3 uProxPos;\nuniform vec3 uCamPos;\n' +
        'uniform float uMaxPointPx;\n' +
        'varying float vDist;\nvarying float vProxDist;\nvarying float vCamDist;\n' +
        shader.vertexShader;
      shader.vertexShader = shader.vertexShader.replace(
        '#include <begin_vertex>',
        `#include <begin_vertex>
         { vec3 wPos = (modelMatrix * vec4(transformed, 1.0)).xyz;
           vDist = distance(wPos, uFocus);
           vProxDist = distance(wPos, uProxPos);
           vCamDist = distance(wPos, uCamPos); }`,
      );
      // Clamp screen-space point size so close-up points stay small dots
      shader.vertexShader = shader.vertexShader.replace(
        'gl_PointSize = size;',
        'gl_PointSize = min(size, uMaxPointPx);',
      );

      shader.fragmentShader =
        'varying float vDist;\nvarying float vProxDist;\nvarying float vCamDist;\n' +
        'uniform float uFadeStart;\nuniform float uFadeEnd;\nuniform float uEnabled;\n' +
        'uniform float uGlobalOpacity;\nuniform float uProxRadius;\nuniform float uProxEnabled;\n' +
        'uniform float uGeoScale;\nuniform float uFollowFade;\n' +
        shader.fragmentShader;
      shader.fragmentShader = shader.fragmentShader.replace(
        '#include <dithering_fragment>',
        `#include <dithering_fragment>
         // Soft circle: wide gaussian-ish falloff from center
         float cd = length(gl_PointCoord - vec2(0.5));
         if (cd > 0.5) discard;
         gl_FragColor.a *= 1.0 - smoothstep(0.15, 0.5, cd);
         // Boost saturation so low-opacity points still read as colourful
         {
           float lum = dot(gl_FragColor.rgb, vec3(0.299, 0.587, 0.114));
           gl_FragColor.rgb = mix(vec3(lum), gl_FragColor.rgb, 1.5);
         }
         // Discard points too close to camera (they rasterize huge)
         if (vCamDist < 0.5) discard;
         if (uEnabled > 0.5) {
           float t = clamp((vDist - uFadeStart) / max(0.001, uFadeEnd - uFadeStart), 0.0, 1.0);
           gl_FragColor.a *= max(0.03, exp(-4.5 * t));
         }
         if (uProxEnabled > 0.5) {
           float distM = vProxDist / max(0.001, uGeoScale);
           if (distM > 100.0) discard;
           float sphere =
             distM < 10.0 ? 1.0 :
             distM < 20.0 ? 0.8 :
             distM < 30.0 ? 0.6 :
             distM < 50.0 ? 0.4 : 0.1;
           gl_FragColor.a *= sphere;
         }
         if (uFollowFade > 0.0) {
           float nearFade = smoothstep(1.0, uFollowFade, vCamDist);
           gl_FragColor.a *= mix(0.15, 1.0, nearFade);
         }
         gl_FragColor.a *= uGlobalOpacity;`,
      );
    };

    return mat;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url]);

  // Push uniform values every frame
  useFrame(({ camera, invalidate }) => {
    const u = uniformsRef.current;
    if (!u) return;

    const controls = focusRef?.current;
    const focus = controls ? controls.target : camera.position;
    (u.uFocus.value as THREE.Vector3).copy(focus);
    u.uFadeStart.value = fadeStart;
    u.uFadeEnd.value   = fadeEnd;
    u.uEnabled.value   = fadeEnabled ? 1.0 : 0.0;

    (u.uCamPos.value as THREE.Vector3).copy(camera.position);
    u.uProxEnabled.value = proximityFade && proximityPos ? 1.0 : 0.0;
    if (proximityPos) {
      (u.uProxPos.value as THREE.Vector3).set(proximityPos.x, proximityPos.y, proximityPos.z);
    }
    u.uProxRadius.value = proximityRadius;
    u.uGeoScale.value = geoScale;
    u.uFollowFade.value = followFadeDist;

    // Lerp global opacity: ease down when camera enters cloud interior
    const dist = camera.position.distanceTo(cloudCenterRef.current);
    const threshold = cloudRadiusRef.current * INSIDE_FRACTION;
    const target = dist < threshold ? OPACITY_INSIDE : OPACITY_OUTSIDE;
    currentOpacityRef.current = THREE.MathUtils.lerp(
      currentOpacityRef.current,
      target,
      OPACITY_LERP_K,
    );
    u.uGlobalOpacity.value = currentOpacityRef.current;

    // While opacity is still lerping (e.g. fly-in/out), keep requesting frames
    // even after OrbitControls damping has settled.
    if (Math.abs(currentOpacityRef.current - target) > 0.001) invalidate();
  });

  return <points geometry={geometry} material={material} />;
};
