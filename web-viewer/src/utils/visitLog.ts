// Anonymous visitor interaction log — the behavioural signals an adaptive layer would learn from:
// which perspective a visitor picks, how long they stay, what they skip, finish or replay.
//
// Identity: a random id per browser tab session (sessionStorage), never a name, account or IP.
// Transport: events are queued and POSTed to /log in batches (sendBeacon on page hide so the
// last batch survives the tab closing). Disable for a device with ?nolog=1.

export type ListenTrigger = 'tap' | 'sidebar' | 'transcript' | 'proximity' | 'cam' | 'auto';
export type ListenOutcome = 'completed' | 'skipped' | 'stopped' | 'left' | 'failed';

interface AnchorMeta { perspective: string | null; title: string }

const ENDPOINT = '/log';
const FLUSH_MS = 10_000;

const enabled = (() => {
  try { return new URLSearchParams(window.location.search).get('nolog') !== '1'; } catch { return true; }
})();

const visitorId = (() => {
  const make = () => (crypto.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36));
  try {
    let id = sessionStorage.getItem('eyesof:visitor');
    if (!id) { id = make(); sessionStorage.setItem('eyesof:visitor', id); }
    return id;
  } catch { return make(); }
})();

const t0 = Date.now();
let seq = 0;
let queue: Record<string, unknown>[] = [];
let recording: string | null = null;
let anchorMeta = new Map<number, AnchorMeta>();
let heard = new Set<string>();      // `${anchorId}|${track}` played this session → replay detection
let open: { anchorId: number; track: string; trigger: ListenTrigger; startedAt: number } | null = null;
let viewed = new Set<number>();     // anchors opened this session → revisit detection
let openView: { anchorId: number; startedAt: number } | null = null;

function flush(useBeacon = false) {
  if (!queue.length) return;
  const body = JSON.stringify(queue);
  queue = [];
  try {
    if (useBeacon && navigator.sendBeacon?.(ENDPOINT, new Blob([body], { type: 'application/json' }))) return;
    fetch(ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {});
  } catch { /* logging must never break the app */ }
}

export function logEvent(type: string, data: Record<string, unknown> = {}) {
  if (!enabled) return;
  queue.push({ v: visitorId, seq: seq++, type, at: new Date().toISOString(), t: (Date.now() - t0) / 1000, rec: recording, ...data });
  if (queue.length >= 50) flush();
}

function anchorFields(anchorId: number) {
  const m = anchorMeta.get(anchorId);
  return { anchor: anchorId, perspective: m?.perspective ?? null, title: m?.title ?? null };
}

/** Called when a recording's anchors load; starts a per-recording session. */
export function setLogRecording(recordingId: string, anchors: { id: number; source_person?: string; narrative_title?: string }[]) {
  if (recording === recordingId) return;
  if (recording) logEvent('session_end', { reason: 'switch_recording' });
  recording = recordingId;
  anchorMeta = new Map(anchors.map(a => [a.id, { perspective: a.source_person ?? null, title: a.narrative_title ?? '' }]));
  heard = new Set();
  viewed = new Set();
  openView = null;
  const coarse = (() => { try { return matchMedia('(pointer: coarse)').matches; } catch { return false; } })();
  logEvent('session_start', {
    device: coarse ? 'mobile' : 'desktop',
    anchors: anchors.length,
    perspectives: [...new Set(anchors.map(a => a.source_person).filter(Boolean))],
  });
}

/** A clip starts. `track` is 'narration' or 'transcript' (the expert's own words). */
export function logListenStart(anchorId: number, track: string, trigger: ListenTrigger) {
  const key = `${anchorId}|${track}`;
  const replay = heard.has(key);
  heard.add(key);
  open = { anchorId, track, trigger, startedAt: Date.now() };
  logEvent('listen_start', { ...anchorFields(anchorId), track, trigger, replay });
}

/** The open clip ends. `position`/`duration` are seconds into / length of the audio. */
export function logListenEnd(outcome: ListenOutcome, position: number, duration: number) {
  if (!open) return;
  const dur = Number.isFinite(duration) && duration > 0 ? duration : null;
  const pos = outcome === 'completed' && dur ? dur : position;
  logEvent('listen_end', {
    ...anchorFields(open.anchorId), track: open.track, trigger: open.trigger, outcome,
    position_s: +pos.toFixed(1), duration_s: dur && +dur.toFixed(1),
    fraction: dur ? +Math.min(1, pos / dur).toFixed(3) : null,
    wall_s: +((Date.now() - open.startedAt) / 1000).toFixed(1),
  });
  open = null;
}

/** Selected anchor changed (null = closed). Covers text-only recordings, where nothing plays:
 *  which anchors a visitor opens, how long each stays open, and which they come back to. */
export function logAnchorView(anchorId: number | null) {
  if (openView?.anchorId === anchorId) return;
  if (openView) {
    logEvent('view_end', { ...anchorFields(openView.anchorId), dwell_s: +((Date.now() - openView.startedAt) / 1000).toFixed(1) });
    openView = null;
  }
  if (anchorId == null) return;
  const revisit = viewed.has(anchorId);
  viewed.add(anchorId);
  openView = { anchorId, startedAt: Date.now() };
  logEvent('view_start', { ...anchorFields(anchorId), revisit });
}

export function logListenAction(type: 'pause' | 'resume' | 'seek', data: Record<string, unknown> = {}) {
  if (!open) return;
  logEvent(type, { anchor: open.anchorId, track: open.track, ...data });
}

// Position of the clip currently playing — registered by AudioContext so a page close
// can still record how far the open clip got.
let positionProvider: (() => { position: number; duration: number }) | null = null;
export function setLogPositionProvider(fn: typeof positionProvider) { positionProvider = fn; }

if (enabled) {
  setInterval(() => flush(), FLUSH_MS);
  // Hidden ≠ gone: on a walking tour the screen locks while narration keeps playing, so
  // hiding only records where the clip was. pagehide (tab closed / navigated away) ends it.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      const p = open && positionProvider ? positionProvider() : null;
      logEvent('page_hidden', p ? { anchor: open!.anchorId, position_s: +p.position.toFixed(1) } : {});
      flush(true);
    } else if (recording) logEvent('page_visible');
  });
  window.addEventListener('pagehide', () => {
    if (open && positionProvider) { const p = positionProvider(); logListenEnd('left', p.position, p.duration); }
    logAnchorView(null);
    logEvent('session_end', { reason: 'pagehide' });
    flush(true);
  });
}
