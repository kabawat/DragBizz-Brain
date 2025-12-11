#!/bin/bash

# Quick run script for DragBizz Voice AI Service

echo "🎤 Starting DragBizz Voice AI Service..."

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    echo "📥 Installing dependencies..."
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# Activate virtual environment
echo "✅ Activating virtual environment..."
source venv/bin/activate

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found!"
    if [ -f ".env.example" ]; then
        echo "📝 Creating .env from .env.example..."
        cp .env.example .env
        echo "⚠️  Please update .env file with your configuration (especially OPENAI_API_KEY)"
    else
        echo "❌ .env.example not found. Please create .env manually."
        exit 1
    fi
fi

# Create directories
mkdir -p storage/audio logs

# Check if required services are running (optional)
echo "🔍 Checking dependencies..."

# Run the service
echo ""
echo "🚀 Starting service on http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo "❤️  Health: http://localhost:8000/api/health"
echo ""
echo "Press Ctrl+C to stop"
echo ""

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
