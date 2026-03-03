#!/bin/bash
# Navigate to backend
cd backend

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Run FastAPI app (replace main:app with your entry point)
uvicorn main:app --host 0.0.0.0 --port $PORT
