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


def parse_kaspi_excel(file_path: str) -> dict:
    """
    Parse a Kaspi bank Excel statement.

    Returns {"transactions": [...], "errors": [...], "warnings": [...], "summary": {...}}.
    Invalid rows are reported in `errors` (with the Excel row number) and not imported.
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    transactions, errors, warnings = [], [], []
    headers = None
    prev_balance = None
    rows_read = 0

    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if headers is None:
            row_str = " ".join(str(c or "").lower() for c in row)
            if "дата" in row_str or "date" in row_str:
                headers = [str(c or "").strip().lower() for c in row]
            continue

        if not any(c not in (None, "") for c in row):
            continue
        rows_read += 1

        tx, error = _map_row_to_transaction(row, headers)
        if error:
            errors.append({"row": i, "error": error})
            continue

        # Reconciliation: previous balance + in - out must equal the balance column
        balance = _to_float(_get_by_keywords(dict(zip(headers, row)), ["остаток", "balance"]))
        if balance is not None:
            if prev_balance is not None:
                delta = tx["amount"] if tx["direction"] == "in" else -tx["amount"]
                if abs(prev_balance + delta - balance) > 0.01:
                    warnings.append({
                        "row": i,
                        "error": f"Остаток не сходится: ожидалось {prev_balance + delta:,.2f}, в файле {balance:,.2f}",
                    })
            prev_balance = balance

        transactions.append(tx)

    if headers is None:
        errors.append({"row": 0, "error": "Не найдена строка заголовков (колонка «Дата»)"})
    else:
        _check_required_columns(headers, errors)

    return _build_result(transactions, errors, warnings, rows_read)


def _check_required_columns(headers: list, errors: list):
    data = {h: None for h in headers}
    if _find_key(data, ["дата", "date"]) is None:
        errors.append({"row": 0, "error": "Нет колонки «Дата»"})
    if _find_key(data, ["дебет", "расход", "debit"]) is None and \
       _find_key(data, ["кредит", "приход", "credit"]) is None:
        errors.append({"row": 0, "error": "Нет колонок «Дебет»/«Кредит»"})


def _build_result(transactions: list, errors: list, warnings: list, rows_read: int) -> dict:
    # Drop exact duplicates inside the file
    seen, unique = set(), []
    for tx in transactions:
        key = (tx["date"], tx["amount"], tx["direction"], tx["counterparty"], tx["description"])
        if key in seen:
            warnings.append({"row": 0, "error": f"Дубликат пропущен: {tx['date']} {tx['amount']:,.2f}"})
            continue
        seen.add(key)
        unique.append(tx)

    return {
        "transactions": unique,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "rows_read": rows_read,
            "valid": len(unique),
            "invalid": len([e for e in errors if e["row"]]),
            "total_in": round(sum(t["amount"] for t in unique if t["direction"] == "in"), 2),
            "total_out": round(sum(t["amount"] for t in unique if t["direction"] == "out"), 2),
        },
    }


def _map_row_to_transaction(row, headers: list) -> tuple[dict | None, str | None]:
    """Map a row to (transaction, None) or (None, error message)."""
    data = dict(zip(headers, row))

    date_val = _get_by_keywords(data, ["дата", "date"])
    amount_debit = _get_by_keywords(data, ["дебет", "расход", "debit"])
    amount_credit = _get_by_keywords(data, ["кредит", "приход", "credit"])
    counterparty = _get_by_keywords(data, ["контрагент", "получатель", "отправитель", "counterparty"])
    description = _get_by_keywords(data, ["описание", "назначение", "description", "purpose"])

    date_str = _format_date(date_val)
    if not date_str:
        return None, "Пустая дата"
    if not _is_iso_date(date_str):
        return None, f"Неверный формат даты: «{date_str}»"

    for label, raw in (("Дебет", amount_debit), ("Кредит", amount_credit)):
        if raw not in (None, "") and _to_float(raw) is None:
            return None, f"{label}: не число («{raw}»)"

    debit = _to_float(amount_debit)
    credit = _to_float(amount_credit)

    if debit and credit:
        return None, "Заполнены и дебет, и кредит"
    if credit is not None and credit < 0 or debit is not None and debit < 0:
        return None, "Отрицательная сумма"
    if credit:
        amount, direction = credit, "in"
    elif debit:
        amount, direction = debit, "out"
    else:
        return None, "Нет суммы (дебет и кредит пустые или 0)"

    return {
        "date": date_str,
        "amount": round(amount, 2),
        "direction": direction,
        "counterparty": str(counterparty or "").strip()[:200],
        "description": str(description or "").strip()[:500],
        "raw_data": str(dict(zip(headers, row))),
    }, None


def parse_kaspi_pdf(file_path: str) -> dict:
    """
    Parse a Kaspi bank statement PDF.
    Extracts text and looks for transaction patterns.
    """
    transactions, errors = [], []

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
        if amount and _is_iso_date(_format_date(date_str)):
            transactions.append({
                "date": _format_date(date_str),
                "amount": round(amount, 2),
                "direction": "unknown",  # PDF doesn't always have debit/credit columns
                "counterparty": "",
                "description": desc.strip()[:500],
                "raw_data": match.group(0),
            })

    if not transactions:
        errors.append({"row": 0, "error": "В PDF не найдено операций"})
    return _build_result(transactions, errors, [], len(transactions))


def _find_key(data: dict, keywords: list):
    for key in data:
        for kw in keywords:
            if kw in key.lower():
                return key
    return None


def _get_by_keywords(data: dict, keywords: list):
    """Find first matching value from a dict by keyword list."""
    key = _find_key(data, keywords)
    return data[key] if key is not None else None


def _is_iso_date(s: str) -> bool:
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


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
