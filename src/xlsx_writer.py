"""Writes the final output workbook matching the exact 3-tab structure the
user specified (AgentVet_Lead_Intelligence_Structure.pdf):

  1. HIGH PRIORITY        - sales-ready shortlist (Priority == HIGH)
  2. ALL QUALIFIED LEADS   - full qualified pipeline, all priorities
  3. RESEARCH - EVIDENCE   - one row per evidence item, across all companies

Column order matches the PDF's header grid read left-to-right, top-to-bottom.
This is a brand-new file — the original input database is never touched.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)

LEAD_COLUMNS = [
    "Priority", "Company / Agent", "Company",
    "AI Agent", "Website", "Agent URL",
    "Decision Maker", "Title", "Email",
    "LinkedIn", "X", "Fundraising Signal",
    "Signal Date", "Funding Stage", "Funding Amount",
    "Why Now", "Enterprise Signal", "Verification Gap",
    "Why AgentVet Is Relevant", "Outreach Angle", "Score",
    "Confidence", "Evidence URL 1", "Evidence URL 2",
    "Evidence URL 3", "Date Researched",
]

EVIDENCE_COLUMNS = [
    "Company / Agent", "Company", "AI Agent",
    "Signal Type", "Claim", "Evidence",
    "Source", "Source URL", "Source Date",
    "Confidence", "Research Notes", "Date Researched",
]


def _write_header(ws: Worksheet, columns: List[str]) -> None:
    for idx, col_name in enumerate(columns, start=1):
        cell = ws.cell(row=1, column=idx, value=col_name)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"


def _autosize(ws: Worksheet, columns: List[str], min_width=12, max_width=45) -> None:
    for idx, col_name in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = max(min_width, min(max_width, len(col_name) + 4))


def lead_row_dict_to_list(row: dict) -> list:
    ev = (row.get("evidence_urls") or []) + ["", "", ""]
    return [
        row.get("priority", ""),
        row.get("agent_name", ""),
        row.get("company_name", ""),
        row.get("agent_type", ""),
        row.get("website", ""),
        row.get("agent_url", ""),
        row.get("decision_maker_name", ""),
        row.get("decision_maker_title", ""),
        row.get("decision_maker_email", ""),
        row.get("decision_maker_linkedin", ""),
        row.get("decision_maker_x", ""),
        row.get("fundraising_signal", ""),
        row.get("signal_date", ""),
        row.get("funding_stage", ""),
        row.get("funding_amount", ""),
        row.get("why_now", ""),
        row.get("enterprise_signal", ""),
        row.get("verification_gap", ""),
        row.get("why_agentvet_relevant", ""),
        row.get("outreach_angle", ""),
        row.get("score", ""),
        row.get("confidence", ""),
        ev[0], ev[1], ev[2],
        row.get("date_researched", ""),
    ]


def evidence_row_dict_to_list(row: dict) -> list:
    return [
        row.get("agent_name", ""),
        row.get("company_name", ""),
        row.get("agent_type", ""),
        row.get("signal_type", ""),
        row.get("claim", ""),
        row.get("evidence", ""),
        row.get("source", ""),
        row.get("source_url", ""),
        row.get("source_date", ""),
        row.get("confidence", ""),
        row.get("research_notes", ""),
        row.get("date_researched", ""),
    ]


def write_workbook(
    leads: List[dict],
    evidence_rows: List[dict],
    output_path: Path,
) -> None:
    wb = Workbook()

    ws_high = wb.active
    ws_high.title = "HIGH PRIORITY"
    _write_header(ws_high, LEAD_COLUMNS)
    high_leads = [l for l in leads if l.get("priority") == "HIGH"]
    high_leads.sort(key=lambda l: l.get("score", 0), reverse=True)
    for r, lead in enumerate(high_leads, start=2):
        for c, val in enumerate(lead_row_dict_to_list(lead), start=1):
            ws_high.cell(row=r, column=c, value=val)
    _autosize(ws_high, LEAD_COLUMNS)

    ws_all = wb.create_sheet("ALL QUALIFIED LEADS")
    _write_header(ws_all, LEAD_COLUMNS)
    qualified = [l for l in leads if l.get("priority") in ("HIGH", "MEDIUM", "LOW")]
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    qualified.sort(key=lambda l: (priority_order.get(l.get("priority"), 9), -l.get("score", 0)))
    for r, lead in enumerate(qualified, start=2):
        for c, val in enumerate(lead_row_dict_to_list(lead), start=1):
            ws_all.cell(row=r, column=c, value=val)
    _autosize(ws_all, LEAD_COLUMNS)

    ws_evidence = wb.create_sheet("RESEARCH - EVIDENCE")
    _write_header(ws_evidence, EVIDENCE_COLUMNS)
    for r, ev in enumerate(evidence_rows, start=2):
        for c, val in enumerate(evidence_row_dict_to_list(ev), start=1):
            ws_evidence.cell(row=r, column=c, value=val)
    _autosize(ws_evidence, EVIDENCE_COLUMNS)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
