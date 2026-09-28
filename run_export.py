#!/usr/bin/env python
"""Assemble every Stage 2 checkpoint into the final 3-tab XLSX output.

Reads all data/checkpoints/stage2/*.json (every company processed so far —
you don't need to have finished the whole candidate list first) and writes
data/output/agentvet_leads_<date>.xlsx with the exact tab structure from
AgentVet_Lead_Intelligence_Structure.pdf:
  1. HIGH PRIORITY
  2. ALL QUALIFIED LEADS
  3. RESEARCH - EVIDENCE

Also pushes to a live Google Sheet when --gsheet is passed (or GOOGLE_SHEET_ID
is set in .env) using the same 3-tab structure, via src/sheets_writer.py.

Usage:
    python run_export.py
    python run_export.py --output data/output/my_leads.xlsx
    python run_export.py --gsheet                  # also push to Google Sheets
    python run_export.py --gsheet --no-xlsx         # Google Sheets only
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from src import config
from src.pipeline import assemble_outputs
from src.xlsx_writer import write_workbook


def load_all_checkpoints() -> list[dict]:
    d = config.CHECKPOINT_DIR / "stage2"
    if not d.exists():
        return []
    records = []
    for p in d.glob("*.json"):
        with open(p, "r", encoding="utf-8") as f:
            records.append(json.load(f))
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_name = f"agentvet_leads_{time.strftime('%Y-%m-%d')}.xlsx"
    parser.add_argument("--output", type=Path, default=config.OUTPUT_DIR / default_name)
    parser.add_argument("--gsheet", action="store_true", help="Also push to the Google Sheet configured in .env")
    parser.add_argument("--no-xlsx", action="store_true", help="Skip writing the local .xlsx file")
    args = parser.parse_args()

    records = load_all_checkpoints()
    print(f"Loaded {len(records)} researched companies from checkpoints.")
    if not records:
        print("No Stage 2 checkpoints found yet. Run run_stage1.py then run_stage2.py first.")
        return

    leads, evidence_rows = assemble_outputs(records)
    high = sum(1 for l in leads if l["priority"] == "HIGH")
    medium = sum(1 for l in leads if l["priority"] == "MEDIUM")
    low = sum(1 for l in leads if l["priority"] == "LOW")
    rejected = sum(1 for l in leads if l["priority"] == "REJECT")
    print(f"After dedupe: {len(leads)} companies -> HIGH={high} MEDIUM={medium} LOW={low} REJECT={rejected}")
    print(f"Evidence rows: {len(evidence_rows)}")

    if not args.no_xlsx:
        write_workbook(leads, evidence_rows, args.output)
        print(f"Wrote {args.output}")

    if args.gsheet or config.GOOGLE_SHEET_ID:
        from src.sheets_writer import write_to_google_sheet
        url = write_to_google_sheet(leads, evidence_rows)
        print(f"Pushed to Google Sheet: {url}")


if __name__ == "__main__":
    main()
