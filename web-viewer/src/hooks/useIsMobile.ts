import { useState, useEffect } from 'react';

const MOBILE_BREAKPOINT = 768;

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(() =>
    window.innerWidth < MOBILE_BREAKPOINT ||
    window.matchMedia('(pointer: coarse)').matches
  );

  useEffect(() => {
    const widthMq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const touchMq = window.matchMedia('(pointer: coarse)');
    const handler = () => setIsMobile(widthMq.matches || touchMq.matches);
    widthMq.addEventListener('change', handler);
    touchMq.addEventListener('change', handler);
    return () => {
      widthMq.removeEventListener('change', handler);
      touchMq.removeEventListener('change', handler);
    };
  }, []);

  return isMobile;
}
