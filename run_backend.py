"""
Unified RailSaathi Platform Backend Runner
Launches the consolidated FastAPI application on Port 8000.
"""

import sys
import os
from pathlib import Path

# Ensure backend directory is in Python path
BACKEND_DIR = (Path(__file__).parent / "backend").resolve()
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["PYTHONPATH"] = str(BACKEND_DIR)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("app.main:create_app", factory=True, host="127.0.0.1", port=8000, reload=True)
