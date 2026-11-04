"""
AI Copilot for Accountants — Kazakhstan MVP
FastAPI application: all routes in one file for clarity.
"""

import os
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import database as db

import hmac
import hashlib
from config import UPLOAD_DIR, TAX_RATES, EXPENSE_CATEGORIES, INCOME_CATEGORIES, CATEGORY_SUBCATEGORIES
from modules.ingestion.kaspi_parser import parse_kaspi_excel, parse_kaspi_pdf
from modules.classifier.transaction_classifier import classify_transaction
from modules.risk_engine.rules import analyze_risks, explain_risk
from modules.export.pdf_generator import generate_tax_package

# ─── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="AI Copilot for Accountants")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs("data", exist_ok=True)
os.makedirs("data/exports", exist_ok=True)
db.init_db()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_conn():
    return db.get_connection()


AUTH_EMAIL = "admin@mail.ru"
AUTH_PASSWORD = "admin"
AUTH_COOKIE_NAME = "auth_token"
AUTH_SECRET = "change_this_secret_for_production"


def _save_upload(file: UploadFile, subdir: str = "") -> str:
    dest_dir = Path(UPLOAD_DIR) / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return str(dest)


def _make_auth_token(email: str) -> str:
    signature = hmac.new(AUTH_SECRET.encode(), email.encode(), hashlib.sha256).hexdigest()
    return f"{email}:{signature}"


def _verify_auth_token(token: str) -> bool:
    try:
        email, signature = token.split(":", 1)
    except ValueError:
        return False

    expected = hmac.new(AUTH_SECRET.encode(), email.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected) and email == AUTH_EMAIL


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return False
    return _verify_auth_token(token)


def render_template(request: Request, template_name: str, **context):
    context.setdefault("logged_in", _is_authenticated(request))
    context["request"] = request
    return templates.TemplateResponse(template_name, context)


# ─── Authentication ──────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_authenticated(request):
        return RedirectResponse("/", status_code=303)
    return render_template(request, "login.html")


@app.post("/login")
async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    if email == AUTH_EMAIL and password == AUTH_PASSWORD:
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(AUTH_COOKIE_NAME, _make_auth_token(email), httponly=True, max_age=3600)
        return response

    return render_template(request, "login.html", error="Неверный логин или пароль")


@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(AUTH_COOKIE_NAME)
    return response


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _is_authenticated(request):
        return RedirectResponse("/login", status_code=303)

    conn = get_conn()
    clients = conn.execute("SELECT * FROM clients ORDER BY created_at DESC").fetchall()
    periods = conn.execute("""
        SELECT p.*, c.name as client_name
        FROM periods p JOIN clients c ON p.client_id = c.id
        ORDER BY p.year DESC, p.quarter DESC
    """).fetchall()
    conn.close()
    return render_template(
        request,
        "dashboard.html",
        clients=[dict(c) for c in clients],
        periods=[dict(p) for p in periods],
    )


# ─── Clients ──────────────────────────────────────────────────────────────────

@app.post("/clients/create")
async def create_client(
    name: str = Form(...),
    bin_number: str = Form(""),
    tax_regime: str = Form("USN"),
):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO clients (name, bin, tax_regime) VALUES (?, ?, ?)",
        (name.strip(), bin_number.strip(), tax_regime)
    )
    client_id = cur.lastrowid
    conn.commit()
    conn.close()
    db.log_action("created_client", "client", client_id, {"name": name})
    return JSONResponse({"ok": True, "client_id": client_id})


# ─── Periods ──────────────────────────────────────────────────────────────────

@app.post("/periods/create")
async def create_period(
    client_id: int = Form(...),
    quarter: str = Form(...),
    year: int = Form(...),
):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO periods (client_id, quarter, year) VALUES (?, ?, ?)",
        (client_id, quarter, year)
    )
    period_id = cur.lastrowid
    conn.commit()
    conn.close()
    db.log_action("created_period", "period", period_id, {"quarter": quarter, "year": year})
    return JSONResponse({"ok": True, "period_id": period_id})


# ─── Period Review Page ────────────────────────────────────────────────────────

