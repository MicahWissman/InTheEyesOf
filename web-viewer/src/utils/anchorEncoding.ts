import type { Anchor } from '../types';

export function markerColor(source?: string): string {
  if (source === 'gaze') return '#f59e0b';
  if (source === 'manual') return '#d946ef';
  return '#22d3ee'; // narration / default
}

export function isRich(a: Anchor): boolean {
  return (a.streams?.length ?? 1) >= 2;
}
