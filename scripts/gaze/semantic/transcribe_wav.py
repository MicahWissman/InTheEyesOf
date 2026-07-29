#!/usr/bin/env python3
"""
Multilingual transcription of an extracted WAV into the pipeline's
[0000s - 0010s]: text  chunk format.

Backends (--backend):
  * faster-whisper (default): fast, robust ASR. Supports per-window language
    detection (--lang-window) to handle es/it/en code-switching.
  * whisperx: same Whisper acoustic model + wav2vec FORCED ALIGNMENT (tighter
    timestamps) + optional speaker DIARIZATION (--diarize). WhisperX alignment
    is single-language, so under --lang-window each window is aligned with its
    own detected language.

Language handling:
  * --lang-window 0 (default): one detected language for the whole file (coerces
    minority languages — e.g. Italian rendered as Spanish).
  * --lang-window >0 (e.g. 30): detect language per window so Italian sections get
    <|it|>. Each output chunk is tagged, e.g. "[0120s - 0130s] (it): ...".
  * --passes: BEST for code-switching. 4-pass merge (faster-whisper) — an auto
    pass plus forced it/es/en, picking the highest-word-probability language per
    segment. Overrides the per-window logic; --diarize still applies on top.
    (Needs a GPU to be practical: 4x the transcription.)

Usage:
  python transcribe_wav.py --wav rec.wav --segments rec.csv \
      [--backend faster-whisper|whisperx] [--lang-window 30 | --passes] \
      [--device cuda] [--diarize --hf-token hf_xxx]

GPU: --device cuda (float16). faster-whisper needs ctranslate2+CUDA+cuDNN;
whisperx additionally needs `pip install whisperx` (torch, pyannote). Diarization
needs a HuggingFace token with the pyannote speaker-diarization model accepted.
"""

import os
import sys
import argparse
import numpy as np
from faster_whisper import WhisperModel
from faster_whisper.audio import decode_audio
from transcript_format import write_transcript, write_segments

SR = 16000


# --------------------------- faster-whisper backend ---------------------------
def _fw(model, audio, language):
    segs, info = model.transcribe(audio, task="transcribe", language=language,
                                  vad_filter=True, beam_size=5)
    return list(segs), info


def fw_collect(model, audio, lang_window):
    """Returns [(start, end, text, lang, speaker=None)]."""
    if lang_window and lang_window > 0:
        items, wsamp = [], int(lang_window * SR)
        nwin = int(np.ceil(len(audio) / wsamp))
        for w in range(nwin):
            a, b = w * wsamp, min(len(audio), (w + 1) * wsamp)
            chunk = np.ascontiguousarray(audio[a:b])
            if np.abs(chunk).max() < 1e-3:
                continue
            segs, info = _fw(model, chunk, None)
            t0 = a / SR
            for s in segs:
                items.append((s.start + t0, s.end + t0, s.text.strip(), info.language, None))
            sys.stderr.write(f"\r  window {w + 1}/{nwin} [{t0:>5.0f}s] lang={info.language}   ")
            sys.stderr.flush()
        sys.stderr.write("\n")
        return items
    segs, info = _fw(model, audio, None)
    print(f"Detected dominant language: {info.language} (p={info.language_probability:.2f})")
    return [(s.start, s.end, s.text.strip(), info.language, None) for s in segs]


# ------------------------------- whisperx backend -----------------------------
def wx_collect(model_name, audio, device, compute_type, lang_window, diarize, hf_token,
               chunk_size=30):
    import whisperx
    asr = whisperx.load_model(model_name, device, compute_type=compute_type)
    align_cache = {}

    def align(segs, lang):
        if not segs:
            return []
        try:
            if lang not in align_cache:
                align_cache[lang] = whisperx.load_align_model(language_code=lang, device=device)
            am, meta = align_cache[lang]
            return whisperx.align(segs, am, meta, audio, device,
                                  return_char_alignments=False)["segments"]
        except Exception as e:                       # no align model for this lang -> raw ts
            sys.stderr.write(f"\n  (align skipped for '{lang}': {e})\n")
            return segs

    items = []
    if lang_window and lang_window > 0:
        wsamp = int(lang_window * SR)
        nwin = int(np.ceil(len(audio) / wsamp))
        for w in range(nwin):
            a, b = w * wsamp, min(len(audio), (w + 1) * wsamp)
            chunk = np.ascontiguousarray(audio[a:b])
            if np.abs(chunk).max() < 1e-3:
                continue
            r = asr.transcribe(chunk, batch_size=16, language=None, chunk_size=chunk_size)
            lang, t0 = r["language"], a / SR
            for s in align(r["segments"], lang):
                items.append((s["start"] + t0, s["end"] + t0, s.get("text", "").strip(), lang, None))
            sys.stderr.write(f"\r  window {w + 1}/{nwin} [{t0:>5.0f}s] lang={lang}   ")
            sys.stderr.flush()
        sys.stderr.write("\n")
    else:
        r = asr.transcribe(audio, batch_size=16, language=None, chunk_size=chunk_size)
        lang = r["language"]
        print(f"Detected dominant language: {lang}")
        for s in align(r["segments"], lang):
            items.append((s["start"], s["end"], s.get("text", "").strip(), lang, None))

    if diarize:
        items = _wx_diarize(audio, device, hf_token, items)
    return items


