# DragBizz Voice AI

A scalable FastAPI-based Voice AI service for natural language customer and supplier data extraction and conversation management.

## Features

- 🎯 **Natural Language Processing**: Extract customer/supplier data from conversational prompts
- 🌐 **Multi-language Support**: Automatically detects and responds in user's language
- ⚡ **High Performance**: Async operations with Redis caching and connection pooling
- 🔄 **Dynamic Model Management**: Automatic fallback across 23+ AI models
- 📊 **Session Management**: Redis-based conversation sessions with TTL
- 🛡️ **Rate Limiting**: Per-user rate limiting to prevent abuse
- 🚀 **Scalable**: Designed to handle 10M+ users with multiple workers

## Tech Stack

- **Framework**: FastAPI
- **Python**: 3.10+
- **Cache/Sessions**: Redis (async)
- **AI Provider**: OpenRouter API
- **Server**: Gunicorn + Uvicorn workers

## Quick Start

### Prerequisites

- Python 3.10 or higher
- Redis server (or use Docker)
- OpenRouter API key

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd dragbizz-voice-ai
   ```

2. **Run setup script**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Start Redis** (if not using Docker)
   ```bash
   redis-server
   ```

5. **Run the application**

   **Development:**
   ```bash
   source env/bin/activate
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   **Production:**
   ```bash
   gunicorn app.main:app -c gunicorn_config.py
   ```

   **Docker:**
   ```bash
   docker compose up --build
   ```

## Environment Variables

Create a `.env` file with the following variables:

```env
# Required
OPENROUTER_API_KEY=your_api_key_here
BASE_URL=http://localhost

# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0

# JWT Configuration
JWT_ALGORITHM=RS256
JWT_ISSUER=DragBizz-auth
JWT_AUDIENCE=VOICE-AI,RETAILER

# Application Settings
ENVIRONMENT=development
DEBUG=false
SESSION_TTL=300

# Rate Limiting
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
RATE_LIMIT_PER_HOUR=1000

# Optional
OPENROUTER_HTTP_REFERER=
OPENROUTER_TITLE=
ALLOWED_ORIGINS=
```

## API Endpoints

### Health Check
- `GET /api/v1/health` - Health check with Redis status
- `GET /api/v1/ping` - Simple ping endpoint

### Customer Chat
- `POST /api/v1/customer/chat` - Conversational customer data extraction

### Supplier Chat
- `POST /api/v1/supplier/chat` - Conversational supplier data extraction

## Project Structure

```
dragbizz-voice-ai/
├── app/
│   ├── api/              # API routes
│   ├── config/           # Configuration files
│   ├── constants/        # Constants and enums
│   ├── controllers/      # Request handlers
│   ├── data/             # Models file (available_models.json)
│   ├── lib/              # External libraries
│   ├── middlewares/      # Custom middlewares
│   ├── models/           # Pydantic models
│   ├── services/         # Business logic
│   └── utils/            # Utility functions
├── docker-compose.yml    # Docker configuration
├── Dockerfile            # Docker image
├── gunicorn_config.py    # Gunicorn configuration
├── requirements.txt      # Python dependencies
├── setup.sh             # Setup script
└── README.md            # This file
```

## AI Models

The service uses dynamic model management with automatic fallback:

- Models are stored in `app/data/available_models.json`
- Automatically switches to next model on rate limit (429)
- Temporary errors (500+) use fallback without removing model
- Supports 23+ AI models from OpenRouter

## Performance

- **Redis Connection Pool**: 1000 connections
- **HTTP Connection Pool**: 500 connections
- **Workers**: Auto-scales based on CPU cores
- **Async Operations**: All I/O operations are async
- **Caching**: Redis-based response caching

## Development

### Running Tests
```bash
# Add test commands here when available
```

### Code Style
- Follows PEP 8
- Type hints for all functions
- Async/await for I/O operations

## Production Deployment

1. Set `ENVIRONMENT=production` in `.env`
2. Configure proper `ALLOWED_ORIGINS`
3. Use Gunicorn with multiple workers
4. Set up load balancer (Nginx/HAProxy)
5. Configure Redis cluster for high availability
6. Set up monitoring (Prometheus/Grafana)

## License

[Add your license here]

## Support

For issues and questions, please contact the development team.

