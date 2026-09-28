"""Orchestrates Stage 2 (research + Claude analysis) with per-candidate
checkpointing, then assembles the final lead/evidence rows for xlsx_writer.

Checkpointing is per-candidate (not just per-query cache) because Stage 2
calls the Claude API, which costs money independently of search credits —
re-running the pipeline must never re-pay for a company already analyzed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import List

import requests
from tqdm import tqdm

from . import config, dedupe, scoring
from .claude_analysis import analyze_bundle
from .models import Stage1Candidate
from .research import research_candidate
from .search_client import QuotaExhausted


def _checkpoint_path(row_id: str) -> Path:
    d = config.CHECKPOINT_DIR / "stage2"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{row_id}.json"


def run_stage2_pipeline(
    candidates: List[Stage1Candidate],
    max_candidates: int | None = None,
    sleep_between: float = 0.0,
) -> List[dict]:
    """Processes up to `max_candidates` NOT-YET-CHECKPOINTED candidates from
    the ranked list (skipping already-done ones first, not just slicing the
    front of the list — otherwise a repeated `--max-candidates 50` run would
    always re-hit the same first 50 and never advance). Returns records for
    only the candidates touched in this call; run_export.py separately reads
    every checkpoint on disk regardless of what any single run processed."""
    max_candidates = max_candidates or config.MAX_CANDIDATES_STAGE2
    pending = [c for c in candidates if not _checkpoint_path(c.row_id).exists()]
    to_process = pending[:max_candidates]

    results = []
    stopped_early = False
    for candidate in tqdm(to_process, desc="Stage 2 research + analysis"):
        cp_path = _checkpoint_path(candidate.row_id)
        if cp_path.exists():
            with open(cp_path, "r", encoding="utf-8") as f:
                results.append(json.load(f))
            continue

        try:
            bundle = research_candidate(candidate)
            classification = analyze_bundle(bundle)
        except QuotaExhausted as e:
            # All configured search providers are out of quota for this
            # billing period. Stop cleanly here rather than crashing — every
            # candidate processed so far this run is already checkpointed,
            # so nothing is lost, and run_export.py can still run on what
            # exists. Whoever's running this should check their provider
            # dashboard(s) for the actual reset date before retrying.
            print(f"\n[stage2] Search quota exhausted, stopping this run early: {e}")
            print(f"[stage2] {len(results)} candidate(s) completed this run before hitting the limit.")
            stopped_early = True
            break
        except requests.exceptions.RequestException as e:
            # Retries inside search_client are already exhausted by the time
            # this surfaces — a real/prolonged network issue. Stop cleanly
            # rather than crashing the whole batch on one candidate.
            print(f"\n[stage2] Persistent network error, stopping this run early: {e}")
            print(f"[stage2] {len(results)} candidate(s) completed this run before hitting the error.")
            stopped_early = True
            break

        record = {
            "candidate": candidate.__dict__,
            "classification": classification,
            "date_researched": time.strftime("%Y-%m-%d"),
        }
        with open(cp_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, default=str)
        results.append(record)

        if sleep_between:
            time.sleep(sleep_between)

    if stopped_early:
        print("[stage2] Run ended early due to quota, not an error — exiting normally so any chained export step still runs.")

    return results


def build_lead_dict(record: dict) -> dict:
    candidate = record["candidate"]
    c = record["classification"]
    score = scoring.compute_score(c)
    priority = scoring.compute_priority(c, score)
    confidence = scoring.derive_confidence(c)

    evidence_urls = [e.get("source_url", "") for e in (c.get("evidence") or []) if e.get("source_url")]

    return {
        "row_id": candidate["row_id"],
        "agent_name": candidate["name"],
        "company_name": c.get("company_name") or "",
        "agent_type": c.get("agent_type", "UNCLEAR"),
        "website": c.get("website") or "",
        "agent_url": c.get("agent_url") or "",
        "decision_maker_name": c.get("decision_maker_name") or "",
        "decision_maker_title": c.get("decision_maker_title") or "",
        "decision_maker_email": c.get("decision_maker_email") or "",
        "decision_maker_linkedin": c.get("decision_maker_linkedin") or "",
        "decision_maker_x": c.get("decision_maker_x") or "",
        "fundraising_signal": c.get("fundraising_signal") or "",
        "signal_date": c.get("signal_date") or "",
        "funding_stage": c.get("funding_stage") or "",
        "funding_amount": c.get("funding_amount") or "",
        "why_now": c.get("why_now") or "",
        "enterprise_signal": c.get("enterprise_signal", "UNKNOWN"),
        "verification_gap": c.get("verification_gap", "LARGE_GAP"),
        "why_agentvet_relevant": c.get("why_agentvet_relevant") or "",
        "outreach_angle": c.get("outreach_angle") or "",
        "score": score,
        "priority": priority,
        "confidence": confidence,
        "evidence_urls": evidence_urls[:3],
        "date_researched": record.get("date_researched", ""),
    }


def build_evidence_rows(record: dict) -> list[dict]:
    candidate = record["candidate"]
    c = record["classification"]
    rows = []
    for e in c.get("evidence") or []:
        rows.append({
            "agent_name": candidate["name"],
            "company_name": c.get("company_name") or "",
            "agent_type": c.get("agent_type", "UNCLEAR"),
            "signal_type": e.get("signal_type", ""),
            "claim": e.get("claim", ""),
            "evidence": e.get("evidence", ""),
            "source": e.get("source_url", ""),
            "source_url": e.get("source_url", ""),
            "source_date": e.get("source_date") or "",
            "confidence": e.get("confidence", ""),
            "research_notes": c.get("research_notes") or "",
            "date_researched": record.get("date_researched", ""),
        })
    return rows


def assemble_outputs(records: List[dict]) -> tuple[list[dict], list[dict]]:
    leads = [build_lead_dict(r) for r in records]
    leads = dedupe.dedupe_leads(leads)

    evidence_rows: list[dict] = []
    for r in records:
        evidence_rows.extend(build_evidence_rows(r))

    return leads, evidence_rows