def _wx_diarize(audio, device, hf_token, items):
    """Assign a speaker to each segment by max temporal overlap with diarization."""
    try:
        try:
            from whisperx.diarize import DiarizationPipeline
        except Exception:
            from whisperx import DiarizationPipeline
        dia = DiarizationPipeline(use_auth_token=hf_token, device=device)
        diar = dia(audio)                            # pandas DataFrame: start,end,speaker
        rows = list(diar.itertuples(index=False))
        out = []
        for st, en, text, lang, _sp in items:
            best, best_ov = None, 0.0
            for r in rows:
                ov = max(0.0, min(en, r.end) - max(st, r.start))
                if ov > best_ov:
                    best_ov, best = ov, r.speaker
            out.append((st, en, text, lang, best))
        n_spk = len({r.speaker for r in rows})
        print(f"diarization: {n_spk} speakers")
        return out
    except Exception as e:
        print(f"WARNING: diarization failed ({e}); continuing without speaker labels")
        return items


# ------------------------------ 4-pass merge (--passes) -----------------------
def passes_collect(model_name, audio, device, compute_type, langs=("it", "es", "en"),
                   vad_threshold=0.5):
    """Code-switch-aware 4-pass merge (faster-whisper) — the collaborator's
    passes.sh + merge_transcript.py logic. Runs an AUTO pass (the time spine)
    plus one FORCED pass per candidate language, all with word timestamps, then
    for each spine segment picks the forced pass whose Whisper word-probability
    is highest (the language that actually 'fits'). Falls back to auto.

    Uses faster-whisper on purpose: the merge needs the Whisper decoder's
    per-word probability, which whisperx's wav2vec alignment score does NOT give.

    Silero VAD is kept (it gives the finer segments that whisperx lacks), but its
    threshold is exposed: lower vad_threshold (e.g. 0.3) detects quieter/onset
    speech -> more sensitive, while still trimming true silence (so no full
    hallucination). Returns [(start, end, text, lang, speaker=None)]."""
    model = WhisperModel(model_name, device=device, compute_type=compute_type)

    def run(language):
        segs, _info = model.transcribe(audio, task="transcribe", language=language,
                                       word_timestamps=True, vad_filter=True,
                                       vad_parameters=dict(threshold=vad_threshold),
                                       beam_size=5)
        segs = list(segs)
        words = [(w.start, w.end, w.word, w.probability)
                 for s in segs for w in (s.words or [])]
        return segs, words

    print(f"4-pass merge: auto + forced {list(langs)}")
    auto_segs, auto_words = run(None)
    spine = [(s.start, s.end) for s in auto_segs]
    print(f"  pass auto: {len(auto_words)} words ({len(spine)} spine segments)")
    forced = {}
    for L in langs:
        _, forced[L] = run(L)
        print(f"  pass {L}: {len(forced[L])} words")

    # Partition words by spine-segment START time: each word lands in exactly one
    # segment ([this_start, next_start)), so a boundary word is never duplicated
    # across consecutive segments. Gaps after a segment are absorbed into it.
    starts = [s for s, _ in spine] + [float("inf")]

    def in_range(words, lo, hi):
        return [w for w in words if lo <= w[0] < hi]

    items = []
    for i in range(len(spine)):
        lo, hi = starts[i], starts[i + 1]
        best, bestconf, bestws = None, -1.0, None
        for L in langs:
            ws = in_range(forced[L], lo, hi)
            if not ws:
                continue
            conf = float(np.mean([w[3] for w in ws]))
            if conf > bestconf:
                bestconf, best, bestws = conf, L, ws
        if best is None:                                  # fallback to the auto pass
            bestws = in_range(auto_words, lo, hi)
            if not bestws:
                continue
            best = "auto"
        text = "".join(w[2] for w in bestws).strip()
        if text:
            items.append((bestws[0][0], bestws[-1][1], text, best, None))
    return items


