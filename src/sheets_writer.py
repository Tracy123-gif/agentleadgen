"""Pushes the same 3-tab structure as xlsx_writer.py to a live Google Sheet
instead of (or alongside) a local file, using a service account.

Setup (once):
  1. Enable the Google Sheets API on your GCP project:
     https://console.cloud.google.com/apis/library/sheets.googleapis.com
  2. Generate a JSON key for your existing service account (IAM & Admin >
     Service Accounts > your account > Keys > Add Key > JSON) and save the
     file somewhere under this project (NOT committed — see .gitignore).
  3. Create a blank Google Sheet in your own Drive and share it with the
     service account's email (ends in @<project>.iam.gserviceaccount.com)
     as Editor.
  4. Set GOOGLE_SERVICE_ACCOUNT_JSON (path to the key file) and
     GOOGLE_SHEET_ID (the long ID in the sheet's URL) in .env.

Only needs the 'spreadsheets' scope — writing to an already-shared,
already-known spreadsheet ID doesn't require Drive API access.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import gspread
from google.oauth2.service_account import Credentials

from . import config
from .xlsx_writer import (
    EVIDENCE_COLUMNS,
    LEAD_COLUMNS,
    evidence_row_dict_to_list,
    lead_row_dict_to_list,
)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

HEADER_BG = {"red": 0x1F / 255, "green": 0x4E / 255, "blue": 0x79 / 255}
HEADER_TEXT_FORMAT = {
    "bold": True,
    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
}


def _client() -> gspread.Client:
    if not config.GOOGLE_SERVICE_ACCOUNT_JSON:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON is not set in .env.")
    key_path = Path(config.GOOGLE_SERVICE_ACCOUNT_JSON)
    if not key_path.exists():
        raise FileNotFoundError(f"Service account key file not found: {key_path}")
    creds = Credentials.from_service_account_file(str(key_path), scopes=SCOPES)
    return gspread.authorize(creds)


def _write_sheet(spreadsheet: gspread.Spreadsheet, title: str, columns: List[str], rows: List[list]) -> None:
    try:
        ws = spreadsheet.worksheet(title)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=max(len(rows) + 10, 100), cols=max(len(columns) + 2, 12))

    values = [columns] + [[("" if v is None else v) for v in row] for row in rows]
    ws.update(values=values, range_name="A1")

    n_cols = len(columns)
    end_col_letter = gspread.utils.rowcol_to_a1(1, n_cols).rstrip("1")
    ws.format(f"A1:{end_col_letter}1", {
        "backgroundColor": HEADER_BG,
        "textFormat": HEADER_TEXT_FORMAT,
    })
    ws.freeze(rows=1)


def write_to_google_sheet(leads: List[dict], evidence_rows: List[dict], sheet_id: str | None = None) -> str:
    sheet_id = sheet_id or config.GOOGLE_SHEET_ID
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID is not set in .env.")

    client = _client()
    spreadsheet = client.open_by_key(sheet_id)

    high_leads = [l for l in leads if l.get("priority") == "HIGH"]
    high_leads.sort(key=lambda l: l.get("score", 0), reverse=True)
    _write_sheet(spreadsheet, "HIGH PRIORITY", LEAD_COLUMNS, [lead_row_dict_to_list(l) for l in high_leads])

    qualified = [l for l in leads if l.get("priority") in ("HIGH", "MEDIUM", "LOW")]
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    qualified.sort(key=lambda l: (priority_order.get(l.get("priority"), 9), -l.get("score", 0)))
    _write_sheet(spreadsheet, "ALL QUALIFIED LEADS", LEAD_COLUMNS, [lead_row_dict_to_list(l) for l in qualified])

    _write_sheet(spreadsheet, "RESEARCH - EVIDENCE", EVIDENCE_COLUMNS, [evidence_row_dict_to_list(e) for e in evidence_rows])

    _delete_empty_default_sheet(spreadsheet)

    return spreadsheet.url


def _delete_empty_default_sheet(spreadsheet: gspread.Spreadsheet) -> None:
    """Google names the sheet a new spreadsheet starts with "Sheet1"; once our
    3 real tabs exist, remove it automatically if it was never used, so the
    output doesn't carry a confusing blank tab on every run."""
    our_titles = {"HIGH PRIORITY", "ALL QUALIFIED LEADS", "RESEARCH - EVIDENCE"}
    for ws in spreadsheet.worksheets():
        if ws.title not in our_titles and not any(ws.get_all_values()):
            spreadsheet.del_worksheet(ws)
