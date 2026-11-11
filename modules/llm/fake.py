"""
Fake AI: deterministic keyword rules that mimic the LLM output schema.
No network, no API key. Used when LLM_PROVIDER=fake (the default).
"""

# (keywords, subcategory, confidence)
_PERSONAL = ["снятие", "наличн", "банкомат",
             "atm", "себе", "личн", "перевод на карту"]

_INCOME_RULES = [
    (["аванс", "предоплат"], "Аванс от клиентов", 0.90),
    (["оплата", "договор", "услуг", "счет", "счёт",
     "инвойс", "акт"], "Оплата от клиентов", 0.90),
]

_EXPENSE_RULES = [
    (["аренд"], "Аренда офиса", 0.95),
    (["зарплат", "оклад"], "Зарплата сотрудников", 0.95),
    (["налог", "кпн", "ипн", "осмс", "опв", "взнос",
     "соцотчисл"], "Налоги и взносы", 0.90),
    (["коммунал", "электро", "отоплен", "водоканал",
     "алсеко"], "Коммунальные услуги", 0.90),
    (["связ", "мобильн", "интернет", "beeline",
     "kcell", "tele2", "altel"], "Услуги связи", 0.90),
    (["комисси"], "Банковские комиссии", 0.90),
    (["реклам", "маркетинг", "таргет", "соцсет"], "Реклама и маркетинг", 0.90),
    (["такси", "бензин", "азс", "транспорт", "доставк"], "Транспортные расходы", 0.85),
    (["ноутбук", "компьютер", "оборудован", "лицензи",
     "программн", "1с"], "Оборудование и ПО", 0.85),
    (["закупк", "товар", "поставщик"], "Закупка товаров", 0.85),
]


def _match(text: str, rules: list):
    for keywords, sub, conf in rules:
        hit = next((k for k in keywords if k in text), None)
        if hit:
            return sub, conf, hit
    return None


def fake_classify(tx: dict) -> dict:
    text = f"{tx.get('counterparty') or ''} {tx.get('description') or ''}".lower()

    hit = next((k for k in _PERSONAL if k in text), None)
    if hit:
        return {"category": "personal", "subcategory": "", "confidence": 0.85,
                "reasoning": f"Похоже на личную операцию (ключевое слово «{hit}»)."}

    if tx.get("direction") == "in":
        m = _match(text, _INCOME_RULES)
        if m:
            sub, conf, hit = m
            return {"category": "income", "subcategory": sub, "confidence": conf,
                    "reasoning": f"Входящий платёж, ключевое слово «{hit}»."}
        return {"category": "income", "subcategory": "Прочие доходы", "confidence": 0.40,
                "reasoning": "Входящий платёж без понятного описания — нужна проверка."}

    m = _match(text, _EXPENSE_RULES)
    if m:
        sub, conf, hit = m
        return {"category": "expense", "subcategory": sub, "confidence": conf,
                "reasoning": f"Исходящий платёж, ключевое слово «{hit}»."}
    return {"category": "expense", "subcategory": "Прочие расходы", "confidence": 0.40,
            "reasoning": "Исходящий платёж без понятного описания — нужна проверка."}


_RISK_EXPLANATIONS = {
    "large_cash_out": "Крупное снятие наличных может быть расценено как вывод средств без подтверждения деловой цели. Налоговый орган вправе запросить обоснование. Приложите документы или отнесите операцию к личным.",
    "income_no_doc": "Доход без подтверждающего документа (счёт, акт) трудно защитить при проверке. Прикрепите акт выполненных работ или договор.",
    "expense_no_doc": "Расход без первичного документа может быть не принят как деловой. Прикрепите счёт-фактуру, чек или акт.",
    "round_amount": "Круглые суммы сами по себе не нарушение, но привлекают внимание. Убедитесь, что есть договор или счёт.",
    "unclassified": "Операция не классифицирована, поэтому не попадёт в расчёт налога. Подтвердите категорию.",
    "monthly_limit_exceeded": (
        "RU: Доход за месяц превысил 300 МРП, это лимит режима самозанятых. Клиент может потерять право на режим: предупредите его и рассмотрите упрощённую декларацию.\n"
        "KZ: Айлық табыс 300 АЕК шегінен асты, бұл өзін-өзі жұмыспен қамтығандар режимінің лимиті. Клиент режимді қолдану құқығынан айырылуы мүмкін: оны ескертіп, оңайлатылған декларацияны қарастырыңыз.\n"
        "EN: Monthly income exceeded 300 MCI, the limit of the self-employed regime. The client may lose the regime: warn them and consider the simplified declaration."
    ),
    "salary_payment": (
        "RU: Платёж похож на выплату зарплаты. Самозанятый не вправе нанимать работников: проверьте, нет ли у клиента сотрудников.\n"
        "KZ: Төлем жалақы төлеміне ұқсайды. Өзін-өзі жұмыспен қамтыған тұлға қызметкер жалдай алмайды: клиентте қызметкерлер бар-жоғын тексеріңіз.\n"
        "EN: This payment looks like a salary. A self-employed person may not hire employees: check whether the client has employees."
    ),
    "unknown_counterparty": "Контрагент не указан, это усложняет подтверждение операции. Уточните получателя или отправителя.",
}


def fake_explain(risk: dict) -> str:
    return _RISK_EXPLANATIONS.get(risk.get("risk_type"), risk.get("description", "Требуется проверка операции."))
