import { Line } from '@react-three/drei';
import * as THREE from 'three';
import type { SemanticGraphData, Link } from '../types';

interface SemanticConnectionsProps {
  graphData: SemanticGraphData | null;
  onSelectLink: (link: Link, index: number) => void;
  selectedLinkIndex?: number | null;
}

export const SemanticConnections = ({ graphData, onSelectLink, selectedLinkIndex }: SemanticConnectionsProps) => {
  if (!graphData) return null;

  return (
    <group>
      {graphData.links.map((link, index) => {
        const start = graphData.nodes[link.source].pos;
        const end = graphData.nodes[link.target].pos;
        
        const isSelected = selectedLinkIndex === index;
        const isDimmed = selectedLinkIndex !== null && selectedLinkIndex !== undefined && !isSelected;

        // Visual properties
        const opacity = isSelected ? 1.0 : (isDimmed ? 0.05 : Math.min(link.weight, 0.8));
        const color = isSelected ? '#ffff00' : new THREE.Color().setHSL(0.4, 1.0, 0.5);
        const width = isSelected ? link.weight * 6 : link.weight * 2;

        return (
          <Line
            key={`link-${index}`}
            points={[start, end]}
            color={color}
            lineWidth={width}
            transparent
            opacity={opacity}
            onClick={(e) => {
              e.stopPropagation();
              onSelectLink(link, index);
            }}
          />
        );
      })}
    </group>
  );
};
