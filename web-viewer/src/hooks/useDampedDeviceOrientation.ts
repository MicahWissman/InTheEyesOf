import { useState, useEffect, useRef, useCallback } from 'react';
import * as THREE from 'three';

const SMOOTH_A = 0.15; // exponential moving average factor for raw sensor smoothing

// Clamp applied camera pitch to this range — prevents gimbal-lock flicker near vertical.
// beta near ±180° can cause 50°+ EMA jumps (no wrap-correction on beta); clamping the
// final quaternion keeps the scene stable without re-introducing a deadband gate.
const PITCH_CLAMP_RAD = THREE.MathUtils.degToRad(75);

// Yaw-freeze thresholds — alpha (compass/heading) degrades when the phone tilts steeply
// because the Earth's horizontal magnetic field component shrinks near vertical.
// |90° − beta| measures how far the phone is from upright (0 = vertical/stable, 90 = face-up).
// Hysteresis gap (FREEZE > RESUME) prevents boundary chatter.
const PITCH_YAW_FREEZE_DEG = 55; // enter freeze above this tilt-from-upright
const PITCH_YAW_RESUME_DEG = 50; // exit freeze below this (5° hysteresis band)

function angleDelta(from: number, to: number): number {
  let d = to - from;
  while (d > 180) d -= 360;
  while (d < -180) d += 360;
  return d;
}

export interface DampedDeviceOrientationResult {
  dampedQRef: React.MutableRefObject<THREE.Quaternion | null>;
  smoothedRef: React.MutableRefObject<{ alpha: number; beta: number; gamma: number } | null>;
  compassAlpha: number | null;
  isAvailable: boolean;
  resetRest: () => void;
}

