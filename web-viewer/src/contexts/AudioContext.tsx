import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';


// Minimal silent WAV (0.1 s, 8 kHz mono) for browser audio unlock via user gesture
const SILENT_WAV = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAZGF0YQQAAAAAAA==';

// If currentTime hasn't advanced past this threshold within STUCK_WATCHDOG_MS after
// play() is called, the play is treated as stuck and retried once, then released.
const STUCK_THRESHOLD_S = 0.05;
const STUCK_WATCHDOG_MS = 1500;

// Strip scheme + host from any absolute URL so the audio element always requests
// over the page's own scheme (https).  Root-relative (/path), data:, and blob:
// URLs pass through unchanged.
//
// Before: "http://pi/recordings/riva1/audio/anchor_000.mp3"
// After:  "/recordings/riva1/audio/anchor_000.mp3"
function toRootRelative(url: string): string {
  if (!url
    || url.startsWith('/')
    || url.startsWith('data:')
    || url.startsWith('blob:')) {
    return url;
  }
  // "//host/path" → "/path"
  if (url.startsWith('//')) {
    return url.replace(/^\/\/[^/]+/, '') || '/';
  }
  // "http(s)://host/path" → "/path"
  const m = url.match(/^https?:\/\/[^/]+(\/.*)?$/);
  if (m) return m[1] ?? '/';
  return url;
}

export interface AudioContextValue {
  audioEnabled: boolean;          // true = unmuted (default); false = muted
  audioUnlocked: boolean;         // true = user has tapped at least once
  currentAnchorId: number | null;
  lastEndedId: number | null;     // id of the anchor whose audio last ended naturally
  isPlaying: boolean;
  currentTime: number;
  duration: number;
  toggleAudio: () => void;
  setNowPlayingTitle: (title: string) => void;
  playAnchorWithUnlock: (anchorId: number, url: string) => void;
  playAnchor: (anchorId: number, url: string) => void;
  pauseAudio: () => void;
  resumeAudio: () => void;
  stopAudio: () => void;
  seekAudio: (time: number) => void;
}

const AudioCtx = createContext<AudioContextValue | null>(null);

