"""
Risk Engine for USN (ИП, Казахстан).
Rules are hardcoded — LLM only explains.
Deterministic logic: no LLM in decision making.
"""

from modules.llm import generate_text, LLMRateLimitError, LLMError, LLMConfigError


# ─── Rule Engine ─────────────────────────────────────────────────────────────

RISK_RULES = [
    {
        "id": "large_cash_out",
        "type": "large_cash_out",
        "severity": "high",
        "description": "Large cash withdrawal without documented purpose",
        "check": lambda tx: (
            tx.get("direction") == "out"
            and tx.get("amount", 0) >= 300_000
            and _is_cash_like(tx)
        ),
    },
    {
        "id": "income_no_doc",
        "type": "income_no_doc",
        "severity": "medium",
        "description": "Large incoming payment without supporting document",
        "check": lambda tx, docs=None: (
            tx.get("category") == "income"
            and tx.get("amount", 0) >= 500_000
            and not (docs or [])
        ),
    },
    {
        "id": "expense_no_doc",
        "type": "expense_no_doc",
        "severity": "medium",
        "description": "Expense transaction without primary document",
        "check": lambda tx, docs=None: (
            tx.get("category") == "expense"
            and tx.get("amount", 0) >= 100_000
            and not (docs or [])
        ),
    },
    {
        "id": "round_amount",
        "type": "round_amount",
        "severity": "low",
        "description": "Round-number amount requires purpose validation",
        "check": lambda tx: (
            tx.get("amount", 0) >= 50_000
            and tx.get("amount", 0) % 100_000 == 0
        ),
    },
    {
        "id": "unclassified",
        "type": "unclassified",
        "severity": "high",
        "description": "Transaction is not classified by accountant",
        "check": lambda tx: (
            not tx.get("approved_by")
            and tx.get("category") is None
        ),
    },
    {
        "id": "unknown_counterparty",
        "type": "unknown_counterparty",
        "severity": "low",
        "description": "Counterparty is missing or not identified",
        "check": lambda tx: (
            not tx.get("counterparty")
            or tx.get("counterparty", "").strip() in ["", "—", "-", "нет"]
        ),
    },
]


def analyze_risks(transactions: list[dict], documents: dict = None) -> list[dict]:
    """
    Run all rules against transactions.
    documents: {transaction_id: [doc, ...]}
    Returns list of detected risks.
    """
    documents = documents or {}
    risks = []

    for tx in transactions:
        tx_docs = documents.get(tx["id"], [])
        for rule in RISK_RULES:
            try:
                # Some rules accept docs, some don't
                import inspect
                sig = inspect.signature(rule["check"])
                if len(sig.parameters) == 2:
                    triggered = rule["check"](tx, tx_docs)
                else:
                    triggered = rule["check"](tx)
            except Exception:
                triggered = False

            if triggered:
                risks.append({
                    "transaction_id": tx["id"],
                    "risk_type": rule["type"],
                    "severity": rule["severity"],
                    "description": rule["description"],
                    "llm_explanation": None,  # filled later on demand
                })

    return risks


def _is_cash_like(tx: dict) -> bool:
    keywords = ["наличн", "снятие", "atm", "банкомат", "обнал"]
    text = (tx.get("description", "") + tx.get("counterparty", "")).lower()
    return any(kw in text for kw in keywords)


# ─── LLM Explainer ───────────────────────────────────────────────────────────

def explain_risk(risk: dict, transaction: dict) -> str:
    """
    Ask LLM to explain a risk in plain language.
    Used on-demand when accountant clicks 'Объяснить'.
    """
    from config import LLM_PROVIDER
    if LLM_PROVIDER == "fake":
        from modules.llm.fake import fake_explain
        return fake_explain(risk)
    try:
        prompt = f"""Ты — налоговый консультант в Казахстане. Объясни бухгалтеру налоговый риск.

ОПЕРАЦИЯ:
Дата: {transaction.get("date", "")}
Сумма: {transaction.get("amount", 0)} тенге
Описание: {transaction.get("description", "")}
Контрагент: {transaction.get("counterparty", "")}

РИСК: {risk["description"]}
Тип: {risk["risk_type"]}
Серьёзность: {risk["severity"]}

Объясни:
1. В чём именно проблема по НК РК?
2. Какой штраф или последствие может быть?
3. Как исправить или снизить риск?

Ответ: 3–4 предложения, простым языком, без лишних слов."""
        return generate_text(prompt, max_tokens=400, temperature=0.2).strip()
    except LLMRateLimitError:
        return "LLM-объяснение недоступно: превышен лимит API (quota/rate limit). Попробуйте позже."
    except (LLMConfigError, LLMError) as e:
        return f"Не удалось получить объяснение: {str(e)}"
    except Exception as e:
        return f"Не удалось получить объяснение: {str(e)}"
