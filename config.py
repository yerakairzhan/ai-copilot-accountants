import os
from dotenv import load_dotenv

load_dotenv()


def _clean_api_key(value: str) -> str:
    key = (value or "").strip()
    lowered = key.lower()
    placeholder_markers = {"sk-ant-...", "your_key_here", "changeme"}
    placeholder_parts = ("...", "your-key", "your_key", "change-this", "example")
    if (
        not key
        or lowered in placeholder_markers
        or any(part in lowered for part in placeholder_parts)
    ):
        return ""
    return key


ANTHROPIC_API_KEY = _clean_api_key(os.getenv("ANTHROPIC_API_KEY", ""))
GEMINI_API_KEY = _clean_api_key(os.getenv("GEMINI_API_KEY", ""))
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/db.sqlite")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads")
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")


# "fake" = built-in rule-based classifier, no API calls (default).
# Set LLM_PROVIDER=gemini or anthropic (plus the key) to use a real model.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "fake").strip().lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash"
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5-20251101").strip() or "claude-opus-4-5-20251101"

# Tax settings
TAX_RATES = {
    "USN": 0.03,   # 3% with expenses not deductible
    "OUR": 0.10,   # Placeholder for future
}

# LLM settings
LLM_MODEL = os.getenv("LLM_MODEL", GEMINI_MODEL if LLM_PROVIDER == "gemini" else ANTHROPIC_MODEL).strip()
LLM_MIN_CONFIDENCE = 0.70
LLM_TEMPERATURE = 0.1

# Expense categories for USN
EXPENSE_CATEGORIES = [
    "Аренда офиса",
    "Зарплата сотрудников",
    "Налоги и взносы",
    "Закупка товаров",
    "Транспортные расходы",
    "Коммунальные услуги",
    "Услуги связи",
    "Банковские комиссии",
    "Реклама и маркетинг",
    "Оборудование и ПО",
    "Прочие расходы",
]

INCOME_CATEGORIES = [
    "Оплата от клиентов",
    "Аванс от клиентов",
    "Прочие доходы",
]

# Allowed top-level categories and, for each, the allowed subcategories.
# This is the single source of truth for the classifier output schema.
CATEGORY_SUBCATEGORIES = {
    "income": INCOME_CATEGORIES,
    "expense": EXPENSE_CATEGORIES,
    "personal": [],
}
