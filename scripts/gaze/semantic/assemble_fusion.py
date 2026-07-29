#!/usr/bin/env python3
"""
Compose per-segment enrichments into one master fusion table, joined by seg_idx.

The base fusion (build_fusion) is the spine; each --add CSV contributes only the
columns the master doesn't already have — so it works whether the add is a full
augmented copy (..._snap.csv, ..._emo.csv) or a thin seg_idx sidecar
(..._discourse.csv). Rows match on --key (default seg_idx); base rows with no
match get blanks; column order is base-first, then new columns in --add order.

This is the integration point that keeps every enrichment (discourse, snapshot,
prosody/emotion, ...) landing in ONE table rather than forking separate copies.

Usage:
  python assemble_fusion.py --base CaronaAdine1_fusion_m8.csv \
      --add CaronaAdine1_fusion_m8_snap.csv \
      --add CaronaAdine1_fusion_m8_emo.csv \
      --add CaronaAdine1_forJavi_m8_discourse.csv \
      --out CaronaAdine1_fusion_m8_enriched.csv
"""
import csv
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="base fusion table (the spine)")
    ap.add_argument("--add", action="append", default=[], required=True,
                    help="enrichment CSV to merge (repeatable)")
    ap.add_argument("--key", default="seg_idx")
    ap.add_argument("--out", help="default: <base>_enriched.csv")
    args = ap.parse_args()

    base_rows = list(csv.DictReader(open(args.base)))
    if not base_rows:
        raise SystemExit(f"empty base: {args.base}")
    master_cols = list(base_rows[0].keys())
    master = {r[args.key]: dict(r) for r in base_rows}
    print(f"base: {len(base_rows)} rows, {len(master_cols)} columns")

    for path in args.add:
        add_rows = list(csv.DictReader(open(path)))
        if not add_rows:
            print(f"  {path}: empty (skipped)")
            continue
        amap = {r[args.key]: r for r in add_rows}
        new_cols = [c for c in add_rows[0].keys() if c not in master_cols and c != args.key]
        if not new_cols:
            print(f"  {path}: no new columns (skipped)")
            continue
        matched = 0
        for k, row in master.items():
            src = amap.get(k)
            for c in new_cols:
                row[c] = src.get(c, "") if src else ""
            if src:
                matched += 1
        master_cols += new_cols
        print(f"  {path}: +{len(new_cols)} cols {new_cols}  ({matched}/{len(master)} rows matched)")

    out = args.out or (args.base[:-4] + "_enriched.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=master_cols)
        w.writeheader()
        for r in base_rows:                       # preserve base row order
            w.writerow({c: master[r[args.key]].get(c, "") for c in master_cols})
    print(f"wrote {out}  ({len(base_rows)} rows, {len(master_cols)} columns)")


if __name__ == "__main__":
    main()
