import { useEffect, useRef, useState } from 'react';
import type { Anchor } from '../types';
import { useAI } from '../contexts/AIContext';

const MAX_EXCHANGES = 5;
const SESSION_SECONDS = 60;

interface Message {
  role: 'user' | 'assistant';
  text: string;
}

interface ConversationPanelProps {
  anchor: Anchor;
  recordingId: string;
  onClose: () => void;
  lang?: string;
}

export function ConversationPanel({ anchor, recordingId, onClose, lang }: ConversationPanelProps) {
  const { aiEnabled } = useAI();

  const [history, setHistory] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [secondsLeft, setSecondsLeft] = useState(SESSION_SECONDS);
  const [exchangesLeft, setExchangesLeft] = useState(MAX_EXCHANGES);
  const [isLoading, setIsLoading] = useState(false);
  const [ended, setEnded] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 60-second countdown
  useEffect(() => {
    const t = setInterval(() => {
      setSecondsLeft(s => {
        if (s <= 1) { setEnded(true); return 0; }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, []);

  // Close if AI toggled off mid-conversation
  useEffect(() => {
    if (!aiEnabled && !ended) {
      setHistory(h => [...h, {
        role: 'assistant',
        text: 'The AI feature has been disabled. This conversation has ended.',
      }]);
      setEnded(true);
    }
  }, [aiEnabled, ended]);

  // Auto-scroll to latest message
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [history, isLoading]);

  const handleSend = async () => {
    const msg = input.trim();
    if (!msg || isLoading || ended || exchangesLeft === 0) return;

    setInput('');
    const userMsg: Message = { role: 'user', text: msg };
    setHistory(h => [...h, userMsg]);
    setIsLoading(true);

    try {
      const res = await fetch('/api/conversation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          anchorId: anchor.id,
          recordingId,
          message: msg,
          conversationHistory: history,
          secondsRemaining: secondsLeft,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
        throw new Error(err.error || `HTTP ${res.status}`);
      }

      const data = await res.json();
      setHistory(h => [...h, { role: 'assistant', text: data.response }]);
      setExchangesLeft(data.exchangesRemaining ?? exchangesLeft - 1);
      if ((data.exchangesRemaining ?? exchangesLeft - 1) <= 0) setEnded(true);
    } catch (err) {
      setHistory(h => [...h, {
        role: 'assistant',
        text: err instanceof Error && err.message.includes('not configured')
          ? 'The conversation service is not yet configured on this device.'
          : 'Could not reach the conversation service. Check your connection and try again.',
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const fmtSeconds = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  const timerClass = secondsLeft <= 10 ? ' conv-timer-urgent' : '';

  return (
    <div className="conversation-panel">
      {/* Header */}
      <div className="conv-header">
        <div className="conv-meta">
          <span className="conv-title">Ask the Expert</span>
          <span className="conv-anchor-name">{anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title}</span>
        </div>
        <div className="conv-controls">
          <span className={`conv-timer${timerClass}`}>{fmtSeconds(secondsLeft)}</span>
          <span className="conv-exchanges">{exchangesLeft}/{MAX_EXCHANGES} left</span>
          <button className="conv-close-btn" onClick={onClose} aria-label="Close conversation">✕</button>
        </div>
      </div>

      {/* System context message */}
      {history.length === 0 && (
        <p className="conv-intro">
          You're in conversation with the expert about <strong>{anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title}</strong>.
          You have {fmtSeconds(secondsLeft)} and up to {MAX_EXCHANGES} questions.
          Responses are grounded in the expert's recorded words only.
        </p>
      )}

      {/* Message history */}
      <div className="conv-history" ref={scrollRef}>
        {history.map((msg, i) => (
          <div key={i} className={`conv-message conv-message-${msg.role}`}>
            <span className="conv-message-label">{msg.role === 'user' ? 'You' : 'Expert'}</span>
            <p className="conv-message-text">{msg.text}</p>
          </div>
        ))}
        {isLoading && (
          <div className="conv-message conv-message-assistant">
            <span className="conv-message-label">Expert</span>
            <p className="conv-message-text conv-typing">···</p>
          </div>
        )}
      </div>

      {/* Input area */}
      {!ended ? (
        <div className="conv-input-row">
          <textarea
            className="conv-input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about this space…"
            rows={2}
            disabled={isLoading}
            aria-label="Your question"
          />
          <button
            className="conv-send-btn"
            onClick={handleSend}
            disabled={isLoading || !input.trim()}
            aria-label="Send"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
              <polygon points="1,1 13,7 1,13 3,7" />
            </svg>
          </button>
        </div>
      ) : (
        <p className="conv-ended">
          {secondsLeft === 0
            ? 'Session timed out. Tap a new anchor to start a fresh conversation.'
            : exchangesLeft === 0
            ? 'Maximum questions reached.'
            : 'Conversation ended.'}
        </p>
      )}
    </div>
  );
}
