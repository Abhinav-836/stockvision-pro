
# Upgrade pip and install dependencies
python3 -m pip install --upgrade pip
pip install -r requirements.txt

# Start FastAPI with uvicorn
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
