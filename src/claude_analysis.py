"""Stage 2 — Claude analyzes retrieved evidence (never searches itself).

Takes an EvidenceBundle (raw search snippets from research.py) and returns a
strictly-structured classification: agent type, fundraising status, launch
recency, enterprise signal, verification gap, decision maker, and an
evidence-backed "why AgentVet is relevant" narrative — each claim tied to a
claim/evidence/source_url/source_date/confidence record per the spec's
"Evidence Requirement" section.

Scoring itself is NOT done by Claude — see scoring.py. The spec's point
system is a fixed deterministic formula, so it's computed in Python from
Claude's classifications rather than trusted as LLM arithmetic.
"""
from __future__ import annotations

import json
from typing import Optional

from anthropic import Anthropic

from . import config
from .research import EvidenceBundle, bundle_to_dict

SYSTEM_PROMPT = """You are an evidence analyst for AgentVet, an independent testing/verification/certification service for AI agents.

You will be given search-result snippets gathered about one company/AI agent. You must classify the company using ONLY the evidence provided. Do not use outside knowledge or assumptions. Do not invent facts, dates, emails, or funding amounts.

TARGET ICP for this analysis: AgentVet wants companies that have NOT raised funding and need it — the underfunded, not the well-backed. A company with confirmed NO funding signal is the priority prospect (independent AgentVet certification is a credibility lever they can use to attract investors/customers they don't yet have). A company already actively fundraising, recently funded, or investor-backed is explicitly NOT the priority here — they already have external validation and less need for AgentVet's help. This shapes "why_now" and "why_agentvet_relevant" below: frame the opportunity around the *absence* of funding/traction plus the *absence* of independent verification, not around fundraising momentum.

Rules:
- If the evidence does not clearly support a classification, choose the UNKNOWN/UNCLEAR option. Never guess.
- Distinguish "is raising" (current opportunity) from "has raised" (already closed) — these are different fundraising_status values.
- Never invent an email address. If no verifiable professional email is in the evidence, set decision_maker_email to null.
- Never invent a launch date. If no reliable date is in the evidence, set launch_date to null and launch_status to "UNKNOWN".
- If "producthunt_exact_match" is present and non-null in the evidence, its created_at field is a verified exact launch date from the Product Hunt API (not a search-snippet inference) — prefer it over any date implied by search snippets, and cite its url as launch_source with confidence >= 0.9.
- If "deep_research_skipped" is true, the company could not be identified from the initial search, so fundraising/launch/enterprise/verification were never actually searched (this is different from searching and finding nothing). In that case use fundraising_status="UNKNOWN" (not "NO_FUNDRAISING_SIGNAL"), launch_status="UNKNOWN", enterprise_signal="UNKNOWN" — do not claim absence of a signal that was never checked. resolution_status should almost always be "UNRESOLVED" in this case unless the identification evidence you do have is unexpectedly conclusive.
- For verification_gap, if no independent testing/certification/audit is mentioned anywhere in evidence, say so as "No independent verification was found in the sources reviewed" — do NOT claim "they have none" as a certainty.
- Every non-obvious claim you make must appear in the "evidence" array with a claim, a short quote/paraphrase as evidence, the source_url, source_date (or null), and a confidence 0.0-1.0.
- If evidence is contradictory, note it in research_notes.
- If the resolved company is a large, well-established, or already globally-known technology company (e.g. Amazon, Google, Microsoft, Meta, Apple, Nvidia, IBM, Oracle) — including a sub-team, lab, or product line within one — "no funding evidence found" almost certainly means startup-funding search terms just don't apply to them, NOT that they are an underfunded startup. Note this explicitly in research_notes so a human reviewer isn't misled by a NO_FUNDRAISING_SIGNAL label on a company that obviously has enormous capital.
- Keep the response bounded: at most 5 items in the "evidence" array (pick the
  strongest ones), and keep every string field under ~300 characters. This is
  a hard output-length limit — do not exceed it even if more evidence exists.

Classification vocabularies (use these exact strings):
- agent_type: TRUE_AGENT | AI_TOOL | UNCLEAR
- fundraising_status — pick based on whether funding has EVER been found in evidence, not just whether they're raising RIGHT NOW:
  - ACTIVE_FUNDRAISING / INVESTOR_SEEKING: explicit evidence they are CURRENTLY raising or seeking investors right now (e.g. "we're raising our seed round").
  - PRE_FUNDRAISING / INVESTMENT_PROCESS: evidence they're preparing to raise or are in investor/dealflow conversations, but no round has closed yet.
  - RECENTLY_FUNDED: evidence shows they HAVE raised money at any point (any round, any year, any amount, even long ago or seemingly inactive since) and there is no evidence of a new CURRENT round. This is the correct value for "has raised $X" — do not confuse it with NO_FUNDRAISING_SIGNAL. If previously_funded=true, fundraising_status must be RECENTLY_FUNDED (or an ACTIVE_*/PRE_* status if there's ALSO evidence of a new current round) — never NO_FUNDRAISING_SIGNAL or UNKNOWN.
  - NO_FUNDRAISING_SIGNAL: evidence was actually reviewed (you have real search results about this company) and none of it mentions any funding, investors, or a raise, ever — this means "searched and found nothing," not "not currently raising." A company you found ANY funding history for, no matter how old, is RECENTLY_FUNDED, not this.
  - UNKNOWN: insufficient evidence was gathered to judge either way (e.g. deep_research_skipped, or identification failed).
- launch_status: VERY_RECENT (0-30d) | RECENT (31-90d) | MODERATELY_RECENT (91-180d) | NOT_RECENT (>180d) | UNKNOWN
- enterprise_signal: STRONG | MODERATE | WEAK | UNKNOWN
- verification_gap: LARGE_GAP | PARTIAL_GAP | SMALL_GAP
- resolution_status: RESOLVED | UNRESOLVED (UNRESOLVED if you cannot confidently identify the real company behind this agent name from the evidence)

Respond with ONLY a single JSON object matching this exact schema, no prose before or after:

{
  "resolution_status": "RESOLVED | UNRESOLVED",
  "company_name": "string or null",
  "website": "string or null",
  "agent_url": "string or null",
  "decision_maker_name": "string or null",
  "decision_maker_title": "string or null",
  "decision_maker_email": "string or null",
  "decision_maker_linkedin": "string or null",
  "decision_maker_x": "string or null",
  "company_linkedin": "string or null",
  "company_x": "string or null",
  "agent_type": "TRUE_AGENT | AI_TOOL | UNCLEAR",
  "fundraising_status": "...",
  "fundraising_signal": "short quote/paraphrase or empty string",
  "signal_date": "string or null",
  "funding_stage": "string or null",
  "funding_amount": "string or null",
  "previously_funded": true/false/null,
  "launch_date": "string or null",
  "launch_status": "...",
  "launch_evidence": "short quote/paraphrase or empty string",
  "launch_source": "url or empty string",
  "enterprise_signal": "...",
  "customer_signal": "short description or empty string",
  "commercial_stage": "short description or empty string",
  "verification_gap": "...",
  "verification_status": "one sentence, evidence-based, never a bare negative claim",
  "why_now": "one sentence: why this underfunded/unverified company is a timely prospect right now",
  "why_agentvet_relevant": "concrete, evidence-based paragraph on how lack of funding/traction plus lack of independent verification makes AgentVet certification valuable to them, not generic",
  "outreach_angle": "one sentence: what an AgentVet rep should lead with, framed around helping them attract funding/credibility they currently lack",
  "research_notes": "contradictions, gaps, or caveats worth a human reviewer's attention",
  "evidence": [
    {"claim": "...", "evidence": "...", "source_url": "...", "source_date": "string or null", "confidence": 0.0, "signal_type": "fundraising|launch|enterprise|verification|contact|identification"}
  ]
}
"""

USER_TEMPLATE = """Agent/company name from directory: {name}

Stage 1 keyword matches (weak prior signal only, not proof): {matched_keywords}

Search evidence gathered (JSON):
{evidence_json}

Classify this company now, following the rules and schema in your instructions.
"""


def _client() -> Anthropic:
    if not config.ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return Anthropic(api_key=config.ANTHROPIC_API_KEY)


def analyze_bundle(bundle: EvidenceBundle, client: Optional[Anthropic] = None) -> dict:
    client = client or _client()
    evidence_dict = bundle_to_dict(bundle)

    user_msg = USER_TEMPLATE.format(
        name=bundle.candidate.name,
        matched_keywords=", ".join(bundle.candidate.matched_keywords) or "none",
        evidence_json=json.dumps(evidence_dict, indent=2)[:12000],
    )

    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        truncated = resp.stop_reason == "max_tokens"
        note = (
            f"Response truncated at max_tokens before valid JSON completed: {e}."
            if truncated else
            f"Failed to parse Claude response as JSON: {e}."
        )
        return {
            "resolution_status": "UNRESOLVED",
            "research_notes": f"{note} Raw: {text[:500]}",
            "evidence": [],
        }