@app.get("/period/{period_id}", response_class=HTMLResponse)
async def period_view(request: Request, period_id: int):
    if not _is_authenticated(request):
        return RedirectResponse("/login", status_code=303)

    period = db.get_period_with_client(period_id)
    if not period:
        raise HTTPException(404, "Period not found")

    transactions = db.get_transactions(period_id)
    risks = db.get_risks(period_id)
    summary = db.calculate_tax_summary(period_id, TAX_RATES.get(period.get("tax_regime", "USN"), 0.03))

    open_risks = [r for r in risks if r.get("status") == "open"]
    pending_tx = [t for t in transactions if not t.get("approved_by")]

    conn = get_conn()
    docs_rows = conn.execute(
        "SELECT * FROM documents WHERE period_id = ?", (period_id,)
    ).fetchall()
    conn.close()
    docs = [dict(d) for d in docs_rows]

    return render_template(
        request,
        "period.html",
        period=period,
        transactions=transactions,
        risks=risks,
        open_risks=open_risks,
        pending_tx=pending_tx,
        summary=summary,
        docs=docs,
        expense_categories=EXPENSE_CATEGORIES,
        income_categories=INCOME_CATEGORIES,
    )


# ─── Upload Bank Statement ────────────────────────────────────────────────────

@app.post("/period/{period_id}/upload-statement")
async def upload_statement(period_id: int, file: UploadFile = File(...)):
    period = db.get_period_with_client(period_id)
    if not period:
        raise HTTPException(404, "Period not found")

    file_path = _save_upload(file, f"period_{period_id}")
    ext = Path(file.filename).suffix.lower()

    try:
        if ext == ".xlsx":
            parsed = parse_kaspi_excel(file_path)
        elif ext == ".pdf":
            parsed = parse_kaspi_pdf(file_path)
        else:
            return JSONResponse({"ok": False, "error": "Поддерживаются только .xlsx и .pdf файлы"})
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Ошибка парсинга: {str(e)}"})

    transactions = parsed["transactions"]
    errors, warnings = parsed["errors"], parsed["warnings"]

    # Skip rows already imported for this period (re-uploading the same file)
    conn = get_conn()
    existing = {
        (r["date"], r["amount"], r["direction"], r["counterparty"] or "", r["description"] or "")
        for r in conn.execute("SELECT * FROM transactions WHERE period_id = ?", (period_id,))
    }
    inserted = 0
    for tx in transactions:
        key = (tx["date"], tx["amount"], tx["direction"], tx["counterparty"], tx["description"])
        if key in existing:
            warnings.append({"row": 0, "error": f"Уже импортировано ранее: {tx['date']} {tx['amount']:,.2f}"})
            continue
        conn.execute("""
            INSERT INTO transactions
            (period_id, date, amount, direction, counterparty, description, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            period_id, tx["date"], tx["amount"], tx["direction"],
            tx["counterparty"], tx["description"], tx["raw_data"],
        ))
        inserted += 1
    conn.commit()
    conn.close()

    if inserted:
        db.refresh_period_status(period_id)

    if not inserted and not transactions:
        msg = errors[0]["error"] if errors else "Не найдено операций в файле"
        return JSONResponse({"ok": False, "error": msg, "errors": errors, "summary": parsed["summary"]})

    db.log_action("uploaded_statement", "period", period_id, {
        "file": file.filename, "transactions_imported": inserted
    })

    return JSONResponse({
        "ok": True, "imported": inserted,
        "summary": parsed["summary"], "errors": errors, "warnings": warnings,
    })


# ─── Upload Supporting Document ───────────────────────────────────────────────

@app.post("/period/{period_id}/upload-document")
async def upload_document(
    period_id: int,
    file: UploadFile = File(...),
    transaction_id: int = Form(None),
):
    file_path = _save_upload(file, f"docs_{period_id}")
    conn = get_conn()
    conn.execute(
        "INSERT INTO documents (transaction_id, period_id, file_name, file_path) VALUES (?, ?, ?, ?)",
        (transaction_id, period_id, file.filename, file_path)
    )
    conn.commit()
    conn.close()
    db.log_action("uploaded_document", "period", period_id, {"file": file.filename})
    return JSONResponse({"ok": True})


# ─── Classify All (LLM) ───────────────────────────────────────────────────────

@app.post("/period/{period_id}/classify-all")
async def classify_all(period_id: int):
    transactions = db.get_transactions(period_id)
    unclassified = [t for t in transactions if not t.get("llm_suggestion")]

    if not unclassified:
        return JSONResponse({"ok": True, "classified": 0, "message": "Все уже классифицированы"})

    conn = get_conn()
    classified_count = 0

    for tx in unclassified:
        try:
            result = classify_transaction(tx)
            conn.execute("""
                UPDATE transactions
                SET llm_suggestion = ?, llm_subcategory = ?, llm_confidence = ?, llm_reasoning = ?, needs_review = ?
                WHERE id = ?
            """, (
                result.get("category"),
                result.get("subcategory"),
                result.get("confidence"),
                result.get("reasoning"),
                1 if result.get("needs_review") else 0,
                tx["id"],
            ))
            classified_count += 1
        except Exception as e:
            conn.execute("""
                UPDATE transactions SET llm_reasoning = ? WHERE id = ?
            """, (f"Ошибка классификации: {str(e)}", tx["id"]))

    conn.commit()
    conn.close()

    db.log_action("classify_all", "period", period_id, {"classified": classified_count})
    return JSONResponse({"ok": True, "classified": classified_count})


# ─── Approve / Edit Transaction ───────────────────────────────────────────────

@app.post("/transaction/{tx_id}/approve")
async def approve_transaction(
    tx_id: int,
    category: str = Form(...),
    subcategory: str = Form(""),
):
    if category not in CATEGORY_SUBCATEGORIES:
        raise HTTPException(400, "Invalid category")
    if subcategory and subcategory not in CATEGORY_SUBCATEGORIES[category]:
        raise HTTPException(400, "Invalid subcategory for this category")

    conn = get_conn()
    tx = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not tx:
        conn.close()
        raise HTTPException(404, "Transaction not found")

    # "accepted" = accountant kept the AI suggestion as is, "edited" = changed it
    accepted = tx["llm_suggestion"] == category and (tx["llm_subcategory"] or "") == subcategory
    review_status = "accepted" if accepted else "edited"

    conn.execute("""
        UPDATE transactions
        SET category = ?, subcategory = ?, review_status = ?,
            approved_by = 'accountant', approved_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (category, subcategory, review_status, tx_id))
    conn.commit()
    conn.close()

    period_status = db.refresh_period_status(tx["period_id"])
    db.log_action("approved_transaction", "transaction", tx_id, {
        "old_category": tx["category"],
        "new_category": category,
        "subcategory": subcategory,
        "review_status": review_status,
        "llm_suggestion": tx["llm_suggestion"],
        "llm_confidence": tx["llm_confidence"],
    })
    return JSONResponse({"ok": True, "review_status": review_status, "period_status": period_status})


