import type { Anchor } from '../types';

export function resolveAudioUrl(
  anchor: Anchor,
  lang: string,
  gender: string,
): string | null {
  if (anchor.audioUrls) {
    const langMap = anchor.audioUrls[lang];
    if (langMap) {
      if (langMap[gender]) return langMap[gender];
      if (langMap[gender === 'm' ? 'f' : 'm']) return langMap[gender === 'm' ? 'f' : 'm'];
    }
    const enMap = anchor.audioUrls['en'];
    if (enMap) {
      if (enMap[gender]) return enMap[gender];
      if (enMap[gender === 'm' ? 'f' : 'm']) return enMap[gender === 'm' ? 'f' : 'm'];
    }
  }
  return anchor.audioUrl ?? null;
}

export function resolveNarrativeText(
  anchor: Anchor,
  lang: string,
): string {
  if (anchor.text) {
    if (anchor.text[lang]) return anchor.text[lang];
    if (anchor.text['en']) return anchor.text['en'];
  }
  return anchor.interpretation || anchor.narrative_description || anchor.narrative_title || '';
}
