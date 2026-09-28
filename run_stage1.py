#!/usr/bin/env python
"""Stage 1: filter the 3,000+ agent database down to a candidate shortlist.

Usage:
    python run_stage1.py data/input/agents.csv
    python run_stage1.py data/input/agents.csv --top-n 400 --use-search-fallback
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src import config
from src.ingest import load_input
from src.stage1_filter import run_stage1, save_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path, help="Path to the existing agent database (.csv or .xlsx)")
    parser.add_argument("--top-n", type=int, default=500, help="Max candidates to pass to Stage 2")
    parser.add_argument("--min-score", type=int, default=1, help="Minimum keyword signal score to keep a row at all")
    parser.add_argument("--no-homepage-fetch", action="store_true", help="Skip fetching homepage text even if a URL column exists")
    parser.add_argument("--use-search-fallback", action="store_true", help="Spend 1 cached search query per row lacking a website column (capped by MAX_SEARCH_QUERIES_PER_RUN)")
    args = parser.parse_args()

    print(f"Loading input database from {args.input_path} (read-only)...")
    rows = load_input(args.input_path)
    print(f"Loaded {len(rows)} rows.")

    candidates = run_stage1(
        rows,
        top_n=args.top_n,
        min_score=args.min_score,
        use_homepage_fetch=not args.no_homepage_fetch,
        use_search_fallback=args.use_search_fallback,
    )
    print(f"Stage 1 selected {len(candidates)} candidates (from {len(rows)} rows).")

    out_path = config.CHECKPOINT_DIR / "stage1_candidates.json"
    save_candidates(candidates, out_path)
    print(f"Saved candidate shortlist to {out_path}")
    print("Review this file, then run: python run_stage2.py")


if __name__ == "__main__":
    main()