# ─── Accept / Edit screen ─────────────────────────────────────────────────────

@app.get("/period/{period_id}/review", response_class=HTMLResponse)
async def review_page(request: Request, period_id: int):
    if not _is_authenticated(request):
        return RedirectResponse("/login", status_code=303)

    period = db.get_period_with_client(period_id)
    if not period:
        raise HTTPException(404, "Period not found")

    transactions = db.get_transactions(period_id)
    return render_template(
        request,
        "review.html",
        period=period,
        transactions=transactions,
        pending=[t for t in transactions if not t.get("approved_by")],
        category_map=CATEGORY_SUBCATEGORIES,
    )


@app.post("/period/{period_id}/accept-confident")
async def accept_confident(period_id: int):
    """Bulk-accept AI suggestions that don't need review."""
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, llm_suggestion, llm_subcategory FROM transactions
        WHERE period_id = ? AND approved_by IS NULL
          AND llm_suggestion IS NOT NULL AND needs_review = 0
    """, (period_id,)).fetchall()
    for r in rows:
        conn.execute("""
            UPDATE transactions
            SET category = ?, subcategory = ?, review_status = 'accepted',
                approved_by = 'accountant', approved_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (r["llm_suggestion"], r["llm_subcategory"] or "", r["id"]))
    conn.commit()
    conn.close()
    db.refresh_period_status(period_id)
    db.log_action("accept_confident", "period", period_id, {"accepted": len(rows)})
    return JSONResponse({"ok": True, "accepted": len(rows)})


# ─── Run Risk Analysis ────────────────────────────────────────────────────────

