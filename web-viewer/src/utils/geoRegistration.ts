/**
 * 2D affine geo-registration: GPS (lat/lon) → SLAM world (wx, wz).
 *
 * Fits a full 2D affine map  [wx; wz] = A·[E; N] + b  via two independent
 * least-squares regressions sharing a single 3×3 normal matrix.  This handles
 * both the pure-rotation case (legacy recordings) and any reflection or
 * shear present in baked ENU-aligned frames (where world wz = −north).
 *
 * NOTE FOR FUTURE DEV: GPS currently sourced from each viewer's device geolocation API.
 * When deploying on Pi/Jetson as a shared host, consider switching to server-side GPS:
 *   - Attach a USB GNSS module to the host (e.g. u-blox, ~$25)
 *   - Expose position via SSE endpoint (e.g. GET /gps-stream → text/event-stream)
 *   - Browser uses EventSource instead of navigator.geolocation
 *   - Benefits: removes HTTPS requirement for geolocation, one authoritative position
 *     for all connected viewers, works on devices without GPS (desktop, etc.)
 *   - Tradeoff: host position ≠ individual viewer position (fine for fixed-station use)
 */

import type { TrajectoryPoint } from '../types';

export interface GeoRegistration {
  toSlam: (lat: number, lon: number) => { x: number; y: number; z: number };
  centerLat: number;
  centerLon: number;
  medianWy: number;
  scale: number;
  theta: number;
}

const M = 111319.49; // meters per degree latitude

/**
 * Solves the 3×3 linear system mat·x = rhs via Gaussian elimination with
 * partial pivoting.  Returns null if the system is singular (< 1e-12 pivot).
 * Operates on a copy — mat is not mutated.
 */
function solve3(mat: number[][], rhs: number[]): number[] | null {
  const N = 3;
  // Build augmented matrix [mat | rhs]
  const a = mat.map((row, i) => [...row, rhs[i]]);

  for (let col = 0; col < N; col++) {
    // Partial pivot
    let maxRow = col;
    for (let row = col + 1; row < N; row++) {
      if (Math.abs(a[row][col]) > Math.abs(a[maxRow][col])) maxRow = row;
    }
    [a[col], a[maxRow]] = [a[maxRow], a[col]];

    if (Math.abs(a[col][col]) < 1e-12) return null;

    for (let row = col + 1; row < N; row++) {
      const factor = a[row][col] / a[col][col];
      for (let j = col; j <= N; j++) {
        a[row][j] -= factor * a[col][j];
      }
    }
  }

  // Back substitution
  const x = new Array<number>(N).fill(0);
  for (let i = N - 1; i >= 0; i--) {
    x[i] = a[i][N];
    for (let j = i + 1; j < N; j++) x[i] -= a[i][j] * x[j];
    x[i] /= a[i][i];
  }
  return x;
}

export function fitGeoRegistration(path: TrajectoryPoint[]): GeoRegistration | null {
  const valid = path.filter(p => p.wx !== undefined && p.wy !== undefined && p.wz !== undefined);
  if (valid.length < 4) return null;

  // GPS centroid (degrees)
  const lat0 = valid.reduce((s, p) => s + p.lat, 0) / valid.length;
  const lon0 = valid.reduce((s, p) => s + p.lon, 0) / valid.length;
  const cosLat = Math.cos(lat0 * Math.PI / 180);

  // GPS-local: E = east meters, N = north meters
  const pts = valid.map(p => ({
    E: (p.lon - lon0) * cosLat * M,
    N: (p.lat - lat0) * M,
    wx: p.wx!,
    wz: p.wz!,
  }));

  // Accumulate the 3×3 normal matrix  A^T A  (shared by both regressions)
  // and both right-hand sides  A^T b_x,  A^T b_z
  let sEE = 0, sEN = 0, sNN = 0, sE = 0, sN = 0;
  let sEwx = 0, sNwx = 0, swx = 0;
  let sEwz = 0, sNwz = 0, swz = 0;

  for (const { E, N, wx, wz } of pts) {
    sEE += E * E;  sEN += E * N;  sNN += N * N;
    sE  += E;      sN  += N;
    sEwx += E * wx;  sNwx += N * wx;  swx += wx;
    sEwz += E * wz;  sNwz += N * wz;  swz += wz;
  }
  const n = pts.length;

  // Normal matrix: [[ΣEE, ΣEN, ΣE], [ΣEN, ΣNN, ΣN], [ΣE, ΣN, n]]
  const normalMat = [
    [sEE, sEN, sE],
    [sEN, sNN, sN],
    [sE,  sN,  n ],
  ];

  // Solve for wx row: [a11, a12, bx]  and  wz row: [a21, a22, bz]
  const solX = solve3(normalMat, [sEwx, sNwx, swx]);
  const solZ = solve3(normalMat, [sEwz, sNwz, swz]);
  if (!solX || !solZ) return null;

  const [a11, a12, bx] = solX;
  const [a21, a22, bz] = solZ;

  // Median wy for ground-plane height
  const wys = valid.map(p => p.wy!).sort((a, b) => a - b);
  const medianWy = wys[Math.floor(wys.length / 2)];

  // scale = sqrt(|det A|); theta = atan2(a21, a11) for interface compatibility
  const scale = Math.sqrt(Math.abs(a11 * a22 - a12 * a21));
  const theta  = Math.atan2(a21, a11);

  return {
    centerLat: lat0,
    centerLon: lon0,
    medianWy,
    scale,
    theta,
    toSlam(lat: number, lon: number) {
      const E = (lon - lon0) * cosLat * M;
      const N = (lat - lat0) * M;
      return {
        x: a11 * E + a12 * N + bx,
        y: medianWy,
        z: a21 * E + a22 * N + bz,
      };
    },
  };
}
