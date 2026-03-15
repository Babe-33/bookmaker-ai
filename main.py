import os
import sys
import logging

# PHASE 128: DIAGNOSTIC BRIDGE
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Bridge")

logger.info(f"PYTHONPATH: {sys.path}")
logger.info(f"CWD: {os.getcwd()}")

try:
    # Add project root and backend to path
    root = os.path.dirname(os.path.abspath(__file__))
    if root not in sys.path: sys.path.append(root)
    backend_path = os.path.join(root, "backend")
    if backend_path not in sys.path: sys.path.append(backend_path)

    logger.info(f"Importing app from backend.main...")
    from backend.main import app
    logger.info("Import successful!")
except Exception as e:
    logger.error(f"FATAL IMPORT ERROR: {e}")
    raise e

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
