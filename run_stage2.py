#!/usr/bin/env python
"""Stage 2: deep research + Claude analysis on the Stage 1 candidate shortlist.

Resumable: each candidate is checkpointed to data/checkpoints/stage2/<row_id>.json
as soon as it's processed, so interrupting and re-running never re-pays for
work already done. Every search query is separately cached (data/cache/), so
even a deleted checkpoint won't re-spend search credits on the same query.

Usage:
    python run_stage2.py
    python run_stage2.py --max-candidates 50   # process a small batch first
"""
from __future__ import annotations

import argparse

from src import config
from src.pipeline import run_stage2_pipeline
from src.stage1_filter import load_candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates-file", default=None, help="Defaults to data/checkpoints/stage1_candidates.json")
    parser.add_argument("--max-candidates", type=int, default=None, help="Overrides MAX_CANDIDATES_STAGE2 from .env")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between candidates (extra rate-limit safety)")
    args = parser.parse_args()

    candidates_path = args.candidates_file or (config.CHECKPOINT_DIR / "stage1_candidates.json")
    print(f"Loading Stage 1 candidates from {candidates_path}...")
    candidates = load_candidates(candidates_path)
    print(f"{len(candidates)} candidates loaded.")

    results = run_stage2_pipeline(candidates, max_candidates=args.max_candidates, sleep_between=args.sleep)
    print(f"Stage 2 complete: {len(results)} candidates processed (including any resumed from checkpoint).")
    print("Run: python run_export.py")


if __name__ == "__main__":
    main()
