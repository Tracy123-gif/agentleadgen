"""Load the existing 3,000+ agent database. Read-only — never write to this file.

No pandas/numpy: this environment blocks numpy's compiled DLL (Windows
Application Control policy), so CSV is read with the standard library and
XLSX with openpyxl directly — both pure-Python-facing and dependency-light.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import List

from openpyxl import load_workbook

from .models import InputRow


def _row_id(name: str, source: str) -> str:
    return hashlib.sha256(f"{name}|{source}".lower().encode("utf-8")).hexdigest()[:16]


def _rows_from_csv(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = [dict(r) for r in reader]
    return headers, rows


def _rows_from_xlsx(path: Path) -> tuple[list[str], list[dict]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h) if h is not None else "" for h in next(rows_iter)]
    rows = []
    for raw in rows_iter:
        if raw is None or all(v is None for v in raw):
            continue
        rows.append({headers[i]: raw[i] for i in range(len(headers)) if i < len(raw)})
    return headers, rows


def load_input(path: Path) -> List[InputRow]:
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        headers, raw_rows = _rows_from_xlsx(path)
    elif path.suffix.lower() == ".csv":
        headers, raw_rows = _rows_from_csv(path)
    else:
        raise ValueError(f"Unsupported input format: {path.suffix}. Use .csv or .xlsx")

    cols = {h.lower().strip(): h for h in headers if h}

    def pick(*candidates: str) -> str | None:
        for c in candidates:
            if c in cols:
                return cols[c]
        return None

    name_col = pick("name", "agent name", "agent")
    cat_col = pick("categories", "category")
    source_col = pick("source", "directory")

    if name_col is None:
        raise ValueError(
            f"Could not find a Name column in {path.name}. Columns found: {headers}"
        )

    known_cols = {c for c in (name_col, cat_col, source_col) if c}

    rows: List[InputRow] = []
    for r in raw_rows:
        raw_name = r.get(name_col)
        name = str(raw_name).strip() if raw_name is not None else ""
        if not name:
            continue
        raw_cat = r.get(cat_col) if cat_col else None
        raw_source = r.get(source_col) if source_col else None
        categories = str(raw_cat).strip() if raw_cat not in (None, "") else ""
        source = str(raw_source).strip() if raw_source not in (None, "") else ""
        extra = {
            k: v for k, v in r.items()
            if k not in known_cols and v not in (None, "")
        }
        rows.append(InputRow(
            name=name,
            categories=categories,
            source=source,
            extra=extra,
            row_id=_row_id(name, source),
        ))
    return rows
