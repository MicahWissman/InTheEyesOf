import { useState, useEffect, useRef, useCallback } from 'react';

export interface DeviceOrientationState {
  alpha: number | null;
  beta: number | null;
  gamma: number | null;
  isAvailable: boolean;
  requestPermission: (() => Promise<boolean>) | null;
}

const SMOOTH = 0.25;

function lerpAngle(prev: number, next: number, factor: number): number {
  let delta = next - prev;
  while (delta > 180) delta -= 360;
  while (delta < -180) delta += 360;
  return prev + factor * delta;
}

export function useDeviceOrientation(): DeviceOrientationState {
  const needsPermission =
    typeof DeviceOrientationEvent !== 'undefined' &&
    typeof (DeviceOrientationEvent as unknown as { requestPermission?: unknown }).requestPermission === 'function';

  const [isAvailable, setIsAvailable] = useState(!needsPermission);
  const [permissionGranted, setPermissionGranted] = useState(!needsPermission);
  const [values, setValues] = useState<{ alpha: number | null; beta: number | null; gamma: number | null }>({
    alpha: null, beta: null, gamma: null,
  });

  const smoothed = useRef<{ alpha: number; beta: number; gamma: number } | null>(null);

  useEffect(() => {
    if (!permissionGranted) return;
    if (typeof DeviceOrientationEvent === 'undefined') return;

    const handler = (e: DeviceOrientationEvent) => {
      if (e.alpha === null || e.beta === null || e.gamma === null) return;

      const rawAlpha = e.alpha;
      const rawBeta = Math.max(10, Math.min(170, e.beta));
      const rawGamma = e.gamma;

      if (!smoothed.current) {
        smoothed.current = { alpha: rawAlpha, beta: rawBeta, gamma: rawGamma };
        setValues({ alpha: rawAlpha, beta: rawBeta, gamma: rawGamma });
        return;
      }

      // Suppress erratic compass jump > 90 degrees
      let alphaDelta = rawAlpha - smoothed.current.alpha;
      while (alphaDelta > 180) alphaDelta -= 360;
      while (alphaDelta < -180) alphaDelta += 360;
      const alpha = Math.abs(alphaDelta) > 90
        ? smoothed.current.alpha
        : lerpAngle(smoothed.current.alpha, rawAlpha, SMOOTH);

      const beta = smoothed.current.beta + SMOOTH * (rawBeta - smoothed.current.beta);
      const gamma = smoothed.current.gamma + SMOOTH * (rawGamma - smoothed.current.gamma);

      smoothed.current = { alpha, beta, gamma };
      setValues({ alpha, beta, gamma });
    };

    let firstEvent = false;
    const detectAvailability = (e: DeviceOrientationEvent) => {
      if (!firstEvent && (e.alpha !== null || e.beta !== null || e.gamma !== null)) {
        firstEvent = true;
        setIsAvailable(true);
      }
    };

    window.addEventListener('deviceorientation', handler);
    window.addEventListener('deviceorientation', detectAvailability, { once: true });
    return () => {
      window.removeEventListener('deviceorientation', handler);
    };
  }, [permissionGranted]);

  const requestPermission = useCallback(async (): Promise<boolean> => {
    try {
      const result = await (
        DeviceOrientationEvent as unknown as { requestPermission: () => Promise<string> }
      ).requestPermission();
      const granted = result === 'granted';
      setPermissionGranted(granted);
      setIsAvailable(granted);
      return granted;
    } catch {
      return false;
    }
  }, []);

  return {
    alpha: values.alpha,
    beta: values.beta,
    gamma: values.gamma,
    isAvailable,
    requestPermission: needsPermission ? requestPermission : null,
  };
}
