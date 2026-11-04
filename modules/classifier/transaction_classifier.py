"""
Transaction classifier using configured LLM provider.
LLM SUGGESTS — human DECIDES. Never auto-approve.
"""

import json
from config import (
    LLM_MIN_CONFIDENCE, LLM_PROVIDER,
    LLM_TEMPERATURE, EXPENSE_CATEGORIES, INCOME_CATEGORIES, CATEGORY_SUBCATEGORIES,
)
from modules.llm import generate_text, LLMRateLimitError, LLMError, LLMConfigError
from modules.llm.fake import fake_classify


def classify_transaction(transaction: dict) -> dict:
    """
    Call LLM to classify a single transaction.
    Returns suggestion dict with confidence score.
    """
    try:
        if LLM_PROVIDER == "fake":
            result = _validate_and_clean(fake_classify(transaction))
        else:
            raw = generate_text(_build_prompt(transaction), max_tokens=512, temperature=LLM_TEMPERATURE)
            result = _parse_llm_response(raw)
    except LLMRateLimitError:
        result = _fallback_classification("Превышен лимит API (quota/rate limit). Попробуйте позже.")
    except (LLMConfigError, LLMError) as e:
        result = _fallback_classification(str(e))
    except Exception as e:
        result = _fallback_classification(str(e))

    result["needs_review"] = result["confidence"] < LLM_MIN_CONFIDENCE
    return result


def classify_batch(transactions: list[dict]) -> list[dict]:
    """Classify multiple transactions, one by one."""
    results = []
    for tx in transactions:
        suggestion = classify_transaction(tx)
        results.append({
            "transaction": tx,
            "suggestion": suggestion,
        })
    return results


def _build_prompt(tx: dict) -> str:
    expense_list = "\n".join(f"  - {c}" for c in EXPENSE_CATEGORIES)
    income_list = "\n".join(f"  - {c}" for c in INCOME_CATEGORIES)

    direction_hint = ""
    if tx.get("direction") == "in":
        direction_hint = "Это входящий платёж (деньги пришли на счёт)."
    elif tx.get("direction") == "out":
        direction_hint = "Это исходящий платёж (деньги ушли со счёта)."

    return f"""Ты — налоговый помощник для ИП на УСН в Казахстане.
Проанализируй банковскую операцию и определи её налоговую категорию.

ОПЕРАЦИЯ:
Дата: {tx.get("date", "")}
Сумма: {tx.get("amount", 0)} тенге
Контрагент: {tx.get("counterparty", "не указан")}
Описание: {tx.get("description", "нет описания")}
{direction_hint}

КАТЕГОРИИ:
Категория "income" — деловой доход:
{income_list}

Категория "expense" — деловой расход:
{expense_list}

Категория "personal" — личная операция, не учитывается в налоге.

ПРАВИЛА:
- Если операция явно деловая (клиент, поставщик, аренда) — income или expense.
- Если снятие наличных без описания — личная.
- Если перевод себе — личная.
- Confidence: 0.0–1.0 (насколько ты уверен).
- Если непонятно — confidence ниже 0.70 и нужно объяснить почему.

Ответь ТОЛЬКО в JSON без markdown блоков:
{{
  "category": "income" | "expense" | "personal",
  "subcategory": "...",
  "confidence": 0.0-1.0,
  "reasoning": "краткое объяснение на русском"
}}"""


def _parse_llm_response(raw: str) -> dict:
    """Parse LLM JSON response with fallback."""
    try:
        # Strip markdown code blocks if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        data = json.loads(text)
        return _validate_and_clean(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        return _fallback_classification("JSON parse error")


def _validate_and_clean(data: dict) -> dict:
    """Validate LLM response fields."""
    category = data.get("category", "")

    if category not in CATEGORY_SUBCATEGORIES:
        return _fallback_classification(f"Invalid category: {category}")

    confidence = float(data.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    # Subcategory must come from the fixed list for this category, otherwise drop it
    subcategory = str(data.get("subcategory") or "")
    if subcategory not in CATEGORY_SUBCATEGORIES[category]:
        subcategory = ""
        confidence = min(confidence, LLM_MIN_CONFIDENCE - 0.01) if CATEGORY_SUBCATEGORIES[category] else confidence

    return {
        "category": category,
        "subcategory": subcategory,
        "confidence": confidence,
        "reasoning": str(data.get("reasoning", ""))[:500],
    }


def _fallback_classification(reason: str) -> dict:
    """Return safe fallback when LLM fails."""
    return {
        "category": None,
        "subcategory": None,
        "confidence": 0.0,
        "reasoning": f"Не удалось классифицировать автоматически: {reason}",
        "needs_review": True,
    }
