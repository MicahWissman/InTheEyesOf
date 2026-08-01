import { useState, useEffect, useRef, useCallback } from 'react';
import type { NarrativeAnimation, AnimationEffect } from '../types';

export interface ActiveAnimation {
  animation: NarrativeAnimation;
  startedAt: number;
  opacity: number;
  phase: 'fadein' | 'active' | 'fadeout' | 'done';
}

interface UseNarrativeAnimationsOpts {
  animations: NarrativeAnimation[] | undefined;
  selectedAnchorId: number | null;
}

const FADE_OUT_DELAY = 0;

export function useNarrativeAnimations({
  animations,
  selectedAnchorId,
}: UseNarrativeAnimationsOpts) {
  const [active, setActive] = useState<ActiveAnimation | null>(null);
  const fadeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!animations) return;

    if (selectedAnchorId != null && selectedAnchorId !== prevIdRef.current) {
      prevIdRef.current = selectedAnchorId;
      if (fadeTimerRef.current) { clearTimeout(fadeTimerRef.current); fadeTimerRef.current = null; }

      const anim = animations.find(a => a.trigger === 'anchor_play' && a.anchorId === selectedAnchorId);
      if (anim) {
        setActive({ animation: anim, startedAt: Date.now(), opacity: 0, phase: 'fadein' });
      } else {
        setActive(prev => {
          if (!prev || prev.phase === 'done') return null;
          return { ...prev, phase: 'fadeout' };
        });
      }
      return;
    }

    if (selectedAnchorId == null && prevIdRef.current != null) {
      prevIdRef.current = null;
      if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
      fadeTimerRef.current = setTimeout(() => {
        setActive(prev => {
          if (!prev || prev.phase === 'done') return null;
          return { ...prev, phase: 'fadeout' };
        });
        fadeTimerRef.current = null;
      }, FADE_OUT_DELAY);
    }
  }, [selectedAnchorId, animations]);

  // Fade in/out ticker
  useEffect(() => {
    if (!active || active.phase === 'done') return;

    const fadeIn = active.animation.fadeIn ?? 1.0;
    const fadeOut = active.animation.fadeOut ?? 2.0;

    if (active.phase === 'fadein') {
      const id = requestAnimationFrame(() => {
        const elapsed = (Date.now() - active.startedAt) / 1000;
        const t = Math.min(1, elapsed / fadeIn);
        if (t >= 1) {
          setActive(prev => prev ? { ...prev, phase: 'active', opacity: 1 } : null);
        } else {
          setActive(prev => prev ? { ...prev, opacity: t } : null);
        }
      });
      return () => cancelAnimationFrame(id);
    }

    if (active.phase === 'fadeout') {
      const fadeStart = Date.now();
      const startOpacity = active.opacity;
      const tick = () => {
        const elapsed = (Date.now() - fadeStart) / 1000;
        const t = Math.max(0, startOpacity - elapsed / fadeOut);
        if (t <= 0) {
          setActive(prev => prev ? { ...prev, phase: 'done', opacity: 0 } : null);
        } else {
          setActive(prev => prev ? { ...prev, opacity: t } : null);
          rafRef.current = requestAnimationFrame(tick);
        }
      };
      const rafRef = { current: requestAnimationFrame(tick) };
      return () => cancelAnimationFrame(rafRef.current);
    }
  });

  useEffect(() => {
    return () => { if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current); };
  }, []);

  useEffect(() => {
    if (active?.phase === 'done') {
      const t = setTimeout(() => setActive(null), 100);
      return () => clearTimeout(t);
    }
  }, [active?.phase]);

  const dismiss = useCallback(() => {
    if (fadeTimerRef.current) clearTimeout(fadeTimerRef.current);
    setActive(null);
  }, []);

  const activeEffects: AnimationEffect[] = active && active.phase !== 'done' ? active.animation.effects : [];
  const opacity = active?.opacity ?? 0;

  return { active, activeEffects, opacity, dismiss };
}