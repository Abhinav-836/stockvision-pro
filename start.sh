#!/bin/bash

# ===============================
# Start script for frontend + backend on Railpack
# ===============================

# --- Backend setup ---
echo "Setting up backend..."
cd backend || exit

# Upgrade pip and install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Go back to root
cd ..

# --- Frontend setup ---
echo "Building frontend..."
cd frontend || exit

# Install Node dependencies (make sure Node is installed on Railpack)
npm install

# Build React app
npm run build

# Copy build to backend/static
# (FastAPI will serve this folder)
rm -rf ../backend/static
mkdir -p ../backend/static
cp -r build/* ../backend/static/

# Go back to backend to run FastAPI
cd ../backend || exit

# --- Run FastAPI ---
echo "Starting FastAPI..."
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
