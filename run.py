#!/usr/bin/env python3
"""
SlackWoot entry point.

Setup:  pip install -e .
Run:    python run.py
Dev:    python run.py --reload
"""

import sys
import os
import argparse

# Add src/ to path so 'app' is importable without install (fallback for dev)
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SlackWoot server")
    parser.add_argument("--reload", action="store_true", help="Auto-reload (dev mode)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Import after path fix; pass object not string to avoid subprocess path issues
    from app.main import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
