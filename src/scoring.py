"""Deterministic scoring — ICP: underfunded agents that need AgentVet.

Kept separate from claude_analysis.py on purpose: classification (what is
true, backed by evidence) comes from Claude; scoring (how much that matters)
is arithmetic and must be reproducible/auditable without re-calling the LLM.

NOTE — this deliberately INVERTS the original spec's fundraising priority.
The original spec scored active-fundraising signals highest (companies
raising money = hot prospects). Per explicit direction, the target ICP is
now the opposite: agents with CONFIRMED NO FUNDING who need it — active
fundraising is no longer required or even rewarded, since a company already
mid-raise/validated by investors is not the target. See README's "Target
ICP" section.
"""
from __future__ import annotations

import re

FUNDRAISING_POINTS = {
    "NO_FUNDRAISING_SIGNAL": 40,   # confirmed no funding — the target
    "UNKNOWN": 15,                  # unconfirmed either way — plausible but not evidenced
    "PRE_FUNDRAISING": 10,          # hasn't raised yet, still essentially unfunded
    "ACTIVE_FUNDRAISING": 0,        # already in-process — no longer the priority
    "INVESTOR_SEEKING": 0,
    "INVESTMENT_PROCESS": 0,
    "RECENTLY_FUNDED": -20,         # has funding — explicitly not the target now
}

AGENT_TYPE_POINTS = {
    "TRUE_AGENT": 20,
    "UNCLEAR": 5,
    "AI_TOOL": -30,
}

LAUNCH_POINTS = {
    "VERY_RECENT": 20,
    "RECENT": 15,
    "MODERATELY_RECENT": 5,
    "NOT_RECENT": 0,
    "UNKNOWN": 0,
}

ENTERPRISE_POINTS = {
    "STRONG": 15,
    "MODERATE": 10,
    "WEAK": 3,
    "UNKNOWN": 0,
}

VERIFICATION_POINTS = {
    "LARGE_GAP": 15,
    "PARTIAL_GAP": 8,
    "SMALL_GAP": 0,
}

NO_FUNDING_TARGET_STATUSES = {"NO_FUNDRAISING_SIGNAL"}

# Deterministic backstop, not a substitute for Claude's judgment: these are
# companies where "no funding evidence found" just means search queries
# built around startup-style raises ("seed round", "Series A") don't apply
# to them at all — not that they're underfunded. Found in practice: Amazon
# (via a Nova Act/AGI Lab agent listing) and OpenAI both scored as
# "no funding signal" HIGH-priority leads, which is absurd. Matched as a
# whole word against the normalized company name so this catches existing
# checkpoints immediately, without needing a new Claude field/re-run.
KNOWN_LARGE_COMPANIES = {
    "amazon", "google", "alphabet", "microsoft", "meta", "facebook",
    "apple", "openai", "anthropic", "nvidia", "ibm", "oracle",
    "salesforce", "adobe", "netflix", "tesla", "samsung", "intel",
    "alibaba", "tencent", "baidu", "bytedance", "sap", "servicenow",
    "databricks", "snowflake", "uber", "airbnb", "spacex", "x",
    "twitter", "linkedin", "cisco", "dell", "hp", "sony",
}


def _is_known_large_company(company_name: str | None) -> bool:
    if not company_name:
        return False
    tokens = set(re.findall(r"[a-z0-9]+", company_name.lower()))
    return bool(tokens & KNOWN_LARGE_COMPANIES)


def normalize_fundraising_status(classification: dict) -> str:
    """Cross-checks fundraising_status against the separate previously_funded
    boolean Claude also returns, and corrects it if they contradict.

    Found in practice: Claude sometimes cites clear historical funding
    evidence (previously_funded=true, a funding_amount) but still labels
    fundraising_status "NO_FUNDRAISING_SIGNAL" — reading that value as "not
    CURRENTLY raising" rather than its intended meaning of "no funding ever
    found." Since previously_funded is a simpler true/false judgment, it's
    more reliable than the 7-way enum choice, so it's used here as the
    source of truth when they disagree. This runs on every scoring pass
    (including re-exports of old checkpoints), so it self-heals existing
    data with no new API calls."""
    status = classification.get("fundraising_status", "UNKNOWN")
    if classification.get("previously_funded") is True and status in ("NO_FUNDRAISING_SIGNAL", "UNKNOWN"):
        return "RECENTLY_FUNDED"
    return status


DECISION_MAKER_BONUS = 5  # a lead with nobody to actually contact is less actionable


def compute_score(classification: dict) -> int:
    score = 0
    score += FUNDRAISING_POINTS.get(normalize_fundraising_status(classification), 0)
    score += AGENT_TYPE_POINTS.get(classification.get("agent_type", "UNCLEAR"), 0)
    score += LAUNCH_POINTS.get(classification.get("launch_status", "UNKNOWN"), 0)
    score += ENTERPRISE_POINTS.get(classification.get("enterprise_signal", "UNKNOWN"), 0)
    score += VERIFICATION_POINTS.get(classification.get("verification_gap", "LARGE_GAP"), 0)
    if classification.get("decision_maker_name"):
        score += DECISION_MAKER_BONUS
    return score


def compute_priority(classification: dict, score: int) -> str:
    resolution_status = classification.get("resolution_status", "UNRESOLVED")
    agent_type = classification.get("agent_type", "UNCLEAR")
    fundraising_status = normalize_fundraising_status(classification)

    if resolution_status != "RESOLVED" or agent_type == "AI_TOOL":
        return "REJECT"

    if _is_known_large_company(classification.get("company_name")):
        return "REJECT"

    has_evidence = bool(classification.get("evidence"))
    if not has_evidence:
        return "REJECT"

    if (
        score >= 70
        and agent_type == "TRUE_AGENT"
        and fundraising_status in NO_FUNDING_TARGET_STATUSES
    ):
        return "HIGH"
    if score >= 45:
        return "MEDIUM"
    return "LOW"


def derive_confidence(classification: dict) -> str:
    evidence = classification.get("evidence") or []
    if not evidence:
        return "LOW"
    confidences = [e.get("confidence", 0.0) for e in evidence if isinstance(e.get("confidence", 0.0), (int, float))]
    if not confidences:
        return "LOW"
    avg = sum(confidences) / len(confidences)
    if avg >= 0.7:
        return "HIGH"
    if avg >= 0.4:
        return "MEDIUM"
    return "LOW"
