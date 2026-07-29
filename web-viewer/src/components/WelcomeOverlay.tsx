import { useEffect, useState } from 'react';

interface WelcomeOverlayProps {
  visible: boolean;
  lang: string;
  onDismiss: () => void;
}

const CONTENT = {
  en: {
    title: 'In the Eyes of Adine',
    subtitle: 'Carona — Expert-guided heritage walk',
    stats: '3 churches · 30 stops · ~40 min',
    instructions: [
      { icon: 'tap', text: 'Tap a point to listen' },
      { icon: 'eye', text: 'Eye = where she looked' },
      { icon: 'hand', text: 'Hand = what she touched' },
    ],
    dismiss: 'Start exploring',
  },
  it: {
    title: 'Negli Occhi di Adine',
    subtitle: 'Carona — Passeggiata guidata nel patrimonio',
    stats: '3 chiese · 30 tappe · ~40 min',
    instructions: [
      { icon: 'tap', text: 'Tocca un punto per ascoltare' },
      { icon: 'eye', text: 'Occhio = dove ha guardato' },
      { icon: 'hand', text: 'Mano = cosa ha toccato' },
    ],
    dismiss: 'Inizia a esplorare',
  },
};

export function WelcomeOverlay({ visible, lang, onDismiss }: WelcomeOverlayProps) {
  const [fadingOut, setFadingOut] = useState(false);

  useEffect(() => {
    if (!visible) setFadingOut(false);
  }, [visible]);

  if (!visible && !fadingOut) return null;

  const c = CONTENT[lang as keyof typeof CONTENT] ?? CONTENT.en;

  const handleDismiss = () => {
    setFadingOut(true);
    setTimeout(onDismiss, 600);
  };

  return (
    <div className={`welcome-overlay${fadingOut ? ' welcome-overlay--fading' : ''}`} onClick={handleDismiss}>
      <div className="welcome-overlay__card" onClick={e => e.stopPropagation()}>
        <h1 className="welcome-overlay__title">{c.title}</h1>
        <p className="welcome-overlay__subtitle">{c.subtitle}</p>
        <p className="welcome-overlay__stats">{c.stats}</p>

        <div className="welcome-overlay__instructions">
          {c.instructions.map((inst, i) => (
            <div key={i} className="welcome-overlay__inst">
              <span className={`welcome-overlay__icon welcome-overlay__icon--${inst.icon}`}>
                {inst.icon === 'tap' && (
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
                  </svg>
                )}
                {inst.icon === 'eye' && (
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#44bbff" strokeWidth="1.5">
                    <ellipse cx="12" cy="12" rx="10" ry="6" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
                {inst.icon === 'hand' && (
                  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#ff8844" strokeWidth="1.5">
                    <path d="M12 2C12 2 8 5 8 9.5C8 11.5 9.5 13 11 13.5V21C11 21.6 11.4 22 12 22C12.6 22 13 21.6 13 21V13.5C14.5 13 16 11.5 16 9.5C16 5 12 2 12 2Z" strokeLinejoin="round" />
                  </svg>
                )}
              </span>
              <span className="welcome-overlay__inst-text">{inst.text}</span>
            </div>
          ))}
        </div>

        <button className="welcome-overlay__btn" onClick={handleDismiss}>
          {c.dismiss}
        </button>
      </div>
    </div>
  );
}
