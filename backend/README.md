# StockVision Pro

AI-Powered Stock Analysis Platform with Real-time Data

## Features
- Real-time stock data via WebSocket
- AI-powered investment insights
- Interactive charts with multiple timeframes
- Stock comparison with AI analysis
- Watchlist management
- Indian stock market support (NSE/BSE)

## Tech Stack
- **Backend**: FastAPI, yFinance, WebSocket, Redis
- **Frontend**: React, Recharts, Vite
- **AI**: OpenRouter API (Llama 3.3)
- **Deployment**: Docker, Docker Compose

## Quick Start

### Using Docker (Recommended)
```bash
docker-compose up --build
Manual Setup
Clone the repository

Install backend dependencies:

bash
pip install -r requirements.txt
Install frontend dependencies:

bash
cd frontend
npm install
Create .env file (see .env.example)

Run backend:

bash
uvicorn main:app --reload
Run frontend:

bash
npm run dev
Environment Variables
Create a .env file:

env
OPENROUTER_API_KEY=your_key_here
REDIS_HOST=localhost
REDIS_PORT=6379
CACHE_TTL=60
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
API Documentation
Swagger UI: http://localhost:8000/api/docs

ReDoc: http://localhost:8000/api/redoc

License
MIT

text

### Create `.env.example`:
```env
OPENROUTER_API_KEY=your_openrouter_api_key_here
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
CACHE_TTL=60
LOG_LEVEL=INFO
ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
Step 2: Push to GitHub
bash
# Initialize git repository
git init

# Add all files
git add .

# Commit
git commit -m "Initial commit: StockVision Pro with real-time data and AI analysis"

# Add remote (replace with your repo URL)
git remote add origin https://github.com/yourusername/stockvision-pro.git

# Push
git push -u origin main
Step 3: Deploy Options
Option A: Deploy on Render (Easiest)
Create render.yaml:

yaml
services:
  - type: web
    name: stockvision-backend
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: REDIS_HOST
        value: stockvision-redis
      - key: REDIS_PORT
        value: 6379
      - key: CACHE_TTL
        value: 60
      - key: OPENROUTER_API_KEY
        sync: false

  - type: redis
    name: stockvision-redis
    ipAllowList: []
    maxmemoryPolicy: allkeys-lru

  - type: web
    name: stockvision-frontend
    env: static
    buildCommand: cd frontend && npm install && npm run build
    staticPublishPath: ./frontend/dist
    envVars:
      - key: VITE_API_URL
        value: https://stockvision-backend.onrender.com