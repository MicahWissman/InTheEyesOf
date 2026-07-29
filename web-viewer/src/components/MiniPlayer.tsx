import { useAudio } from '../contexts/AudioContext';

interface MiniPlayerProps {
  title: string | null;
  visible: boolean;
}

export function MiniPlayer({ title, visible }: MiniPlayerProps) {
  const { isPlaying, currentTime, duration, pauseAudio, resumeAudio } = useAudio();

  if (!visible || !title) return null;

  const progress = duration > 0 ? currentTime / duration : 0;
  const fmt = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, '0')}`;
  };

  return (
    <div className="mini-player">
      <div className="mini-player__progress" style={{ width: `${progress * 100}%` }} />
      <button className="mini-player__btn" onClick={isPlaying ? pauseAudio : resumeAudio}>
        {isPlaying ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <rect x="3" y="2" width="3.5" height="12" rx="1" />
            <rect x="9.5" y="2" width="3.5" height="12" rx="1" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <polygon points="4,2 14,8 4,14" />
          </svg>
        )}
      </button>
      <span className="mini-player__title">{title}</span>
      <span className="mini-player__time">{fmt(currentTime)} / {fmt(duration)}</span>
    </div>
  );
}