# Output formatting lives in transcript_format.write_transcript (shared canonical
# format across all transcript generators).


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--output", help="fixed-interval multi-line .txt (legacy pipeline format)")
    ap.add_argument("--segments", help="NATIVE variable-length segments as CSV "
                    "(seg_idx,t_start_s,t_end_s,lang,speaker,transcript) — recommended")
    ap.add_argument("--backend", default="faster-whisper",
                    choices=["faster-whisper", "whisperx"])
    ap.add_argument("--passes", action="store_true",
                    help="4-pass code-switch merge (faster-whisper auto + forced it/es/en, "
                         "pick highest word-prob per segment). Overrides --backend/--lang-window "
                         "for transcription; --diarize still applies on top.")
    ap.add_argument("--vad-threshold", type=float, default=0.5,
                    help="--passes only: Silero VAD speech threshold (default 0.5). Lower (e.g. "
                         "0.3) captures quieter onsets / more speech while keeping fine segments.")
    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--lang-window", type=float, default=0.0,
                    help="0 = one language for whole file; >0 (e.g. 30) = detect language per window")
    ap.add_argument("--chunk-size", type=int, default=30,
                    help="whisperx only: max VAD chunk seconds before transcription (default 30). "
                         "Lower (e.g. 6-10) -> smaller segments (slightly less context).")
    ap.add_argument("--diarize", action="store_true",
                    help="whisperx only: label speakers (needs --hf-token + pyannote)")
    ap.add_argument("--hf-token", default=os.environ.get("HF_TOKEN"),
                    help="HuggingFace token for the pyannote diarization model")
    ap.add_argument("--no-tag-lang", action="store_true", help="omit the per-chunk (lang) tag")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"])
    ap.add_argument("--compute-type", default=None,
                    help="ctranslate2 compute type; default float16 on cuda, int8 on cpu")
    args = ap.parse_args()

    if not os.path.exists(args.wav):
        print(f"ERROR: WAV not found: {args.wav}")
        sys.exit(1)
    if not args.output and not args.segments:
        print("ERROR: provide --segments (native, recommended) and/or --output (binned)")
        sys.exit(1)
    if args.diarize and args.backend != "whisperx" and not args.passes:
        print("ERROR: --diarize requires --backend whisperx (or --passes)")
        sys.exit(1)

    device = args.device
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    compute_type = args.compute_type or ("float16" if device == "cuda" else "int8")

    audio = decode_audio(args.wav, sampling_rate=SR)
    mode = "passes" if args.passes else args.backend
    print(f"{os.path.basename(args.wav)}: {len(audio) / SR:.1f}s | mode={mode} | "
          f"{device}/{compute_type} | lang-window={args.lang_window:.0f}")

    if args.passes:
        items = passes_collect(args.model, audio, device, compute_type,
                               vad_threshold=args.vad_threshold)
        if args.diarize:
            items = _wx_diarize(audio, device, args.hf_token, items)
    elif args.backend == "whisperx":
        items = wx_collect(args.model, audio, device, compute_type,
                           args.lang_window, args.diarize, args.hf_token,
                           chunk_size=args.chunk_size)
    else:
        model = WhisperModel(args.model, device=device, compute_type=compute_type)
        items = fw_collect(model, audio, args.lang_window)

    by_lang = {}
    for s, e, _t, lang, _sp in items:
        by_lang[lang] = by_lang.get(lang, 0.0) + (e - s)
    if by_lang:
        total = sum(by_lang.values())
        print("language share (by speech seconds):")
        for lang, dur in sorted(by_lang.items(), key=lambda kv: -kv[1]):
            print(f"  {lang}: {dur:7.1f}s  ({100 * dur / total:4.1f}%)")

    if args.segments:
        m = write_segments(items, args.segments)
        print(f"Native segments saved to: {args.segments}  ({m} segments)")
    if args.output:
        n = write_transcript(items, args.output, args.interval, tag_lang=not args.no_tag_lang)
        print(f"Binned transcript saved to: {args.output}  ({n} chunks)")


if __name__ == "__main__":
    main()
