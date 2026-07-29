import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import type { Anchor, Link, GazeOverlay, TouchOverlay } from '../types';
import { useAudio } from '../contexts/AudioContext';
import { useAI } from '../contexts/AIContext';
import type { Grounding } from '../contexts/AIContext';
import { speakAssistant, stopSpeaking } from '../utils/speech';
import { resolveAudioUrl, resolveNarrativeText } from '../utils/audioResolver';
import { ConversationPanel } from './ConversationPanel';

function formatTime(s: number): string {
  if (!isFinite(s) || s < 0) return '0:00';
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

interface SidebarProps {
  selectedAnchor: Anchor | null;
  selectedLink: { link: Link; source: Anchor; target: Anchor } | null;
  anchors: Anchor[];
  onSelect: (anchor: Anchor) => void;
  onClearSelection: () => void;
  onClearLink: () => void;
  isMobile?: boolean;
  recordingBaseUrl?: string;
  gazeOverlays?: GazeOverlay[];
  touchOverlays?: TouchOverlay[];
  onShowAttentionDetail?: (item: { type: 'gaze'; overlay: GazeOverlay } | { type: 'touch'; overlay: TouchOverlay }) => void;
  lang?: string;
  gender?: string;
  bubbleMap?: Map<number, { gaze?: string; touch?: string }>;
  showOriginalTranscript?: boolean;
  mobileOpen?: boolean;
  onMobileOpenChange?: (open: boolean) => void;
}

const HEAR_MORE_PROMPT =
  'Give a fresh two-sentence perspective on this location, focusing on a different aspect ' +
  'than what was just described. Speak directly to a visitor standing here.';

// Speech Recognition — not in standard TypeScript lib, cast through any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SpeechRec: (new () => any) | undefined =
  (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;

export const Sidebar = ({
  selectedAnchor,
  selectedLink,
  anchors,
  onSelect,
  onClearSelection,
  onClearLink,
  isMobile = false,
  recordingBaseUrl = '',
  gazeOverlays,
  touchOverlays,
  onShowAttentionDetail,
  lang,
  gender,
  bubbleMap,
  showOriginalTranscript = false,
  mobileOpen: mobileOpenProp,
  onMobileOpenChange,
}: SidebarProps) => {
  const [mobileOpenLocal, setMobileOpenLocal] = useState(false);
  const mobileOpen = mobileOpenProp ?? mobileOpenLocal;
  const setMobileOpen = onMobileOpenChange ?? setMobileOpenLocal;
  const [expertWordsOpen, setExpertWordsOpen] = useState(false);
  const [paneMode, setPaneMode] = useState<'description' | 'attention'>('attention');
  const [showConversation, setShowConversation] = useState(false);

  // AI ask state
  const [aiInput, setAiInput] = useState('');
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [aiGrounding, setAiGrounding] = useState<Grounding | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [isListening, setIsListening] = useState(false);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recognitionRef = useRef<any>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputFocusedRef = useRef(false);

  const {
    currentAnchorId, isPlaying, currentTime, duration,
    playAnchor, pauseAudio, resumeAudio, setNowPlayingTitle,
  } = useAudio();
  const { aiEnabled, isAskOnline, ask, recordVisit, recordQuestion } = useAI();

  // Derive recording ID from base URL (e.g. "/recordings/riva1" → "riva1")
  const recordingId = useMemo(
    () => recordingBaseUrl.split('/').filter(Boolean).pop() ?? '',
    [recordingBaseUrl],
  );

  // Reset UI when anchor changes — default to attention pane when events exist
  const hasAttention = (gazeOverlays && gazeOverlays.length > 0) || (touchOverlays && touchOverlays.length > 0);
  useEffect(() => {
    setShowConversation(false);
    setExpertWordsOpen(false);
    setPaneMode(hasAttention ? 'attention' : 'description');
    setAiInput('');
    setAiAnswer(null);
    setAiGrounding(null);
    setAiError(null);
    setAiLoading(false);
    setIsListening(false);
    recognitionRef.current?.abort();
    stopSpeaking();
  }, [selectedAnchor?.id]);

  // Open sidebar sheet on mobile when something is selected
  useEffect(() => {
    if (isMobile && (selectedAnchor !== null || selectedLink !== null)) {
      setMobileOpen(true);
    }
  }, [isMobile, selectedAnchor, selectedLink]);

  const hasSelection = selectedAnchor !== null || selectedLink !== null;
  const isOpen = isMobile ? mobileOpen : true;
  const mobileClass = isMobile ? ` sidebar-mobile${isOpen ? ' mobile-open' : ''}` : '';

  const handleClose = () => {
    onClearSelection();
    onClearLink();
    setMobileOpen(false);
    setShowConversation(false);
    stopSpeaking();
  };

  const swipeStartY = useRef<number | null>(null);
  const [swipeDeltaY, setSwipeDeltaY] = useState(0);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    swipeStartY.current = e.touches[0].clientY;
    setSwipeDeltaY(0);
  }, []);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (swipeStartY.current === null) return;
    const dy = e.touches[0].clientY - swipeStartY.current;
    if (dy > 0) setSwipeDeltaY(dy);
  }, []);

  const onTouchEnd = useCallback(() => {
    if (swipeDeltaY > 80 && !inputFocusedRef.current) {
      setMobileOpen(false);
    }
    swipeStartY.current = null;
    setSwipeDeltaY(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [swipeDeltaY]);

  if (isMobile && !hasSelection) return null;


  // Three-state toggle: play from 0 | pause | resume from position
  const anchorAudioUrl = selectedAnchor ? resolveAudioUrl(selectedAnchor, lang ?? 'en', gender ?? 'f') : null;

  const handlePlayPauseToggle = () => {
    if (!selectedAnchor || !anchorAudioUrl) return;
    const isThisAnchor = currentAnchorId === selectedAnchor.id;
    if (isThisAnchor && isPlaying) {
      pauseAudio();
    } else if (isThisAnchor && !isPlaying && currentTime > 0) {
      resumeAudio();
    } else {
      setNowPlayingTitle(selectedAnchor.narrative_titles?.[lang || 'en'] ?? selectedAnchor.narrative_title);
      recordVisit(selectedAnchor.id);
      stopSpeaking();
      playAnchor(selectedAnchor.id, `${recordingBaseUrl}/${anchorAudioUrl}`);
    }
  };

  const getAnchorContext = () =>
    selectedAnchor
      ? resolveNarrativeText(selectedAnchor, lang ?? 'en')
      : '';

  const handleAsk = async () => {
    if (!aiInput.trim() || aiLoading || !selectedAnchor) return;
    const question = aiInput.trim();
    setAiInput('');
    inputRef.current?.focus();
    recordQuestion(question);
    setAiLoading(true);
    setAiAnswer(null);
    setAiGrounding(null);
    setAiError(null);
    try {
      const result = await ask(getAnchorContext(), question);
      if (result) { setAiAnswer(result.answer); setAiGrounding(result.grounding); speakAssistant(result.answer); }
      else setAiError("Couldn't reach the assistant — try again");
    } finally {
      setAiLoading(false);
    }
  };

  const handleHearMore = async () => {
    if (aiLoading || !selectedAnchor) return;
    setAiLoading(true);
    setAiAnswer(null);
    setAiGrounding(null);
    setAiError(null);
    try {
      const result = await ask(getAnchorContext(), HEAR_MORE_PROMPT);
      if (result) { setAiAnswer(result.answer); setAiGrounding(result.grounding); speakAssistant(result.answer); }
      else setAiError("Couldn't reach the assistant — try again");
    } finally {
      setAiLoading(false);
    }
  };

  const handleSend = () => {
    if (aiLoading || !selectedAnchor) return;
    if (aiInput.trim()) { handleAsk(); } else { handleHearMore(); }
  };

  const handleMic = () => {
    if (!SpeechRec) return;
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }
    const rec = new SpeechRec();
    recognitionRef.current = rec;
    rec.lang = 'en-US';
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (e: any) => {
      const last = e.results[e.results.length - 1];
      setAiInput(last[0].transcript);
    };
    rec.onend = () => setIsListening(false);
    rec.onerror = () => setIsListening(false);
    rec.start();
    setIsListening(true);
  };

  // Progress for the slim bar
  const isThisAnchor = currentAnchorId === selectedAnchor?.id;
  const isThisPlaying = isThisAnchor && isPlaying;
  const displayTime = isThisAnchor ? currentTime : 0;
  const displayDuration = isThisAnchor
    ? (duration || selectedAnchor?.audioDuration || 0)
    : (selectedAnchor?.audioDuration || 0);
  const progressPct = displayDuration > 0 ? Math.min(100, (displayTime / displayDuration) * 100) : 0;

  return (
    <div className={`sidebar${mobileClass}`}>
      <div
        className="sidebar-content"
        onTouchStart={isMobile ? onTouchStart : undefined}
        onTouchMove={isMobile ? onTouchMove : undefined}
        onTouchEnd={isMobile ? onTouchEnd : undefined}
        style={swipeDeltaY > 0 ? { transform: `translateY(${swipeDeltaY}px)`, transition: 'none' } : undefined}
      >
        {selectedLink ? (
          <div className="detail-panel link-comparison">
            <button className="back-button" onClick={onClearLink}>← Back</button>
            <div className="detail-header">
              <span className="timestamp">Convergence Detected</span>
              <h3>Semantic Connection</h3>
            </div>
            <div className="rationale-box">
              <h4>AI Rationale</h4>
              <p className="rationale-text">"{selectedLink.link.rationale || 'Thematic similarity identified between these locations.'}"</p>
            </div>
            <div className="comparison-grid">
              <div className="comparison-node">
                <span className="node-label">Point A</span>
                <h5>{selectedLink.source.narrative_titles?.[lang || 'en'] ?? selectedLink.source.narrative_title}</h5>
                <p>{selectedLink.source.interpretation || selectedLink.source.narrative_description}</p>
              </div>
              <div className="comparison-divider"></div>
              <div className="comparison-node">
                <span className="node-label">Point B</span>
                <h5>{selectedLink.target.narrative_titles?.[lang || 'en'] ?? selectedLink.target.narrative_title}</h5>
                <p>{selectedLink.target.interpretation || selectedLink.target.narrative_description}</p>
              </div>
            </div>
          </div>

        ) : selectedAnchor ? (
          showConversation ? (
            /* ── AI Conversation mode (full corpus panel) ── */
            <div className="detail-panel">
              <button className="back-button" onClick={() => setShowConversation(false)}>
                ← Back to anchor
              </button>
              <ConversationPanel
                anchor={selectedAnchor}
                recordingId={recordingId}
                onClose={() => setShowConversation(false)}
                lang={lang}
              />
            </div>
          ) : (
            /* ── Standard anchor detail ── */
            <div className="detail-panel">

              {/* ── Drag indicator (mobile only) ── */}
              {isMobile && <div className="popup-drag-bar" />}

              {/* ── HEADER: play · title · ask · close ── */}
              <div className="popup-header">
                {anchorAudioUrl && (
                  <button
                    className={`popup-play-btn${isThisPlaying ? ' is-playing' : ''}`}
                    onClick={handlePlayPauseToggle}
                    aria-label={isThisPlaying ? 'Pause' : 'Play'}
                  >
                    {isThisPlaying ? (
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                        <rect x="2" y="1" width="4" height="12" rx="1" />
                        <rect x="8" y="1" width="4" height="12" rx="1" />
                      </svg>
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                        <polygon points="3,1 12,7 3,13" />
                      </svg>
                    )}
                  </button>
                )}
                {bubbleMap?.get(selectedAnchor.id) && (
                  <div className="popup-bubble-images">
                    {bubbleMap.get(selectedAnchor.id)!.gaze && (
                      <img className="popup-bubble-img" src={bubbleMap.get(selectedAnchor.id)!.gaze} alt="Expert gaze" />
                    )}
                    {bubbleMap.get(selectedAnchor.id)!.touch && (
                      <img className="popup-bubble-img" src={bubbleMap.get(selectedAnchor.id)!.touch} alt="Expert touch" />
                    )}
                  </div>
                )}
                <h3
                  className={`popup-title popup-title--tappable${isThisPlaying ? ' popup-title--playing' : ''}`}
                  onClick={anchorAudioUrl ? handlePlayPauseToggle : undefined}
                >
                  <span className={`debug-id-tag${selectedAnchor.contentCategory ? ` cat-${selectedAnchor.contentCategory}` : ''}`}>{selectedAnchor.id}</span>
                  {selectedAnchor.narrative_titles?.[lang || 'en'] ?? selectedAnchor.narrative_title}
                  {anchorAudioUrl && (
                    <svg className="popup-title__wave" width="16" height="12" viewBox="0 0 16 12" fill="currentColor" aria-hidden="true">
                      <rect x="1" y="4" width="2" height="4" rx="1" opacity={isThisPlaying ? 1 : 0.4}>
                        {isThisPlaying && <animate attributeName="height" values="4;10;4" dur="0.8s" repeatCount="indefinite" />}
                        {isThisPlaying && <animate attributeName="y" values="4;1;4" dur="0.8s" repeatCount="indefinite" />}
                      </rect>
                      <rect x="5" y="2" width="2" height="8" rx="1" opacity={isThisPlaying ? 1 : 0.4}>
                        {isThisPlaying && <animate attributeName="height" values="8;3;8" dur="0.6s" repeatCount="indefinite" />}
                        {isThisPlaying && <animate attributeName="y" values="2;4.5;2" dur="0.6s" repeatCount="indefinite" />}
                      </rect>
                      <rect x="9" y="3" width="2" height="6" rx="1" opacity={isThisPlaying ? 1 : 0.4}>
                        {isThisPlaying && <animate attributeName="height" values="6;11;6" dur="0.7s" repeatCount="indefinite" />}
                        {isThisPlaying && <animate attributeName="y" values="3;0.5;3" dur="0.7s" repeatCount="indefinite" />}
                      </rect>
                      <rect x="13" y="4" width="2" height="4" rx="1" opacity={isThisPlaying ? 1 : 0.4}>
                        {isThisPlaying && <animate attributeName="height" values="4;9;4" dur="0.9s" repeatCount="indefinite" />}
                        {isThisPlaying && <animate attributeName="y" values="4;1.5;4" dur="0.9s" repeatCount="indefinite" />}
                      </rect>
                    </svg>
                  )}
                </h3>
                {hasAttention && (
                  <div className="attention-badges">
                    {paneMode === 'description' ? (
                      <>
                        {gazeOverlays && gazeOverlays.length > 0 && (
                          <button
                            className="attention-badge attention-badge--gaze"
                            onClick={(e) => { e.stopPropagation(); setPaneMode('attention'); }}
                            title={`${gazeOverlays.length} gaze point${gazeOverlays.length > 1 ? 's' : ''}`}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <ellipse cx="12" cy="12" rx="9" ry="5" />
                              <circle cx="12" cy="12" r="2.5" fill="currentColor" />
                            </svg>
                            <span>{gazeOverlays.length}</span>
                          </button>
                        )}
                        {touchOverlays && touchOverlays.length > 0 && (
                          <button
                            className="attention-badge attention-badge--touch"
                            onClick={(e) => { e.stopPropagation(); setPaneMode('attention'); }}
                            title={`${touchOverlays.length} touch point${touchOverlays.length > 1 ? 's' : ''}`}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M12 3C12 3 9 5.5 9 9C9 10.8 10 12 11 12.5V20C11 20.6 11.4 21 12 21C12.6 21 13 20.6 13 20V12.5C14 12 15 10.8 15 9C15 5.5 12 3 12 3Z" strokeLinejoin="round" />
                            </svg>
                            <span>{touchOverlays.length}</span>
                          </button>
                        )}
                      </>
                    ) : (
                      <button
                        className="attention-badge attention-badge--transcript"
                        onClick={(e) => { e.stopPropagation(); setPaneMode('description'); }}
                        title="Show transcript"
                      >
                        <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
                          <rect x="1" y="2" width="10" height="1.5" rx="0.5" />
                          <rect x="1" y="5.25" width="7" height="1.5" rx="0.5" />
                          <rect x="1" y="8.5" width="9" height="1.5" rx="0.5" />
                        </svg>
                        <span>Transcript</span>
                      </button>
                    )}
                  </div>
                )}
                {aiEnabled && selectedAnchor.corpusFile && (
                  <button
                    className="popup-ask-btn"
                    onClick={() => setShowConversation(true)}
                    aria-label="Ask the Expert"
                  >
                    <svg width="12" height="12" viewBox="0 0 14 14" fill="currentColor">
                      <path d="M2 2h10v8H8l-3 2v-2H2z" />
                    </svg>
                  </button>
                )}
                {isMobile && (
                  <button
                    className="popup-close-btn"
                    onClick={(e) => { e.stopPropagation(); handleClose(); }}
                    aria-label="Close"
                  >✕</button>
                )}
              </div>

              {/* ── Progress bar (inline under header) ── */}
              {anchorAudioUrl && isThisAnchor && displayDuration > 0 && (
                <div className="anchor-player anchor-player--header">
                  <div className="anchor-player-progress">
                    <div className="anchor-player-fill" style={{ width: `${progressPct}%` }} />
                  </div>
                  <span className="anchor-player-time">{formatTime(displayTime)}</span>
                </div>
              )}

              {/* ── AI ASK ROW — always present when Ask is enabled ── */}
              {aiEnabled && isAskOnline && (
                <div className="ai-ask-persistent">
                  <button
                    className="ai-hear-more-circle"
                    onClick={handleHearMore}
                    disabled={aiLoading}
                    aria-label="Hear more about this location"
                    title="Hear more"
                  >
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                      <circle cx="10" cy="10" r="8.5" stroke="currentColor" strokeWidth="1.5" fill="none" />
                      <circle cx="10" cy="7" r="2" />
                      <path d="M7 13c0-1.7 1.3-3 3-3s3 1.3 3 3" strokeWidth="1.5" stroke="currentColor" fill="none" strokeLinecap="round" />
                    </svg>
                  </button>
                  <input
                    ref={inputRef}
                    type="text"
                    className="ai-ask-input"
                    placeholder="Ask a question…"
                    value={aiInput}
                    onChange={e => setAiInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); handleSend(); } }}
                    onFocus={() => { inputFocusedRef.current = true; }}
                    onBlur={() => { setTimeout(() => { inputFocusedRef.current = false; }, 300); }}
                    enterKeyHint="send"
                    disabled={aiLoading}
                    aria-label="Ask a question about this location"
                  />
                  {SpeechRec && (
                    <button
                      className={`ai-mic-btn${isListening ? ' listening' : ''}`}
                      onClick={handleMic}
                      disabled={aiLoading}
                      aria-label={isListening ? 'Stop listening' : 'Speak your question'}
                    >
                      <svg width="18" height="18" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                        <rect x="7" y="1" width="6" height="10" rx="3" />
                        <path d="M4 10a6 6 0 0 0 12 0" stroke="currentColor" strokeWidth="1.8" fill="none" strokeLinecap="round" />
                        <line x1="10" y1="16" x2="10" y2="19" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                      </svg>
                    </button>
                  )}
                  <button
                    className="ai-send-btn"
                    onClick={handleSend}
                    disabled={aiLoading}
                    aria-label={aiInput.trim() ? 'Send question' : 'Hear more'}
                  >
                    <svg width="16" height="16" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
                      <polygon points="1,1 13,7 1,13 3,7" />
                    </svg>
                  </button>
                </div>
              )}
              {aiEnabled && isAskOnline && aiLoading && (
                <div className="ai-pn-loading" aria-live="polite">···</div>
              )}
              {aiEnabled && isAskOnline && aiError && (
                <div className="ai-ask-error" aria-live="polite">{aiError}</div>
              )}
              {aiEnabled && isAskOnline && aiAnswer && (
                <div className={`ai-pn-answer${aiGrounding ? ` grounding-${aiGrounding}` : ''}`} aria-live="polite">
                  <p>{aiAnswer}</p>
                  {aiGrounding && (
                    <div className={`ai-grounding-label ai-grounding-${aiGrounding}`}>
                      {aiGrounding === 'grounded' && 'from this location\'s notes'}
                      {aiGrounding === 'partial' && 'partly notes, partly general'}
                      {aiGrounding === 'general' && 'general knowledge — unverified'}
                    </div>
                  )}
                  <button
                    className="ai-pn-replay"
                    onClick={() => speakAssistant(aiAnswer)}
                    aria-label="Replay answer"
                  >
                    <svg width="10" height="10" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
                      <polygon points="2,1 12,7 2,13" />
                    </svg>
                    Replay
                  </button>
                </div>
              )}

              {/* ── PANE: description or attention ── */}
              {paneMode === 'description' ? (
                <div className="detail-section interpretation-section">
                  <p className="interpretation-text">
                    {resolveNarrativeText(selectedAnchor, lang ?? 'en')}
                  </p>
                </div>
              ) : (
                <div className="detail-section attention-section">
                  <div className="attention-list">
                    {gazeOverlays?.map((g, i) => (
                      <div key={`gaze-${i}`} className="attention-item" onClick={() => onShowAttentionDetail?.({ type: 'gaze', overlay: g })}>
                        <div className="attention-placeholder attention-placeholder--gaze">
                          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                            <ellipse cx="12" cy="12" rx="10" ry="6" />
                            <circle cx="12" cy="12" r="3" />
                          </svg>
                        </div>
                        <span className="attention-text">
                          {lang === 'it' ? (g._note_it || g.objectLabel_it || g._note || g.objectLabel || 'L\'esperta ha guardato qui') : (g._note || g.objectLabel || 'Expert looked here')}
                        </span>
                      </div>
                    ))}
                    {touchOverlays?.map((t, i) => (
                      <div key={`touch-${i}`} className="attention-item" onClick={() => onShowAttentionDetail?.({ type: 'touch', overlay: t })}>
                        <div className="attention-placeholder attention-placeholder--touch">
                          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                            <path d="M12 2C12 2 8 5 8 9.5C8 11.5 9.5 13 11 13.5V21C11 21.6 11.4 22 12 22C12.6 22 13 21.6 13 21V13.5C14.5 13 16 11.5 16 9.5C16 5 12 2 12 2Z" strokeLinejoin="round" />
                          </svg>
                        </div>
                        <span className="attention-text">{lang === 'it' ? (t.label_it || t.label) : t.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* ── EXPERT'S WORDS (collapsible) ── */}
              {(() => {
                const verbatim = selectedAnchor.expertQuote || selectedAnchor.expertVerbatim || selectedAnchor.transcript_slice || '';
                const vLang = (selectedAnchor as any).verbatimLang as string | undefined;
                const viewerLang = (lang ?? 'en').slice(0, 2);
                const LANG_LABELS: Record<string, string> = { es: 'Spanish', it: 'Italian', en: 'English', mixed: 'Spanish/Italian' };
                const isTranslated = !!vLang && vLang !== viewerLang && vLang !== 'unknown';
                const translatedText = resolveNarrativeText(selectedAnchor, viewerLang);
                return (
                  <div className="detail-section">
                    <button
                      className={`collapsible-toggle${expertWordsOpen ? ' open' : ''}`}
                      onClick={() => setExpertWordsOpen(v => !v)}
                      aria-expanded={expertWordsOpen}
                    >
                      <span>Expert's Words</span>
                      <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" className="chevron">
                        <polygon points="1,3 5,8 9,3" />
                      </svg>
                    </button>
                    {expertWordsOpen && (
                      <>
                        {isTranslated && translatedText && (
                          <blockquote className="transcript-box expert-quote">
                            "{translatedText}"
                            <span className="verbatim-disclosure">Translated from {LANG_LABELS[vLang!] ?? vLang}</span>
                          </blockquote>
                        )}
                        {(!isTranslated || showOriginalTranscript) && (
                          <blockquote className="transcript-box expert-quote expert-quote--original">
                            {isTranslated && <span className="verbatim-original-label">Original transcript</span>}
                            "{verbatim}"
                          </blockquote>
                        )}
                      </>
                    )}
                  </div>
                );
              })()}

            </div>
          )

        ) : isMobile ? null : (
          /* ── Anchor list (desktop only — mobile uses NarrativeBubble) ── */
          <div className="list-panel">
            {anchors.map((anchor) => (
              <div
                key={anchor.id}
                className="anchor-item"
                onClick={() => onSelect(anchor)}
              >
                <span className="item-title">{anchor.narrative_titles?.[lang || 'en'] ?? anchor.narrative_title}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
