# 🚀 Voice AI Service - Kaise Run Karein

## Method 1: Development Mode (Recommended for Testing)

### Step 1: Virtual Environment Activate Karein

```bash
cd /home/mukesh/env/DragBizz/dragbizz-voice-ai
source venv/bin/activate
```

### Step 2: Dependencies Install Karein (Pehli Baar)

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3: Environment Variables Setup

```bash
# .env file create karein
cp .env.example .env

# .env file edit karein
nano .env
# ya
vim .env
```

**Important .env settings:**
```env
# OpenAI API Key (Zaroori)
OPENAI_API_KEY=sk-your-openai-api-key-here

# MongoDB (Agar separate MongoDB chahiye)
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=dragbizz

# Redis (Optional - agar nahi hai to skip karein)
REDIS_HOST=localhost
REDIS_PORT=6379

# Service URLs
RETAILER_SERVICE_URL=http://localhost:3002/api
AUTH_SERVICE_URL=http://localhost:3001/auth
JWKS_URL=http://localhost:3001/auth/.well-known/jwks.json

# Port
PORT=8000
```

### Step 4: Service Run Karein

```bash
# Development mode (auto-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Ya directly Python se:**
```bash
python -m app.main
```

### Step 5: Test Karein

```bash
# Health check
curl http://localhost:8000/api/health

# Browser mein
# http://localhost:8000/docs - Swagger UI
# http://localhost:8000/redoc - ReDoc
```

---

## Method 2: Setup Script Use Karein (Easiest)

```bash
cd /home/mukesh/env/DragBizz/dragbizz-voice-ai
./setup.sh
```

Setup script automatically:
- ✅ Virtual environment create/activate karega
- ✅ Dependencies install karega
- ✅ Directories create karega
- ✅ .env file setup karega

**Setup ke baad:**
```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Method 3: Docker Se Run Karein

### Step 1: Docker Compose Se

```bash
cd /home/mukesh/env/DragBizz/dragbizz-voice-ai

# .env file mein OpenAI API key set karein
export OPENAI_API_KEY=sk-your-key-here

# Docker compose run karein
docker-compose up -d

# Logs dekhne ke liye
docker-compose logs -f voice-ai
```

### Step 2: Ya Directly Docker Build

```bash
# Build image
docker build -t dragbizz-voice-ai .

# Run container
docker run -d \
  -p 8000:8000 \
  -e OPENAI_API_KEY=sk-your-key-here \
  -e MONGODB_URI=mongodb://host.docker.internal:27017 \
  -e RETAILER_SERVICE_URL=http://host.docker.internal:3002/api \
  dragbizz-voice-ai
```

---

## Method 4: Production Mode

### PM2 Se Run (Recommended for Production)

```bash
# PM2 install karein (agar nahi hai)
npm install -g pm2

# PM2 ecosystem file create karein
cat > ecosystem.config.js << EOF
module.exports = {
  apps: [{
    name: 'dragbizz-voice-ai',
    script: 'uvicorn',
    args: 'app.main:app --host 0.0.0.0 --port 8000',
    interpreter: 'venv/bin/python',
    instances: 2,
    exec_mode: 'cluster',
    env: {
      NODE_ENV: 'production'
    }
  }]
}
EOF

# PM2 se start karein
pm2 start ecosystem.config.js
pm2 save
pm2 startup
```

---

## Quick Start Commands

### Development (Hot Reload)
```bash
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Production (No Reload)
```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Docker
```bash
docker-compose up -d
```

---

## Service Check Karein

### Health Check
```bash
curl http://localhost:8000/api/health
```

**Expected Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "service": "DragBizz Voice AI"
}
```

### API Documentation
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Test Voice Command
```bash
curl -X POST http://localhost:8000/api/voice/command \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "audio=@test_audio.webm" \
  -F "language=hinglish"
```

---

## Troubleshooting

### Issue 1: Port Already in Use
```bash
# Port check karein
lsof -i :8000

# Ya different port use karein
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

### Issue 2: MongoDB Connection Error
```bash
# MongoDB running hai check karein
mongosh --eval "db.adminCommand('ping')"

# Ya .env mein correct URI set karein
MONGODB_URI=mongodb://localhost:27017
```

### Issue 3: OpenAI API Key Missing
```bash
# .env file check karein
cat .env | grep OPENAI_API_KEY

# Set karein
export OPENAI_API_KEY=sk-your-key-here
```

### Issue 4: Dependencies Install Nahi Ho Raha
```bash
# Virtual environment activate karein
source venv/bin/activate

# Pip upgrade karein
pip install --upgrade pip setuptools wheel

# Phir install karein
pip install -r requirements.txt
```

---

## Service Stop Karein

### Development Mode
```bash
# Terminal mein Ctrl+C press karein
```

### Docker
```bash
docker-compose down
```

### PM2
```bash
pm2 stop dragbizz-voice-ai
pm2 delete dragbizz-voice-ai
```

---

## Logs Dekhne Ke Liye

### Development
```bash
# Terminal mein directly dikhega
```

### Docker
```bash
docker-compose logs -f voice-ai
```

### PM2
```bash
pm2 logs dragbizz-voice-ai
```

---

## Next Steps

1. ✅ Service run ho gaya
2. ✅ Health check pass ho gaya
3. ✅ API docs check karein (http://localhost:8000/docs)
4. ✅ Frontend se integrate karein
5. ✅ Test voice commands

---

**Service URL:** http://localhost:8000  
**API Docs:** http://localhost:8000/docs  
**Health Check:** http://localhost:8000/api/health
