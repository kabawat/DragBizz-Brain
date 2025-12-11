#!/bin/bash

# Setup script for DragBizz Voice AI Service

echo "🚀 Setting up DragBizz Voice AI Service..."

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "✅ Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️ Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p storage/audio
mkdir -p logs

# Copy .env.example to .env if .env doesn't exist
if [ ! -f ".env" ]; then
    echo "📝 Creating .env file from .env.example..."
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "⚠️  Please update .env file with your configuration!"
    else
        echo "⚠️  .env.example not found. Please create .env manually."
    fi
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "To activate virtual environment manually:"
echo "  source venv/bin/activate"
echo ""
echo "To run the service:"
echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
echo ""
