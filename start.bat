@echo off
echo AI Copilot for Accountants - Starting...

if not exist ".env" (
    copy .env.example .env
    echo Created .env from .env.example
    echo GEMINI_API_KEY or ANTHROPIC_API_KEY is optional - app will run with fallback AI behavior.
)

if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate
echo Installing dependencies...
pip install -r requirements.txt -q

if not exist "data\uploads" mkdir data\uploads
if not exist "data\exports" mkdir data\exports

echo.
echo Ready! Open http://localhost:8000
echo.
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
