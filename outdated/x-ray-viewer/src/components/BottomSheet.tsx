import { useState, useRef, useEffect } from 'react';
import { Sparkles, Loader2 } from 'lucide-react';
import { analyzeAnchor } from '../lib/gemini';
import type { Anchor } from '../lib/types';

type SheetState = 'peek' | 'list' | 'detail';

const PEEK_PX = 72;

function getStatePx(state: SheetState): number {
  const vh = window.innerHeight;
  if (state === 'peek') return PEEK_PX;
  if (state === 'list') return Math.round(vh * 0.48);
  return Math.round(vh * 0.84);
}

function snapToState(px: number): SheetState {
  const states: SheetState[] = ['peek', 'list', 'detail'];
  const diffs = states.map((s) => Math.abs(getStatePx(s) - px));
  return states[diffs.indexOf(Math.min(...diffs))];
}

// ── Gemini analysis sub-component ─────────────────────────────────────────────

function GeminiAnalysis({ anchor }: { anchor: Anchor }) {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const run = () => {
    let cancelled = false;
    setText('');
    setError('');
    setLoading(true);

    analyzeAnchor(anchor, (chunk) => {
      if (!cancelled) setText((prev) => prev + chunk);
    })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Analysis failed');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  };

  useEffect(() => {
    const cancel = run();
    return cancel;
  }, []);

  if (error) {
    return (
      <div className="mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-xl">
        <p className="text-red-400 text-sm">{error}</p>
        <button
          onClick={run}
          className="mt-2 text-orange-400 font-mono text-xs"
        >
          ↺ Retry
        </button>
      </div>
    );
  }

  return (
    <div className="mt-4 p-4 bg-orange-500/5 border border-orange-500/10 rounded-xl">
      <div className="flex items-center gap-2 mb-2">
        <Sparkles className="w-3.5 h-3.5 text-orange-400 flex-shrink-0" />
        <span className="text-orange-400 font-mono text-[10px] uppercase tracking-wider">
          Gemini Analysis
        </span>
        {loading && (
          <Loader2 className="w-3 h-3 text-orange-400 animate-spin ml-auto" />
        )}
      </div>

      {text ? (
        <p className="text-white/80 text-sm leading-relaxed">{text}</p>
      ) : loading ? (
        <div className="flex gap-1 mt-2">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-orange-500/40 animate-pulse"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </div>
      ) : null}

      {!loading && text && (
        <button
          onClick={run}
          className="mt-3 text-orange-500/40 hover:text-orange-500/70 font-mono text-[10px] transition-colors"
        >
          ↺ Re-analyze
        </button>
      )}
    </div>
  );
}

// ── List view ──────────────────────────────────────────────────────────────────

function ListView({
  anchors,
  onSelect,
}: {
  anchors: Anchor[];
  onSelect: (a: Anchor) => void;
}) {
  return (
    <div className="space-y-2 pb-4">
      {anchors.map((anchor) => (
        <button
          key={anchor.id}
          onClick={() => onSelect(anchor)}
          className="w-full text-left bg-white/5 active:bg-white/15 border border-white/10 rounded-xl px-4 py-3 transition-colors"
        >
          <span className="block text-[#00ff88] font-mono text-xs mb-0.5">
            {anchor.relative_time}
          </span>
          <span className="block text-white text-sm font-medium">
            {anchor.narrative_title}
          </span>
        </button>
      ))}
    </div>
  );
}

// ── Detail view ────────────────────────────────────────────────────────────────

function DetailView({ anchor }: { anchor: Anchor }) {
  return (
    <div className="pb-10">
      <div className="mb-4">
        <span className="text-[#00ff88] font-mono text-xs">{anchor.relative_time}</span>
        <h2 className="text-white text-lg font-bold mt-0.5 leading-tight">
          {anchor.narrative_title}
        </h2>
      </div>

      <div className="mb-4">
        <h3 className="text-white/40 font-mono text-[10px] uppercase tracking-wider mb-1.5">
          Description
        </h3>
        <p className="text-white/80 text-sm leading-relaxed">
          {anchor.narrative_description}
        </p>
      </div>

      <div className="mb-4">
        <h3 className="text-white/40 font-mono text-[10px] uppercase tracking-wider mb-1.5">
          Transcript
        </h3>
        <blockquote className="bg-white/5 border-l-2 border-[#00ff88] rounded-r-xl pl-3 pr-4 py-3 text-white/70 text-sm italic leading-relaxed">
          "{anchor.transcript_slice}"
        </blockquote>
      </div>

      <GeminiAnalysis key={anchor.id} anchor={anchor} />
    </div>
  );
}

// ── Bottom Sheet ───────────────────────────────────────────────────────────────

interface BottomSheetProps {
  anchors: Anchor[];
  selectedAnchor: Anchor | null;
  onSelect: (anchor: Anchor) => void;
  onClear: () => void;
}

export function BottomSheet({
  anchors,
  selectedAnchor,
  onSelect,
  onClear,
}: BottomSheetProps) {
  const [state, setState] = useState<SheetState>('list');
  const [height, setHeight] = useState(() => getStatePx('list'));
  const [dragging, setDragging] = useState(false);

  const touchStartY = useRef(0);
  const touchStartH = useRef(0);

  // Auto-expand / collapse on selection change
  useEffect(() => {
    const next: SheetState = selectedAnchor ? 'detail' : 'list';
    setState(next);
    setHeight(getStatePx(next));
  }, [selectedAnchor]);

  const onTouchStart = (e: React.TouchEvent) => {
    touchStartY.current = e.touches[0].clientY;
    touchStartH.current = height;
    setDragging(true);
  };

  const onTouchMove = (e: React.TouchEvent) => {
    const delta = touchStartY.current - e.touches[0].clientY;
    const newH = Math.max(PEEK_PX, Math.min(getStatePx('detail'), touchStartH.current + delta));
    setHeight(newH);
  };

  const onTouchEnd = () => {
    setDragging(false);
    const snapped = snapToState(height);
    setState(snapped);
    setHeight(getStatePx(snapped));
    if (snapped === 'peek' || snapped === 'list') onClear();
  };

  const handleHandleTap = () => {
    if (state === 'peek') {
      setState('list');
      setHeight(getStatePx('list'));
    } else if (state === 'list') {
      setState('peek');
      setHeight(getStatePx('peek'));
      onClear();
    }
    // 'detail' — tapping handle collapses to list
    else if (state === 'detail') {
      setState('list');
      setHeight(getStatePx('list'));
      onClear();
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: `${height}px`,
        transition: dragging ? 'none' : 'height 0.38s cubic-bezier(0.32, 0.72, 0, 1)',
        zIndex: 30,
      }}
      className="bg-[#111]/95 backdrop-blur-xl border-t border-white/10 rounded-t-2xl flex flex-col overflow-hidden"
    >
      {/* Drag handle + header */}
      <div
        className="flex-shrink-0 flex flex-col items-center pt-2 pb-2 cursor-grab active:cursor-grabbing"
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onClick={handleHandleTap}
      >
        <div className="w-10 h-1 rounded-full bg-white/20 mb-2" />
        <div className="flex items-center justify-between w-full px-4">
          <span className="text-white/50 text-xs font-mono truncate pr-4">
            {selectedAnchor
              ? selectedAnchor.narrative_title
              : `${anchors.length} narrative events`}
          </span>
          {selectedAnchor && (
            <button
              onClick={(e) => { e.stopPropagation(); onClear(); }}
              className="text-white/30 hover:text-white/60 text-xs font-mono flex-shrink-0 transition-colors"
            >
              ← back
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-4">
        {selectedAnchor ? (
          <DetailView anchor={selectedAnchor} />
        ) : (
          <ListView anchors={anchors} onSelect={onSelect} />
        )}
      </div>
    </div>
  );
}
