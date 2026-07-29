import { Sphere, MeshDistortMaterial } from '@react-three/drei';
import type { Anchor } from '../lib/types';

interface HotspotsProps {
  anchors: Anchor[];
  onSelect: (anchor: Anchor) => void;
  selectedId?: number;
}

export function Hotspots({ anchors, onSelect, selectedId }: HotspotsProps) {
  return (
    <>
      {anchors.map((anchor) => (
        <Sphere
          key={anchor.id}
          args={[0.14, 16, 16]}
          position={[anchor.gx, anchor.gy, anchor.gz]}
          onClick={(e) => {
            e.stopPropagation();
            onSelect(anchor);
          }}
        >
          <MeshDistortMaterial
            color={selectedId === anchor.id ? '#f97316' : '#00ff88'}
            speed={2}
            distort={selectedId === anchor.id ? 0.5 : 0.3}
            opacity={0.85}
            transparent
          />
        </Sphere>
      ))}
    </>
  );
}