export function AudioProvider({ children }: { children: ReactNode }) {
  const [audioEnabled, setAudioEnabled] = useState<boolean>(true);
  const [audioUnlocked, setAudioUnlocked] = useState(false);
  const [currentAnchorId, setCurrentAnchorId] = useState<number | null>(null);
  const [lastEndedId, setLastEndedId] = useState<number | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const audioRef           = useRef<HTMLAudioElement | null>(null);
  const currentSrcRef      = useRef<string | null>(null);
  const unlockedRef        = useRef(false);
  const currentAnchorIdRef = useRef<number | null>(null);
  const nowPlayingTitleRef = useRef<string>('');
  // Sync mirrors for watchdog — avoid stale React state in setTimeout closures
  const isPlayingRef   = useRef(false);
  const currentTimeRef = useRef(0);
  const watchdogRef    = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── channel-management helpers ──────────────────────────────────────────────

  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current !== null) {
      clearTimeout(watchdogRef.current);
      watchdogRef.current = null;
    }
  }, []);

  // Release the single-channel lock so the next anchor can play.
  // Called from: play() rejection, 'error' event, watchdog timeout (after 1 retry).
  const releaseChannel = useCallback(() => {
    clearWatchdog();
    isPlayingRef.current = false;
    setIsPlaying(false);
    currentAnchorIdRef.current = null;
    setCurrentAnchorId(null);
    currentTimeRef.current = 0;
    setCurrentTime(0);
  }, [clearWatchdog]);

  // ── mute / unmount lifecycle ─────────────────────────────────────────────────

  useEffect(() => {
    if (!audioEnabled && audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      currentSrcRef.current = null;
      releaseChannel();
    }
  }, [audioEnabled, releaseChannel]);

  useEffect(() => () => {
    clearWatchdog();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      audioRef.current = null;
    }
  }, [clearWatchdog]);

  // ── element factory ──────────────────────────────────────────────────────────

  const ensureAudio = useCallback((): HTMLAudioElement => {
    if (!audioRef.current) {
      const el = new Audio();
      el.preload = 'auto';

      el.addEventListener('timeupdate', () => {
        currentTimeRef.current = el.currentTime;
        setCurrentTime(el.currentTime);
        // Time has advanced — this play is healthy; disarm watchdog
        if (el.currentTime > STUCK_THRESHOLD_S) clearWatchdog();
      });

      el.addEventListener('durationchange', () =>
        setDuration(isFinite(el.duration) ? el.duration : 0),
      );

      el.addEventListener('play', () => {
        isPlayingRef.current = true;
        setIsPlaying(true);
        if ('mediaSession' in navigator && nowPlayingTitleRef.current) {
          navigator.mediaSession.metadata = new MediaMetadata({
            title: nowPlayingTitleRef.current,
            artist: 'In the Eyes Of',
          });
          navigator.mediaSession.playbackState = 'playing';
        }
      });

      el.addEventListener('pause', () => {
        isPlayingRef.current = false;
        setIsPlaying(false);
        clearWatchdog();
        currentSrcRef.current = null;
        if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'paused';
      });

      el.addEventListener('ended', () => {
        isPlayingRef.current = false;
        setIsPlaying(false);
        clearWatchdog();
        currentTimeRef.current = 0;
        setCurrentTime(0);
        setLastEndedId(currentAnchorIdRef.current);
        currentAnchorIdRef.current = null;
        setCurrentAnchorId(null);
        currentSrcRef.current = null;
        if ('mediaSession' in navigator) navigator.mediaSession.playbackState = 'none';
      });

      // Network / decode error — release so the channel doesn't wedge
      el.addEventListener('error', () => {
        releaseChannel();
      });

      if ('mediaSession' in navigator) {
        navigator.mediaSession.setActionHandler('play',  () => el.play().catch(() => {}));
        navigator.mediaSession.setActionHandler('pause', () => el.pause());
        navigator.mediaSession.setActionHandler('stop',  () => { el.pause(); el.currentTime = 0; });
      }

      audioRef.current = el;
    }
    return audioRef.current;
  }, [clearWatchdog, releaseChannel]);

  // ── core play helper ─────────────────────────────────────────────────────────
  //
  // Calls audio.play(), handles the returned Promise, and arms a stuck-at-0 watchdog.
  //
  // currentTime is reset to 0 only when the element has valid metadata (readyState >= 1).
  // This avoids a seek on an unloaded element (e.g. right after load() before the
  // 'loadedmetadata' event fires).  A fresh load() already resets currentTime to 0, so
  // the guard matters only for same-src re-requests (restart case).
  //
  // Watchdog: if currentTime hasn't passed STUCK_THRESHOLD_S within STUCK_WATCHDOG_MS,
  // retry play() once; if still stuck, release channel so the next anchor can proceed.
  const doPlay = useCallback((audio: HTMLAudioElement, anchorId: number) => {
    clearWatchdog();

    // Guard: only seek to 0 when metadata is available.  A new load() already resets
    // to 0; skipping this on readyState 0 avoids a no-op seek that throws on some
    // browsers when src is not yet loaded.
    if (audio.readyState >= 1 /* HAVE_METADATA */) {
      audio.currentTime = 0;
    }
    currentTimeRef.current = 0;

    const p = audio.play();
    p?.catch((err: Error) => {
      // AbortError is expected when load() interrupts a pending play (switching src).
      // Any other rejection means the play truly failed — release so nothing is blocked.
      if (err?.name !== 'AbortError') {
        releaseChannel();
      }
    });

    // Arm watchdog — retries once, then gives up cleanly
    const armWatchdog = (retryDone: boolean) => {
      watchdogRef.current = setTimeout(() => {
        watchdogRef.current = null;
        if (!isPlayingRef.current
          || currentTimeRef.current > STUCK_THRESHOLD_S
          || currentAnchorIdRef.current !== anchorId) return;

        if (retryDone) {
          // Second attempt also stuck — release channel
          releaseChannel();
        } else {
          // First retry
          audio.play()?.catch(() => releaseChannel());
          armWatchdog(true);
        }
      }, STUCK_WATCHDOG_MS);
    };
    armWatchdog(false);
  }, [clearWatchdog, releaseChannel]);

  // ── public API ───────────────────────────────────────────────────────────────

  const toggleAudio = useCallback(() => setAudioEnabled(v => !v), []);

  const setNowPlayingTitle = useCallback((title: string) => {
    nowPlayingTitleRef.current = title;
    if ('mediaSession' in navigator && title) {
      navigator.mediaSession.metadata = new MediaMetadata({
        title,
        artist: 'In the Eyes Of',
      });
    }
  }, []);

  // Gesture path — performs silent-WAV unlock on first tap, then plays url.
  const playAnchorWithUnlock = useCallback((anchorId: number, url: string) => {
    if (!audioEnabled) return;
    const audio = ensureAudio();
    const src = toRootRelative(url);
    currentAnchorIdRef.current = anchorId;
    setCurrentAnchorId(anchorId);

    if (!unlockedRef.current) {
      audio.pause();
      audio.src = SILENT_WAV;
      audio.play()
        .then(() => {
          audio.pause();
          unlockedRef.current = true;
          setAudioUnlocked(true);
          audio.src = src;
          audio.load();
          currentSrcRef.current = src;
          doPlay(audio, anchorId);
        })
        .catch(() => {});
    } else {
      if (currentSrcRef.current !== src) {
        audio.pause();
        audio.src = src;
        audio.load();
        currentSrcRef.current = src;
      }
      doPlay(audio, anchorId);
    }
  }, [audioEnabled, ensureAudio, doPlay]);

  // Proximity / auto-play path — browser rejects silently if no prior gesture.
  const playAnchor = useCallback((anchorId: number, url: string) => {
    if (!audioEnabled) return;
    const audio = ensureAudio();
    const src = toRootRelative(url);
    if (currentSrcRef.current !== src) {
      audio.pause();
      audio.src = src;
      audio.load();
      currentSrcRef.current = src;
    }
    currentAnchorIdRef.current = anchorId;
    setCurrentAnchorId(anchorId);
    doPlay(audio, anchorId);
  }, [audioEnabled, ensureAudio, doPlay]);

  const pauseAudio = useCallback(() => { audioRef.current?.pause(); }, []);

  // Resume from paused position — no seek, no watchdog; audio is already loaded.
  const resumeAudio = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.play()?.catch((err: Error) => {
      if (err?.name !== 'AbortError') releaseChannel();
    });
  }, [releaseChannel]);

  const stopAudio = useCallback(() => {
    clearWatchdog();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = '';
      currentSrcRef.current = null;
    }
    currentAnchorIdRef.current = null;
    setCurrentAnchorId(null);
    isPlayingRef.current = false;
    setIsPlaying(false);
    currentTimeRef.current = 0;
    setCurrentTime(0);
  }, [clearWatchdog]);

  const seekAudio = useCallback((time: number) => {
    if (audioRef.current) audioRef.current.currentTime = time;
  }, []);

  return (
    <AudioCtx.Provider value={{
      audioEnabled, audioUnlocked,
      currentAnchorId, lastEndedId, isPlaying, currentTime, duration,
      toggleAudio, setNowPlayingTitle, playAnchorWithUnlock,
      playAnchor, pauseAudio, resumeAudio, stopAudio, seekAudio,
    }}>
      {children}
    </AudioCtx.Provider>
  );
}

export function useAudio(): AudioContextValue {
  const ctx = useContext(AudioCtx);
  if (!ctx) throw new Error('useAudio must be used inside <AudioProvider>');
  return ctx;
}
