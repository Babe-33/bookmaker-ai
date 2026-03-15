import sys
import os

# PHASE 119: BULLETPROOF BRIDGE
# This file at the root tells Render exactly where to find the application.
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

from backend.main import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
