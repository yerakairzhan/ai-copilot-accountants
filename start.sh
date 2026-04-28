#!/bin/bash
# Quick start script for AI Copilot

set -e

echo "🧾 AI Copilot for Accountants — Starting..."

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  Created .env from .env.example"
    echo "   → Add GEMINI_API_KEY or ANTHROPIC_API_KEY for live AI responses (optional)."
fi

if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "📦 Installing dependencies..."
pip install -r requirements.txt -q

mkdir -p data/uploads data/exports

echo ""
echo "✅ Ready! Opening at http://localhost:8000"
echo ""
python3 -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
