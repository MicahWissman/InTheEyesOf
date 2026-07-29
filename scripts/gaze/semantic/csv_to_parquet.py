#!/usr/bin/env python3
"""
Convert an MPS CSV to a Parquet sibling (<name>.parquet) for fast reuse.

The summarizer's loaders (`_read_csv_fast`) auto-detect and prefer a `.parquet`
sibling, so a recording's huge `closed_loop_trajectory.csv` is parsed once here
and read ~10-20x faster (columnar + compressed) on every subsequent pipeline run.
Keep the original .csv next to it (the loader resolves the path from the .csv).

Usage:
  python csv_to_parquet.py /path/closed_loop_trajectory.csv
  python csv_to_parquet.py rec.csv --columns tracking_timestamp_us,tx_world_device,...
"""
import os
import argparse
import pyarrow.csv as pacsv
import pyarrow.parquet as pq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--columns", help="comma-separated subset to keep (default: all)")
    ap.add_argument("--out", help="output path (default: <csv with .parquet>)")
    ap.add_argument("--compression", default="zstd")
    args = ap.parse_args()

    cols = args.columns.split(",") if args.columns else None
    opts = pacsv.ConvertOptions(include_columns=cols) if cols else None
    table = pacsv.read_csv(args.csv, convert_options=opts)

    out = args.out or (args.csv[:-4] + ".parquet" if args.csv.endswith(".csv") else args.csv + ".parquet")
    pq.write_table(table, out, compression=args.compression)
    print(f"wrote {out}  ({table.num_rows} rows, {table.num_columns} cols, "
          f"{os.path.getsize(out) / 1e6:.0f} MB; csv was {os.path.getsize(args.csv) / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
