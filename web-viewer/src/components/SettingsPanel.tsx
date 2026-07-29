type Lang = 'en' | 'it' | 'es';
const LANG_LABELS: Record<Lang, string> = { en: 'EN', it: 'IT', es: 'ES' };

interface SettingsPanelProps {
  open: boolean;
  onClose: () => void;
  // Language
  lang?: string;
  onLangChange?: (lang: Lang) => void;
  // Voice gender
  gender?: string;
  onGenderChange?: (gender: 'm' | 'f') => void;
  // Fade
  fadeEnabled: boolean;
  onFadeEnabled: (v: boolean) => void;
  fadeEnd: number;
  onFadeEnd: (v: number) => void;
  // Vertical level
  heightOffset: number;
  onHeightOffset: (v: number) => void;
  // Audio
  audioEnabled: boolean;
  onToggleAudio: () => void;
  proximityAutoPlay: boolean;
  onProximityAutoPlay: (v: boolean) => void;
  // Compass
  compassOffset: number;
  onCompassOffset: (v: number) => void;
  // AR
  arAutoReturn: boolean;
  onArAutoReturn: (v: boolean) => void;
  onEnterAR?: () => void;
  onExitAR?: () => void;
  isArAvailable?: boolean;
  viewMode?: string;
  // GPS
  gpsStatus?: 'waiting' | 'active' | 'error' | 'too_far';
  onRetryGps?: () => void;
  // CAM overlays
  camShowGaze?: boolean;
  onCamShowGaze?: (v: boolean) => void;
  camShowTouch?: boolean;
  onCamShowTouch?: (v: boolean) => void;
  // Transcript
  showOriginalTranscript: boolean;
  onShowOriginalTranscript: (v: boolean) => void;
  // Experimental
  aiEnabled: boolean;
  onToggleAI: () => void;
  // Session
  onFlushMemory: () => void;
  onRestartSession: () => void;
}