@app.post("/period/{period_id}/analyze-risks")
async def run_risk_analysis(period_id: int):
    transactions = db.get_transactions(period_id)

    conn = get_conn()
    docs_rows = conn.execute(
        "SELECT * FROM documents WHERE period_id = ?", (period_id,)
    ).fetchall()
    conn.close()

    docs_by_tx = {}
    for d in docs_rows:
        tid = d["transaction_id"]
        if tid:
            docs_by_tx.setdefault(tid, []).append(dict(d))

    risks = analyze_risks(transactions, docs_by_tx)

    conn = get_conn()
    conn.execute("DELETE FROM risks WHERE period_id = ?", (period_id,))
    for r in risks:
        conn.execute("""
            INSERT INTO risks (period_id, transaction_id, risk_type, severity, description)
            VALUES (?, ?, ?, ?, ?)
        """, (period_id, r["transaction_id"], r["risk_type"], r["severity"], r["description"]))
    conn.commit()
    conn.close()

    db.log_action("analyzed_risks", "period", period_id, {"risks_found": len(risks)})
    return JSONResponse({"ok": True, "risks_found": len(risks)})


# ─── Explain Risk (LLM) ───────────────────────────────────────────────────────

@app.get("/risk/{risk_id}/explain")
async def get_risk_explanation(risk_id: int):
    conn = get_conn()
    risk_row = conn.execute("SELECT * FROM risks WHERE id = ?", (risk_id,)).fetchone()
    if not risk_row:
        conn.close()
        raise HTTPException(404)

    risk = dict(risk_row)
    tx = {}
    if risk.get("transaction_id"):
        tx_row = conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (risk["transaction_id"],)
        ).fetchone()
        if tx_row:
            tx = dict(tx_row)

    # Check if explanation already cached
    if risk.get("llm_explanation"):
        conn.close()
        return JSONResponse({"explanation": risk["llm_explanation"]})

    explanation = explain_risk(risk, tx)
    conn.execute(
        "UPDATE risks SET llm_explanation = ? WHERE id = ?",
        (explanation, risk_id)
    )
    conn.commit()
    conn.close()

    return JSONResponse({"explanation": explanation})


# ─── Resolve Risk ─────────────────────────────────────────────────────────────

@app.post("/risk/{risk_id}/resolve")
async def resolve_risk(risk_id: int, action: str = Form(...)):
    valid = {"resolved", "ignored"}
    if action not in valid:
        raise HTTPException(400, "Invalid action")

    conn = get_conn()
    conn.execute("""
        UPDATE risks SET status = ?, resolved_by = 'accountant', resolved_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (action, risk_id))
    conn.commit()
    conn.close()

    db.log_action(f"risk_{action}", "risk", risk_id)
    return JSONResponse({"ok": True})


# ─── Generate PDF ─────────────────────────────────────────────────────────────

@app.get("/period/{period_id}/export-pdf")
async def export_pdf(period_id: int):
    period = db.get_period_with_client(period_id)
    if not period:
        raise HTTPException(404)

    transactions = db.get_transactions(period_id)
    risks = db.get_risks(period_id)
    summary = db.calculate_tax_summary(period_id, TAX_RATES.get(period.get("tax_regime", "USN"), 0.03))

    client = {
        "name": period.get("client_name", ""),
        "bin": period.get("bin", ""),
    }

    filename = f"tax_package_{period_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = f"data/exports/{filename}"

    try:
        generate_tax_package(output_path, client, period, transactions, risks, summary)
    except Exception as e:
        raise HTTPException(500, f"Ошибка генерации PDF: {str(e)}")

    db.log_action("exported_pdf", "period", period_id, {"file": filename})

    return FileResponse(
        output_path,
        media_type="application/pdf",
        filename=filename,
    )


# ─── Audit Log ────────────────────────────────────────────────────────────────

@app.get("/period/{period_id}/audit", response_class=HTMLResponse)
async def audit_log(request: Request, period_id: int):
    if not _is_authenticated(request):
        return RedirectResponse("/login", status_code=303)

    period = db.get_period_with_client(period_id)
    conn = get_conn()
    logs = conn.execute(
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return render_template(
        request,
        "audit.html",
        period=period,
        logs=[dict(l) for l in logs],
    )


# ─── API: Transaction detail ──────────────────────────────────────────────────

@app.get("/api/transaction/{tx_id}")
async def get_transaction(tx_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404)
    return JSONResponse(dict(row))
