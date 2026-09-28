"""Dedupe qualified leads by normalized company website domain (fallback: company name).

Directory sources often list the same product twice under slightly
different names, so dedupe happens after resolution, not before.
"""
from __future__ import annotations

import re
from typing import List
from urllib.parse import urlparse


def _normalize_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        netloc = urlparse(url if "://" in url else f"//{url}").netloc.lower()
    except ValueError:
        return None
    netloc = re.sub(r"^www\.", "", netloc)
    return netloc or None


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def dedupe_leads(leads: List[dict]) -> List[dict]:
    """leads: list of flat dicts with at least 'website' and 'company_name'
    and 'score'. Keeps the highest-scoring row per dedupe key."""
    best_by_key: dict[str, dict] = {}
    order: List[str] = []

    for lead in leads:
        key = _normalize_domain(lead.get("website")) or _normalize_name(lead.get("company_name"))
        if not key:
            key = _normalize_name(lead.get("agent_name")) or f"__row__{lead.get('row_id')}"

        if key not in best_by_key:
            best_by_key[key] = lead
            order.append(key)
        else:
            if lead.get("score", 0) > best_by_key[key].get("score", 0):
                best_by_key[key] = lead

    return [best_by_key[k] for k in order]
