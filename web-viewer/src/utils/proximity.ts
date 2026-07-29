export type ProximityCategory = 'distant' | 'approaching' | 'discoverable' | 'in_range';

export function classifyDistance(meters: number): ProximityCategory {
  if (meters < 3) return 'in_range';
  if (meters < 10) return 'discoverable';
  if (meters < 25) return 'approaching';
  return 'distant';
}
