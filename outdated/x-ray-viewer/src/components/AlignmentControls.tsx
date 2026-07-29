import { useState } from 'react';
import { Settings2, X } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import type { XRayConfig, Transform } from '../lib/types';

interface AlignmentControlsProps {
  transform: Transform;
  config: XRayConfig;
  onTransformChange: (t: Transform) => void;
  onConfigChange: (c: XRayConfig) => void;
}

export function AlignmentControls({
  transform,
  config,
  onTransformChange,
  onConfigChange,
}: AlignmentControlsProps) {
  const [open, setOpen] = useState(false);

  const nudge = (axis: 0 | 1 | 2, delta: number) => {
    const pos = [...transform.position] as [number, number, number];
    pos[axis] += delta;
    onTransformChange({ ...transform, position: pos });
  };

  const xraySliders = [
    { label: 'Radius', key: 'radius' as const, min: 1, max: 200, step: 1, unit: 'm' },
    { label: 'Intensity', key: 'intensity' as const, min: 0.1, max: 2, step: 0.1, unit: '' },
    { label: 'Point Size', key: 'pointSize' as const, min: 0.5, max: 10, step: 0.5, unit: 'px' },
  ] as const;

  return (
    <div className="absolute top-14 right-3 z-40 flex flex-col items-end gap-2">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-11 h-11 rounded-full bg-[#151619]/90 border border-white/10 flex items-center justify-center shadow-lg backdrop-blur-md"
      >
        {open
          ? <X className="w-4 h-4 text-orange-500" />
          : <Settings2 className="w-4 h-4 text-white/60" />}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.95 }}
            transition={{ type: 'spring', damping: 25, stiffness: 380 }}
            className="bg-[#151619]/95 backdrop-blur-xl border border-white/10 rounded-2xl p-4 w-60 shadow-2xl"
          >
            {/* Position nudge */}
            <p className="text-white/40 font-mono text-[10px] uppercase tracking-wider mb-2">
              Position Nudge (0.1m)
            </p>
            <div className="grid grid-cols-3 gap-1.5 mb-4">
              {(['X', 'Y', 'Z'] as const).map((axis, i) => (
                <div key={axis} className="flex flex-col items-center gap-1">
                  <button
                    onClick={() => nudge(i as 0 | 1 | 2, 0.1)}
                    className="w-full bg-white/5 active:bg-white/15 text-white text-[11px] font-mono py-2 rounded-lg"
                  >
                    +{axis}
                  </button>
                  <span className="text-white/30 text-[9px] font-mono">
                    {transform.position[i].toFixed(1)}
                  </span>
                  <button
                    onClick={() => nudge(i as 0 | 1 | 2, -0.1)}
                    className="w-full bg-white/5 active:bg-white/15 text-white text-[11px] font-mono py-2 rounded-lg"
                  >
                    −{axis}
                  </button>
                </div>
              ))}
            </div>

            {/* Rotation Y */}
            <p className="text-white/40 font-mono text-[10px] uppercase tracking-wider mb-1">
              Rotation Y
            </p>
            <input
              type="range"
              min={-Math.PI}
              max={Math.PI}
              step={0.01}
              value={transform.rotationY}
              onChange={(e) =>
                onTransformChange({ ...transform, rotationY: parseFloat(e.target.value) })
              }
              className="w-full accent-orange-500 mb-1"
            />
            <span className="text-white/30 font-mono text-[9px] block mb-4">
              {(transform.rotationY * 180 / Math.PI).toFixed(0)}°
            </span>

            {/* Scale */}
            <p className="text-white/40 font-mono text-[10px] uppercase tracking-wider mb-1">
              Scale
            </p>
            <input
              type="range"
              min={0.1}
              max={5}
              step={0.05}
              value={transform.scale}
              onChange={(e) =>
                onTransformChange({ ...transform, scale: parseFloat(e.target.value) })
              }
              className="w-full accent-orange-500 mb-1"
            />
            <span className="text-white/30 font-mono text-[9px] block mb-4">
              {transform.scale.toFixed(2)}×
            </span>

            {/* X-Ray */}
            <p className="text-white/40 font-mono text-[10px] uppercase tracking-wider mb-2">
              X-Ray
            </p>
            <div className="space-y-3">
              {xraySliders.map(({ label, key, min, max, step, unit }) => (
                <div key={key}>
                  <div className="flex justify-between text-[9px] font-mono text-white/30 mb-1">
                    <span>{label}</span>
                    <span>
                      {config[key]}
                      {unit}
                    </span>
                  </div>
                  <input
                    type="range"
                    min={min}
                    max={max}
                    step={step}
                    value={config[key]}
                    onChange={(e) =>
                      onConfigChange({ ...config, [key]: parseFloat(e.target.value) })
                    }
                    className="w-full accent-orange-500"
                  />
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
