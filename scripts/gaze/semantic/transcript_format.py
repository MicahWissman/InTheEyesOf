#!/usr/bin/env python3
"""
Canonical transcript chunk format — the SINGLE source of truth shared by every
transcript generator (transcribe_wav.py, vrs_to_transcript.py). Keeping the
formatting here prevents the format from drifting between scripts.

Emits MULTI-LINE chunks that spatial_transcript_summarizer.load_transcript()
parses (marker line, then content on its own line):

    [0120s - 0130s] (it):
    spoken text on its own line
    [0130s - 0140s]:
    (silence)

The optional "(lang[, SPEAKER])" tag lives on the MARKER line, which the parser
ignores — so it's visible for human review but never leaks into the transcript
text, the LLM synthesis, or the embeddings.
"""

import os


def _ts(idx, interval):
    return f"[{idx * interval:04.0f}s - {(idx + 1) * interval:04.0f}s]"


def segments_to_lines(items, interval=10.0, tag_lang=True):
    """items: iterable of (start, end, text, lang_or_None, speaker_or_None).
    Returns canonical multi-line output as a list of strings."""
    items = sorted(items, key=lambda x: x[0])
    lines = []
    cur_idx, texts, langs, spks = 0, [], [], []

    def flush(idx):
        if texts:
            parts = []
            lang_vals = [l for l in langs if l]
            if tag_lang and lang_vals:
                parts.append(max(set(lang_vals), key=lang_vals.count))
            spk_vals = [s for s in spks if s]
            if spk_vals:
                parts.append(max(set(spk_vals), key=spk_vals.count))
            tag = f" ({', '.join(parts)})" if parts else ""
            lines.append(f"{_ts(idx, interval)}{tag}:")
            lines.append(" ".join(t for t in texts if t) or "(silence)")
        else:
            lines.append(f"{_ts(idx, interval)}:")
            lines.append("(silence)")

    if not items:
        return []
    for start, _end, text, lang, spk in items:
        idx = int(start // interval)
        if idx > cur_idx:
            flush(cur_idx)
            for i in range(cur_idx + 1, idx):
                lines.append(f"{_ts(i, interval)}:")
                lines.append("(silence)")
            cur_idx, texts, langs, spks = idx, [text], [lang], [spk]
        else:
            texts.append(text); langs.append(lang); spks.append(spk)
    flush(cur_idx)
    return lines


def write_transcript(items, output_path, interval=10.0, tag_lang=True):
    """Write items to a canonical multi-line transcript (fixed `interval` bins).
    Returns chunk count."""
    lines = segments_to_lines(items, interval, tag_lang)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return sum(1 for l in lines if l.startswith("["))


def write_segments(items, output_path):
    """Write NATIVE variable-length segments (no binning) as CSV, mirroring the
    fusion.csv schema so it joins cleanly with gaze/IMU/etc:
        seg_idx, t_start_s, t_end_s, lang, speaker, transcript
    Preserves real segment boundaries for sub-second gaze-speech alignment."""
    import csv
    items = sorted(items, key=lambda x: x[0])
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with open(output_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["seg_idx", "t_start_s", "t_end_s", "lang", "speaker", "transcript"])
        for i, (s, e, text, lang, spk) in enumerate(items):
            w.writerow([i, round(float(s), 3), round(float(e), 3), lang or "", spk or "", text])
    return len(items)
