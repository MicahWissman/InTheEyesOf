import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

const STORAGE_KEY = 'aiEnabled';
const HEALTH_TIMEOUT_MS = 4000;
const ASK_TIMEOUT_MS = 40_000;

// ── Session memory (client-only, ephemeral) ───────────────────────────────────
export interface SessionMemory {
  visitedAnchorIds: number[];
  questionsAsked: string[];
  inferredInterests: string[];
}

const EMPTY_MEMORY: SessionMemory = {
  visitedAnchorIds: [],
  questionsAsked: [],
  inferredInterests: [],
};

function memoryToString(m: SessionMemory): string {
  const parts: string[] = [];
  if (m.visitedAnchorIds.length)
    parts.push(`Visited ${m.visitedAnchorIds.length} location(s) this session.`);
  if (m.inferredInterests.length)
    parts.push(`Interests: ${m.inferredInterests.slice(-3).join(', ')}.`);
  if (m.questionsAsked.length)
    parts.push(`Recent: ${m.questionsAsked.slice(-2).join(' | ')}.`);
  return parts.join(' ');
}

function inferInterests(question: string): string[] {
  const q = question.toLowerCase();
  const out: string[] = [];
  if (/material|stone|brick|wood|metal|glass/.test(q)) out.push('materials');
  if (/histor|built|centur|era|age|old/.test(q)) out.push('history');
  if (/architect|design|style|structur/.test(q)) out.push('architecture');
  if (/person|who|name|people|artist|worker/.test(q)) out.push('people');
  if (/why|purpose|use|function|meant/.test(q)) out.push('purpose');
  if (/how|technique|process|made|construct/.test(q)) out.push('craft');
  return out;
}

// ── Context shape ─────────────────────────────────────────────────────────────
export type Grounding = 'grounded' | 'partial' | 'general';
export interface AskResult { answer: string; grounding: Grounding; }

export interface AIContextValue {
  aiEnabled: boolean;
  toggleAI: () => void;
  isAskOnline: boolean;
  sessionMemory: SessionMemory;
  recordVisit: (anchorId: number) => void;
  recordQuestion: (question: string) => void;
  clearMemory: () => void;
  ask: (anchorContext: string, question: string) => Promise<AskResult | null>;
}

const AICtx = createContext<AIContextValue | null>(null);

export function AIProvider({ children }: { children: ReactNode }) {
  const [aiEnabled, setAIEnabled] = useState<boolean>(() => {
    try { return localStorage.getItem(STORAGE_KEY) === 'true'; } catch { return false; }
  });
  const [isAskOnline, setIsAskOnline] = useState(false);
  const [sessionMemory, setSessionMemory] = useState<SessionMemory>(EMPTY_MEMORY);
  const probed = useRef(false);

  // Probe /ask/health once on mount — determines whether AI affordances are shown at all.
  // Offline = hide silently; no error shown to visitor.
  useEffect(() => {
    if (probed.current) return;
    probed.current = true;
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), HEALTH_TIMEOUT_MS);
    fetch('/ask/health', { signal: ctrl.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(new Error('not ok'))))
      .then((d: { ok?: boolean }) => { clearTimeout(t); setIsAskOnline(d.ok === true); })
      .catch(() => { clearTimeout(t); setIsAskOnline(false); });
  }, []);

  const toggleAI = useCallback(() => {
    setAIEnabled(v => {
      const next = !v;
      try { localStorage.setItem(STORAGE_KEY, String(next)); } catch {}
      return next;
    });
  }, []);

  const recordVisit = useCallback((anchorId: number) => {
    setSessionMemory(m =>
      m.visitedAnchorIds.includes(anchorId)
        ? m
        : { ...m, visitedAnchorIds: [...m.visitedAnchorIds, anchorId] },
    );
  }, []);

  const recordQuestion = useCallback((question: string) => {
    const interests = inferInterests(question);
    setSessionMemory(m => ({
      visitedAnchorIds: m.visitedAnchorIds,
      questionsAsked: [...m.questionsAsked.slice(-9), question],
      inferredInterests: [...new Set([...m.inferredInterests, ...interests])].slice(-8),
    }));
  }, []);

  const clearMemory = useCallback(() => setSessionMemory(EMPTY_MEMORY), []);

  // Read sessionMemory via ref so ask() doesn't need it as a dependency.
  // This prevents ask() from being recreated on every memory update, which was
  // causing the in-flight AbortController to be aborted mid-request via React's
  // context-propagation / useCallback recreation cascade.
  const sessionMemoryRef = useRef(sessionMemory);
  sessionMemoryRef.current = sessionMemory;

  // Track the active in-flight controller so a new ask() cancels the previous one.
  const askCtrlRef = useRef<AbortController | null>(null);

  // ask() — stable reference ([] deps); cancels any previous in-flight request.
  // Returns null ONLY for true network/abort failures — callers show "couldn't reach".
  // Returns a non-null AskResult for "got a response but no usable answer" cases.
  const ask = useCallback(async (
    anchorContext: string,
    question: string,
  ): Promise<AskResult | null> => {
    // Cancel any previous in-flight ask with a labelled reason
    askCtrlRef.current?.abort(new DOMException('superseded by new ask', 'AbortError'));

    const ctrl = new AbortController();
    askCtrlRef.current = ctrl;

    const t = setTimeout(
      () => ctrl.abort(new DOMException('ask timeout', 'TimeoutError')),
      ASK_TIMEOUT_MS,
    );

    let res: Response;
    try {
      res = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: ctrl.signal,
        body: JSON.stringify({
          anchorContext: anchorContext.trim(),
          question: question.trim(),
          sessionMemory: memoryToString(sessionMemoryRef.current) || undefined,
        }),
      });
      clearTimeout(t);
      if (askCtrlRef.current === ctrl) askCtrlRef.current = null;
    } catch (e) {
      clearTimeout(t);
      if (askCtrlRef.current === ctrl) askCtrlRef.current = null;
      return null;
    }

    if (!res.ok) return null;
    setIsAskOnline(true);

    let data: { answer?: string; grounding?: string };
    try {
      data = (await res.json()) as { answer?: string; grounding?: string };
    } catch (e) {
      return { answer: '(response received but could not be read)', grounding: 'general' };
    }

    if (typeof data.answer === 'string' && data.answer.trim()) {
      const grounding: Grounding =
        data.grounding === 'grounded' || data.grounding === 'partial' || data.grounding === 'general'
          ? data.grounding
          : 'general';
      return { answer: data.answer.trim(), grounding };
    }

    return { answer: '(no answer received — try rephrasing)', grounding: 'general' };
  }, []); // stable — sessionMemory read via ref, setIsAskOnline is a stable setter

  return (
    <AICtx.Provider value={{
      aiEnabled, toggleAI,
      isAskOnline,
      sessionMemory, recordVisit, recordQuestion, clearMemory,
      ask,
    }}>
      {children}
    </AICtx.Provider>
  );
}

export function useAI(): AIContextValue {
  const ctx = useContext(AICtx);
  if (!ctx) throw new Error('useAI must be inside <AIProvider>');
  return ctx;
}
