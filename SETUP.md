# 🛠️ Setup Instructions - DragBizz Voice AI

This document provides technical instructions for setting up the DragBizz Voice AI service (FastAPI-based).

---

## 📦 Prerequisites

- **Python** (v3.10+)
- **Redis** server (Local or Docker)
- **Docker** & **Docker Compose** (Optional)
- **OpenRouter API Key** (Required for AI features)

---

## ⚙️ Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd dragbizz-voice-ai
   ```

2. **Run the setup script**
   This script handles virtual environment creation and dependency installation.
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. **Configure Environment Variables**
   ```bash
   cp .env.example .env
   ```
   Update `.env` with your `OPENROUTER_API_KEY` and Redis settings.

---

## 🚀 Running the Application

### Development (Local)
Active your virtual environment and start the Uvicorn server:
```bash
source env/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production (Local)
Run using Gunicorn with the provided configuration:
```bash
gunicorn app.main:app -c gunicorn_config.py
```

### Using Docker
```bash
docker compose up --build
```

---

## 📊 Logging & Health Check
- **Endpoints:**
  - `GET /api/v1/health` - Health check with Redis status
  - `GET /api/v1/ping` - Simple availability check
- **Logs:** Logs can be viewed via standard output or redirected to files in production environments.

---

## 🔧 Troubleshooting
- **Redis Connection:** Ensure Redis is running on the port specified in `.env` (default 6379).
- **AI Model Fallback:** If one model is rate-limited, the system automatically cycles through over 20+ alternate models defined in `app/data/available_models.json`.
- **API Key Errors:** Verify that your OpenRouter credit balance is positive for the models to respond.

---

## 🌐 Endpoints
- **Service Root:** http://localhost:8000
- **API Documentation (Auto-generated):** http://localhost:8000/docs
- **Customer Chat API:** `POST /api/v1/customer/chat`
- **Supplier Chat API:** `POST /api/v1/supplier/chat`
