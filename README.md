# 🎙️ DragBizz Voice AI

**DragBizz Voice AI** is a highly scalable FastAPI-based service designed for conversational data extraction and intelligent interaction management. It uses state-of-the-art LLMs to automate customer and supplier data processing.

---

## ✨ Key Features

- **🎯 Natural Language Processing:** Seamlessly extract structured customer and supplier data from raw conversational inputs.
- **🌐 Intelligent Fallback:** Automatically manages and falls back across 23+ AI models from OpenRouter to ensure 100% uptime.
- **🔄 Session Management:** Real-time state tracking using high-performance Redis sessions with automated TTL.
- **🛡️ Rate Limiting:** Built-in protection to prevent abuse and manage API costs efficiently.
- **⚡ High Performance:** Fully asynchronous architecture optimized for low-latency voice and chat interactions.

---

## 🛠️ Tech Stack

- **Framework:** FastAPI (Python 3.10+)
- **AI Core:** OpenRouter API (Access to GPT-4, Claude-3, Llama-3, etc.)
- **Persistence/Cache:** Redis (Async)
- **Deployment:** Gunicorn + Uvicorn
- **Containerization:** Docker

---

## 📁 Project Structure

```text
dragbizz-voice-ai/
├── app/
│   ├── api/            # Route definitions
│   ├── controllers/    # Request logic
│   ├── services/       # AI & Session business logic
│   ├── models/         # Pydantic schemas (Validation)
│   └── data/           # AI Model registries
├── gunicorn_config.py  # Production server setup
└── Dockerfile          # Image definition
```

---

## 🚀 Getting Started

To set up the project locally, please refer to the detailed technical guide:

👉 **[SETUP.MD](./SETUP.md)**

---

## 📄 License

Proprietary License - see LICENSE file for details.

---

**Powered by DragBizz** 🚀 | **AI Native** 🤖 | **Enterprise NLP** ⚡
