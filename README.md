# AI Copilot for Accountants — Kazakhstan MVP

Налоговый помощник для ИП на УСН. Human-in-the-loop: LLM предлагает, бухгалтер решает.

---

## Быстрый старт

### 1. Требования

- Python 3.11+ (рекомендуется 3.11–3.13)
- Gemini API ключ или Anthropic API ключ — опционально (нужен только для реальных LLM-ответов)

### 2. Установка

```bash
# Клонировать или распаковать архив
cd copilot

# Создать виртуальное окружение
python -m venv venv
source venv/bin/activate       # Linux / macOS
# venv\Scripts\activate        # Windows

# Установить зависимости
pip install -r requirements.txt

# Настроить переменные окружения
cp .env.example .env
# Откройте .env и (опционально) вставьте GEMINI_API_KEY или ANTHROPIC_API_KEY
```

### 3. Запуск

```bash
python -m uvicorn app:app --reload --port 8000
```

Открыть в браузере: **http://localhost:8000**

### Запуск тестов

Тесты нужно запускать из виртуального окружения проекта:

```bash
source venv/bin/activate
python -m unittest discover -s tests -v
```

Или без активации окружения:

```bash
./venv/bin/python -m unittest discover -s tests -v
```

---

## Как пользоваться

### Шаг 1: Создать клиента
- Нажмите **«+ Клиент»** на главной
- Введите название ИП и БИН/ИИН

### Шаг 2: Создать отчётный период
- Нажмите **«+ Новый период»**
- Выберите клиента, квартал, год

### Шаг 3: Загрузить банковскую выписку
- Откройте период
- Выгрузите выписку из Kaspi Business (.xlsx или .pdf)
- Нажмите **«Загрузить выписку»**

### Шаг 4: Классифицировать операции (AI)
- Нажмите **«Классифицировать все»** — AI предложит категории
- Проверьте каждую операцию (цвет уверенности)
- Нажмите **«✓ Принять»** или **«✎ Изменить»** для каждой

### Шаг 5: Анализ рисков
- Нажмите **«🔍 Анализировать»**
- По каждому риску можно получить объяснение AI
- Закройте или проигнорируйте каждый риск

### Шаг 6: Скачать отчёт
- Нажмите **«📥 Скачать PDF»**
- PDF содержит: список операций, расчёт налога, риски

---

## Формат выписки Kaspi

Система ожидает Excel-файл из **Kaspi Business** → Выписка → Экспорт в Excel.

Типичные колонки: `Дата | Описание операции | Дебет | Кредит | Остаток | Контрагент`

Если колонки отличаются — система попытается подобрать автоматически.

---

## Структура проекта

```
copilot/
├── app.py                    # Все маршруты FastAPI
├── config.py                 # Настройки, ставки налогов
├── database.py               # SQLite, схема, запросы
├── modules/
│   ├── ingestion/            # Парсинг Kaspi Excel/PDF
│   ├── classifier/           # LLM классификация операций
│   ├── risk_engine/          # Правила рисков + LLM объяснение
│   └── export/               # Генерация PDF
├── templates/                # HTML страницы
├── static/                   # CSS и JS
└── data/
    ├── db.sqlite             # База данных
    └── uploads/              # Загруженные файлы
```

---

## LLM политика

| Действие | LLM участие |
|----------|-------------|
| Классификация операций | ✅ Предлагает категорию + обоснование |
| Выявление рисков | ❌ Только hardcoded правила |
| Объяснение рисков | ✅ Объясняет на русском |
| Расчёт налога | ❌ Детерминированная формула |
| Утверждение операций | ❌ Только бухгалтер |
| Подача отчёта | ❌ Не автоматизировано |

---

## Расширение

### Добавить второй банк
1. Создать `modules/ingestion/halyk_parser.py`
2. Реализовать функцию `parse_halyk_excel(file_path) -> list[dict]`
3. Добавить в `app.py` определение формата по названию файла

### Добавить налоговый режим
1. В `config.py` добавить ставку в `TAX_RATES`
2. В `modules/risk_engine/rules.py` добавить правила для режима
3. Всё остальное работает без изменений

---

## Настройки (.env)

```
LLM_PROVIDER=gemini              # gemini | anthropic
GEMINI_API_KEY=AIza...           # Опционально
GEMINI_MODEL=gemini-2.0-flash    # Рекомендуемый рабочий вариант
ANTHROPIC_API_KEY=sk-ant-...     # Опционально
DATABASE_PATH=data/db.sqlite     # Путь к БД
UPLOAD_DIR=data/uploads          # Папка для файлов
```

---

## Антипаттерны (не делать)

- ❌ Не включать автоподтверждение операций (даже при confidence 0.99)
- ❌ Не использовать LLM для расчёта налога
- ❌ Не хранить файлы в облаке без ведома бухгалтера
- ❌ Не подавать отчёты автоматически

---

## Поддержка

Это MVP. Если что-то не работает — проверьте:
1. `ANTHROPIC_API_KEY` в файле `.env`
2. Если используете Gemini: корректный `GEMINI_MODEL` (например, `gemini-2.0-flash`)
3. Формат выписки Kaspi (Excel, не PDF для лучшего результата)
4. Python 3.11+

Аудит-лог всех действий доступен по ссылке **«📋 Аудит»** в каждом периоде.

## Fake AI & tests

By default `LLM_PROVIDER=fake`: transactions are classified by built-in keyword rules (`modules/llm/fake.py`), no API key or network needed. Set `LLM_PROVIDER=gemini|anthropic` plus a key to use a real model.

```bash
python -m unittest discover -s tests -v
```

Labelled examples live in `tests/labelled_transactions.json`. Review screen: `/period/<id>/review`.