export function SettingsPanel({
  open, onClose,
  lang, onLangChange, gender, onGenderChange,
  fadeEnabled, onFadeEnabled, fadeEnd, onFadeEnd,
  heightOffset, onHeightOffset,
  audioEnabled, onToggleAudio,
  proximityAutoPlay, onProximityAutoPlay,
  compassOffset, onCompassOffset,
  arAutoReturn, onArAutoReturn,
  onEnterAR, onExitAR, isArAvailable, viewMode,
  gpsStatus, onRetryGps,
  camShowGaze, onCamShowGaze, camShowTouch, onCamShowTouch,
  showOriginalTranscript, onShowOriginalTranscript,
  aiEnabled, onToggleAI,
  onFlushMemory, onRestartSession,
}: SettingsPanelProps) {
  return (
    <>
      {open && <div className="settings-backdrop" onClick={onClose} />}
      <div className={`settings-panel${open ? ' open' : ''}`} role="dialog" aria-label="Settings">
        <div className="settings-header">
          <span className="settings-title">Settings</span>
          <button className="settings-close-btn" onClick={onClose} aria-label="Close settings">✕</button>
        </div>

        <div className="settings-body">

          {onLangChange && (
            <section className="settings-section">
              <div className="settings-section-title">Language</div>
              <div className="settings-row">
                {(Object.keys(LANG_LABELS) as Lang[]).map(code => (
                  <button
                    key={code}
                    className={`settings-lang-btn${lang === code ? ' active' : ''}`}
                    onClick={() => onLangChange(code)}
                  >
                    {LANG_LABELS[code]}
                  </button>
                ))}
              </div>
            </section>
          )}

          {onGenderChange && (
            <section className="settings-section">
              <div className="settings-section-title">Voice</div>
              <div className="settings-row">
                {(['f', 'm'] as const).map(g => (
                  <button
                    key={g}
                    className={`settings-lang-btn${gender === g ? ' active' : ''}`}
                    onClick={() => onGenderChange(g)}
                  >
                    {g === 'f' ? 'Female' : 'Male'}
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="settings-section">
            <div className="settings-section-title">Distance Fade</div>
            <div className="settings-row">
              <span className="settings-row-label">Enable</span>
              <button
                className={`settings-toggle${fadeEnabled ? ' on' : ''}`}
                onClick={() => onFadeEnabled(!fadeEnabled)}
                aria-pressed={fadeEnabled}
              >
                {fadeEnabled ? 'On' : 'Off'}
              </button>
            </div>
            {fadeEnabled && (
              <div className="settings-row">
                <span className="settings-row-label">Distance</span>
                <input
                  type="range"
                  className="settings-slider"
                  min={2} max={30} step={1}
                  value={fadeEnd}
                  onChange={e => onFadeEnd(Number(e.target.value))}
                  aria-label="Depth fade distance"
                />
                <span className="settings-row-value">{Math.round(fadeEnd)}m</span>
              </div>
            )}
          </section>

          <section className="settings-section">
            <div className="settings-section-title">Vertical Level</div>
            <div className="settings-row">
              <span className="settings-row-label">Eye height</span>
              <input
                type="range"
                className="settings-slider"
                min={-7} max={7} step={0.1}
                value={heightOffset}
                onChange={e => onHeightOffset(Number(e.target.value))}
                aria-label="Camera eye height above floor"
              />
              <span className="settings-row-value">
                {heightOffset >= 0 ? '+' : ''}{heightOffset.toFixed(1)}m
              </span>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title">Audio</div>
            <div className="settings-row">
              <span className="settings-row-label">Audio</span>
              <button
                className={`settings-toggle${audioEnabled ? ' on' : ''}`}
                onClick={onToggleAudio}
                aria-pressed={audioEnabled}
              >
                {audioEnabled ? 'On' : 'Off'}
              </button>
            </div>
            <div className="settings-row">
              <span className="settings-row-label">Walk-up auto-play</span>
              <button
                className={`settings-toggle${proximityAutoPlay ? ' on' : ''}`}
                onClick={() => onProximityAutoPlay(!proximityAutoPlay)}
                aria-pressed={proximityAutoPlay}
              >
                {proximityAutoPlay ? 'On' : 'Off'}
              </button>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title">Content</div>
            <div className="settings-row">
              <span className="settings-row-label">Original transcript</span>
              <button
                className={`settings-toggle${showOriginalTranscript ? ' on' : ''}`}
                onClick={() => onShowOriginalTranscript(!showOriginalTranscript)}
                aria-pressed={showOriginalTranscript}
              >
                {showOriginalTranscript ? 'On' : 'Off'}
              </button>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title">Compass Calibration</div>
            <div className="settings-row">
              <span className="settings-row-label">Flip 180°</span>
              <button
                className={`settings-toggle${compassOffset === 180 ? ' on' : ''}`}
                onClick={() => onCompassOffset(compassOffset === 180 ? 0 : 180)}
              >
                {compassOffset === 180 ? 'On' : 'Off'}
              </button>
            </div>
            <div className="settings-row">
              <span className="settings-row-label">Fine adjust</span>
              <input
                type="range"
                className="settings-slider"
                min={0} max={359} step={1}
                value={compassOffset}
                onChange={e => onCompassOffset(Number(e.target.value))}
                aria-label="Compass heading offset"
              />
              <input
                type="number"
                className="settings-number-input"
                min={0} max={359} step={1}
                value={compassOffset}
                onChange={e => {
                  const v = Number(e.target.value);
                  if (!isNaN(v)) onCompassOffset(((v % 360) + 360) % 360);
                }}
                aria-label="Compass heading offset degrees"
              />
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title">GPS</div>
            <div className="settings-row">
              <span className="settings-row-label">Status</span>
              <span className="settings-row-value" style={{
                color: gpsStatus === 'active' ? '#00ff88' : gpsStatus === 'error' ? '#ff4444' : gpsStatus === 'too_far' ? '#ffaa44' : '#888',
              }}>
                {gpsStatus === 'active' ? 'Active' : gpsStatus === 'error' ? 'Error' : gpsStatus === 'too_far' ? 'Too far from site' : 'Waiting…'}
              </span>
            </div>
            {gpsStatus !== 'active' && onRetryGps && (
              <button className="settings-action-btn" onClick={onRetryGps}>
                {gpsStatus === 'too_far' ? 'Force GPS Activation' : 'Request GPS Permission'}
              </button>
            )}
          </section>

          {onCamShowGaze && onCamShowTouch && (
            <section className="settings-section">
              <div className="settings-section-title">CAM Overlays</div>
              <div className="settings-row">
                <span className="settings-row-label">Gaze marks</span>
                <button
                  className={`settings-toggle${camShowGaze ? ' on' : ''}`}
                  onClick={() => onCamShowGaze(!camShowGaze)}
                  aria-pressed={camShowGaze}
                >
                  {camShowGaze ? 'On' : 'Off'}
                </button>
              </div>
              <div className="settings-row">
                <span className="settings-row-label">Touch marks</span>
                <button
                  className={`settings-toggle${camShowTouch ? ' on' : ''}`}
                  onClick={() => onCamShowTouch(!camShowTouch)}
                  aria-pressed={camShowTouch}
                >
                  {camShowTouch ? 'On' : 'Off'}
                </button>
              </div>
            </section>
          )}

          <section className="settings-section">
            <div className="settings-section-title">AR Street View</div>
            {isArAvailable && onEnterAR && (
              <div className="settings-row">
                <span className="settings-row-label">GPS-pinned street view</span>
                <button
                  className={`settings-toggle${viewMode === 'ar' ? ' on' : ''}`}
                  onClick={() => {
                    if (viewMode === 'ar' && onExitAR) { onExitAR(); }
                    else { onEnterAR(); }
                    onClose();
                  }}
                >
                  {viewMode === 'ar' ? 'On' : 'Off'}
                </button>
              </div>
            )}
            {!isArAvailable && (
              <div className="settings-row">
                <span className="settings-row-label" style={{ color: '#555' }}>Requires mobile + orientation sensor</span>
              </div>
            )}
            <div className="settings-row">
              <span className="settings-row-label">Auto-return when idle</span>
              <button
                className={`settings-toggle${arAutoReturn ? ' on' : ''}`}
                onClick={() => onArAutoReturn(!arAutoReturn)}
                aria-pressed={arAutoReturn}
              >
                {arAutoReturn ? 'On' : 'Off'}
              </button>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title">Experimental</div>
            <div className="settings-row">
              <span className="settings-row-label">AI Ask (self-reported, unverified)</span>
              <button
                className={`settings-toggle${aiEnabled ? ' on' : ''}`}
                onClick={onToggleAI}
                aria-pressed={aiEnabled}
              >
                {aiEnabled ? 'On' : 'Off'}
              </button>
            </div>
          </section>

          <section className="settings-section">
            <div className="settings-section-title">Session</div>
            <button className="settings-action-btn" onClick={onFlushMemory}>
              Flush session memory
            </button>
            <button className="settings-action-btn settings-action-danger" onClick={onRestartSession}>
              Restart session
            </button>
          </section>

        </div>
      </div>
    </>
  );
}
