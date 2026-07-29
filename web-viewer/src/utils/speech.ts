// Assistant voice for synthesized AI answers — intentionally distinct from expert
// pre-baked audio so visitors can tell the difference audibly.

let cachedVoice: SpeechSynthesisVoice | null | undefined = undefined;

function pickVoice(): SpeechSynthesisVoice | null {
  if (!window.speechSynthesis) return null;
  if (cachedVoice !== undefined) return cachedVoice;
  const voices = window.speechSynthesis.getVoices();
  if (!voices.length) return null;
  cachedVoice =
    voices.find(v => v.name === 'Google UK English Female') ??
    voices.find(v => v.name.includes('Samantha') && v.lang.startsWith('en')) ??
    voices.find(v => v.name.includes('Karen') && v.lang.startsWith('en')) ??
    voices.find(v => v.lang === 'en-GB') ??
    voices.find(v => v.lang.startsWith('en') && !v.default) ??
    voices.find(v => v.lang.startsWith('en')) ??
    null;
  return cachedVoice;
}

function apply(utt: SpeechSynthesisUtterance): void {
  utt.rate = 0.92;
  utt.pitch = 1.05;
  utt.volume = 1.0;
  const v = pickVoice();
  if (v) utt.voice = v;
}

export function speakAssistant(text: string): void {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utt = new SpeechSynthesisUtterance(text);

  const voices = window.speechSynthesis.getVoices();
  if (voices.length > 0) {
    apply(utt);
    window.speechSynthesis.speak(utt);
  } else {
    // Chrome loads voices asynchronously; wait for the first load
    window.speechSynthesis.addEventListener('voiceschanged', () => {
      cachedVoice = undefined; // re-pick now that voices are available
      apply(utt);
      window.speechSynthesis.speak(utt);
    }, { once: true });
  }
}

export function stopSpeaking(): void {
  window.speechSynthesis?.cancel();
}
