"""
Kaspi bank statement parser.
Supports Excel (.xlsx) exports from Kaspi Business.

Kaspi Excel columns (typical):
  Дата, Описание операции, Дебет, Кредит, Остаток, Контрагент
"""

import openpyxl
import pdfplumber
import re
from datetime import datetime


def parse_kaspi_excel(file_path: str) -> list[dict]:
    """
    Parse a Kaspi bank Excel statement.
    Returns list of transaction dicts.
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    transactions = []
    header_row = None

    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        # Find header row
        if header_row is None:
            row_str = " ".join(str(c or "").lower() for c in row)
            if "дата" in row_str or "date" in row_str:
                header_row = i
                headers = [str(c or "").strip().lower() for c in row]
                continue
        
        if header_row is None:
            continue
        
        if not any(row):
            continue

        tx = _map_row_to_transaction(row, headers)
        if tx:
            transactions.append(tx)

    return transactions


def _map_row_to_transaction(row, headers: list) -> dict | None:
    """Map a row to a transaction dict based on detected headers."""
    data = dict(zip(headers, row))

    # Try to extract date
    date_val = _get_by_keywords(data, ["дата", "date"])
    amount_debit = _get_by_keywords(data, ["дебет", "расход", "debit"])
    amount_credit = _get_by_keywords(data, ["кредит", "приход", "credit"])
    counterparty = _get_by_keywords(data, ["контрагент", "получатель", "отправитель", "counterparty"])
    description = _get_by_keywords(data, ["описание", "назначение", "description", "purpose"])

    # Determine direction and amount
    debit = _to_float(amount_debit)
    credit = _to_float(amount_credit)

    if credit and credit > 0:
        amount = credit
        direction = "in"
    elif debit and debit > 0:
        amount = debit
        direction = "out"
    else:
        return None

    if not amount:
        return None

    date_str = _format_date(date_val)

    return {
        "date": date_str,
        "amount": round(amount, 2),
        "direction": direction,
        "counterparty": str(counterparty or "").strip()[:200],
        "description": str(description or "").strip()[:500],
        "raw_data": str(dict(zip(headers, row))),
    }


def parse_kaspi_pdf(file_path: str) -> list[dict]:
    """
    Parse a Kaspi bank statement PDF.
    Extracts text and looks for transaction patterns.
    """
    transactions = []

    with pdfplumber.open(file_path) as pdf:
        full_text = ""
        for page in pdf.pages:
            full_text += page.extract_text() or ""

    # Pattern: date, description, amount
    # This is a simplified pattern – adjust to actual Kaspi PDF layout
    pattern = re.compile(
        r'(\d{2}\.\d{2}\.\d{4})\s+(.+?)\s+([\d\s]+[,\.]\d{2})\s*(тг|₸|KZT)?',
        re.MULTILINE
    )

    for match in pattern.finditer(full_text):
        date_str, desc, amount_str, _ = match.groups()
        amount = _to_float(amount_str.replace(" ", "").replace(",", "."))
        if amount:
            transactions.append({
                "date": _format_date(date_str),
                "amount": round(amount, 2),
                "direction": "unknown",  # PDF doesn't always have debit/credit columns
                "counterparty": "",
                "description": desc.strip()[:500],
                "raw_data": match.group(0),
            })

    return transactions


def _get_by_keywords(data: dict, keywords: list):
    """Find first matching value from a dict by keyword list."""
    for key in data:
        for kw in keywords:
            if kw in key.lower():
                return data[key]
    return None


def _to_float(val) -> float | None:
    if val is None:
        return None
    try:
        cleaned = str(val).replace(" ", "").replace(",", ".").replace("₸", "").replace("тг", "").strip()
        return float(cleaned) if cleaned else None
    except (ValueError, TypeError):
        return None


def _format_date(val) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s