// Android Chrome only.
// TODO (iOS): Add DeviceOrientationEvent.requestPermission() gesture flow for Safari.
//             iOS requires a user gesture to grant motion/orientation access.
//
// Returns refs (not state) so high-frequency updates do not trigger re-renders.
// compassAlpha is state-throttled at ~5 fps for the compass UI overlay.
//
// yawFactor:   -1.0 → matches ImmersiveCamera Euler(pitch, -yaw, 0) convention
// pitchFactor: +0.25 → horizon-biased; attenuates floor/ceiling dives
export function useDampedDeviceOrientation(
  active: boolean,
  initialCameraQ: THREE.Quaternion,
  yawFactor: number,
  pitchFactor: number,
  horizonLock?: boolean,
  horizonPitchDeg?: number,
): DampedDeviceOrientationResult {
  const [isAvailable, setIsAvailable] = useState(false);
  const [compassAlpha, setCompassAlpha] = useState<number | null>(null);

  const dampedQRef = useRef<THREE.Quaternion | null>(null);
  const smoothedRef = useRef<{ alpha: number; beta: number; gamma: number } | null>(null);
  const restRef = useRef<{ alpha: number; beta: number; gamma: number } | null>(null);
  const isAvailableSet = useRef(false);
  const lastCompassUpdate = useRef(0);

  // Yaw-freeze state
  const yawFrozenRef = useRef(false);
  const frozenDeltaYawRef = useRef(0); // deltaYaw held while compass is unreliable

  const activeRef = useRef(active);
  const initQRef = useRef(initialCameraQ.clone());
  const yawRef = useRef(yawFactor);
  const pitchRef = useRef(pitchFactor);
  const horizonLockRef = useRef(horizonLock ?? false);
  const horizonPitchRef = useRef(horizonPitchDeg ?? 0);

  useEffect(() => { activeRef.current = active; }, [active]);
  useEffect(() => { initQRef.current = initialCameraQ.clone(); }, [initialCameraQ]);
  useEffect(() => { yawRef.current = yawFactor; }, [yawFactor]);
  useEffect(() => { pitchRef.current = pitchFactor; }, [pitchFactor]);
  useEffect(() => { horizonLockRef.current = horizonLock ?? false; }, [horizonLock]);
  useEffect(() => { horizonPitchRef.current = horizonPitchDeg ?? 0; }, [horizonPitchDeg]);

  const resetRest = useCallback(() => {
    restRef.current = null;
    smoothedRef.current = null;
    dampedQRef.current = null;
    yawFrozenRef.current = false;
    frozenDeltaYawRef.current = 0;
  }, []);

  useEffect(() => {
    const handler = (e: DeviceOrientationEvent) => {
      if (e.alpha === null || e.beta === null || e.gamma === null) return;

      if (!isAvailableSet.current) {
        isAvailableSet.current = true;
        setIsAvailable(true);
      }

      if (!activeRef.current) {
        smoothedRef.current = null;
        restRef.current = null;
        dampedQRef.current = null;
        yawFrozenRef.current = false;
        frozenDeltaYawRef.current = 0;
        return;
      }

      // Exponential moving average; alpha uses wrap-corrected delta, beta/gamma are linear.
      const s = smoothedRef.current;
      const next = s
        ? {
            alpha: s.alpha + SMOOTH_A * angleDelta(s.alpha, e.alpha),
            beta:  s.beta  + SMOOTH_A * (e.beta  - s.beta),
            gamma: s.gamma + SMOOTH_A * (e.gamma - s.gamma),
          }
        : { alpha: e.alpha, beta: e.beta, gamma: e.gamma };
      smoothedRef.current = next;

      // Capture rest orientation on first reading after AR mode starts
      if (!restRef.current) {
        restRef.current = { ...next };
      }

      const rest = restRef.current;
      const deltaYaw   = angleDelta(rest.alpha, next.alpha);
      const deltaPitch = next.beta - rest.beta;

      // ── Yaw-freeze hysteresis ────────────────────────────────────────────────
      // alpha (compass) goes noisy when the phone tilts steeply: the Earth's horizontal
      // magnetic field component weakens near vertical, degrading magnetometer heading.
      // |90 − beta| measures tilt-from-upright: 0 = phone vertical/upright, 90 = face-up.
      const pitchFromUprightDeg = Math.abs(90 - next.beta);
      const wasFrozen = yawFrozenRef.current;

      if (!wasFrozen && pitchFromUprightDeg > PITCH_YAW_FREEZE_DEG) {
        // Entering freeze: capture the last good yaw delta
        yawFrozenRef.current = true;
        frozenDeltaYawRef.current = deltaYaw;
      } else if (wasFrozen && pitchFromUprightDeg < PITCH_YAW_RESUME_DEG) {
        // Resuming: re-anchor rest.alpha so the next frame produces frozenDeltaYaw,
        // giving a continuous camera output with no snap.
        yawFrozenRef.current = false;
        const newRestAlpha = ((next.alpha - frozenDeltaYawRef.current) % 360 + 360) % 360;
        restRef.current = { ...rest, alpha: newRestAlpha };
      }

      // Use the frozen delta when frozen OR on the exact resume frame (old rest.alpha is stale
      // for one event — using frozenDelta here gives continuity; the re-anchor kicks in next frame).
      const appliedDeltaYaw = (yawFrozenRef.current || wasFrozen)
        ? frozenDeltaYawRef.current
        : deltaYaw;
      // ────────────────────────────────────────────────────────────────────────

      // Apply decoupled yaw/pitch factors on top of the initial camera quaternion.
      // YXZ Euler: yaw first (Y), then pitch (X), matching FPS camera convention.
      const initEuler = new THREE.Euler().setFromQuaternion(initQRef.current, 'YXZ');
      const yawComponent = initEuler.y - THREE.MathUtils.degToRad(appliedDeltaYaw * yawRef.current);

      let finalEuler: THREE.Euler;
      if (horizonLockRef.current) {
        // Horizon-lock: yaw-only, pitch fixed at horizonPitchDeg. Eliminates pitch/gimbal flicker.
        // Flip AR_HORIZON_LOCK to false to restore the pitch-tracking path below.
        finalEuler = new THREE.Euler(
          THREE.MathUtils.degToRad(horizonPitchRef.current),
          yawComponent,
          0,
          'YXZ',
        );
      } else {
        // Standard path: yaw + pitch, pitch clamped to ±PITCH_CLAMP_RAD to prevent gimbal-lock flicker.
        const rawPitch = initEuler.x + THREE.MathUtils.degToRad(deltaPitch * pitchRef.current);
        finalEuler = new THREE.Euler(
          Math.max(-PITCH_CLAMP_RAD, Math.min(PITCH_CLAMP_RAD, rawPitch)),
          yawComponent,
          0,
          'YXZ',
        );
      }
      dampedQRef.current = new THREE.Quaternion().setFromEuler(finalEuler);

      // Throttle compass re-render to ~5 fps
      const now = performance.now();
      if (now - lastCompassUpdate.current > 200) {
        lastCompassUpdate.current = now;
        setCompassAlpha(next.alpha);
      }
    };

    window.addEventListener('deviceorientation', handler);
    return () => window.removeEventListener('deviceorientation', handler);
  }, []);

  return { dampedQRef, smoothedRef, compassAlpha, isAvailable, resetRest };
}
