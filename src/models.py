"""Shared data structures used across the pipeline stages.

Every enum here matches the classification vocabulary in the AgentVet
qualification spec exactly, so scoring.py can key off these values without
re-deriving them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AgentType(str, Enum):
    TRUE_AGENT = "TRUE_AGENT"
    AI_TOOL = "AI_TOOL"
    UNCLEAR = "UNCLEAR"


class FundraisingStatus(str, Enum):
    ACTIVE_FUNDRAISING = "ACTIVE_FUNDRAISING"
    PRE_FUNDRAISING = "PRE_FUNDRAISING"
    INVESTOR_SEEKING = "INVESTOR_SEEKING"
    INVESTMENT_PROCESS = "INVESTMENT_PROCESS"
    RECENTLY_FUNDED = "RECENTLY_FUNDED"
    NO_FUNDRAISING_SIGNAL = "NO_FUNDRAISING_SIGNAL"
    UNKNOWN = "UNKNOWN"


class LaunchStatus(str, Enum):
    VERY_RECENT = "VERY_RECENT"   # 0-30 days
    RECENT = "RECENT"             # 31-90 days
    MODERATELY_RECENT = "MODERATELY_RECENT"  # 91-180 days
    NOT_RECENT = "NOT_RECENT"     # >180 days
    UNKNOWN = "UNKNOWN"


class EnterpriseSignal(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"


class VerificationGap(str, Enum):
    LARGE_GAP = "LARGE_GAP"
    PARTIAL_GAP = "PARTIAL_GAP"
    SMALL_GAP = "SMALL_GAP"


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    REJECT = "REJECT"


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"


@dataclass
class Evidence:
    claim: str
    evidence: str
    source_url: str
    source_date: Optional[str]
    confidence: float  # 0.0-1.0
    signal_type: str = ""  # fundraising | launch | enterprise | verification | contact


@dataclass
class InputRow:
    """Raw row from the existing 3,000+ agent database. Never mutated."""
    name: str
    categories: str = ""
    source: str = ""
    extra: dict = field(default_factory=dict)
    row_id: str = ""  # stable hash of name+source, used for dedupe/caching keys


@dataclass
class Stage1Candidate:
    row_id: str
    name: str
    categories: str
    source: str
    signal_score: int
    matched_keywords: list = field(default_factory=list)
    company_guess: Optional[str] = None
    website_guess: Optional[str] = None
    notes: str = ""


@dataclass
class Company:
    row_id: str
    agent_name: str
    company_name: Optional[str] = None
    website: Optional[str] = None
    agent_url: Optional[str] = None
    category: str = ""
    resolution_status: ResolutionStatus = ResolutionStatus.UNRESOLVED

    decision_maker_name: Optional[str] = None
    decision_maker_title: Optional[str] = None
    decision_maker_email: Optional[str] = None
    decision_maker_linkedin: Optional[str] = None
    decision_maker_x: Optional[str] = None
    company_linkedin: Optional[str] = None
    company_x: Optional[str] = None


@dataclass
class QualifiedLead:
    company: Company

    agent_type: AgentType = AgentType.UNCLEAR

    fundraising_status: FundraisingStatus = FundraisingStatus.UNKNOWN
    fundraising_signal: str = ""
    signal_date: Optional[str] = None
    funding_stage: Optional[str] = None
    funding_amount: Optional[str] = None
    previously_funded: Optional[bool] = None

    launch_date: Optional[str] = None
    launch_status: LaunchStatus = LaunchStatus.UNKNOWN
    launch_evidence: str = ""
    launch_source: str = ""

    enterprise_signal: EnterpriseSignal = EnterpriseSignal.UNKNOWN
    customer_signal: str = ""
    commercial_stage: str = ""

    verification_gap: VerificationGap = VerificationGap.LARGE_GAP
    verification_status: str = ""

    why_now: str = ""
    why_agentvet_relevant: str = ""
    outreach_angle: str = ""

    score: int = 0
    priority: Priority = Priority.REJECT
    confidence: str = "LOW"  # LOW / MEDIUM / HIGH, derived from evidence confidences

    evidence: list = field(default_factory=list)  # list[Evidence]
    date_researched: str = ""
