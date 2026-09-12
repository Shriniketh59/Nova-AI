"""Nova AI - Unified Server Entrypoint

Runs the unified FastAPI server (Frontend SPA + Backend APIs + RAG Engine)
on a single port (default: http://localhost:5001).
"""

import os
import sys
import uvicorn
from dotenv import load_dotenv

# Load .env file with highest precedence
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV_PATH):
    load_dotenv(_ENV_PATH, override=True)
else:
    load_dotenv(override=True)

# Ensure the server package directory is on Python path
SERVER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server")
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from app.core.config import PORT  # noqa: E402


def ensure_ollama():
    """Ensure local Ollama service is running on 127.0.0.1:11434 so AI queries succeed."""
    import shutil
    import subprocess
    import time
    import urllib.request

    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1)
        print("🧠 Local AI Engine (Ollama): Active on http://127.0.0.1:11434")
        return
    except Exception:
        pass

    ollama_path = "/home/linux/ollama/bin/ollama"
    if not os.path.exists(ollama_path):
        ollama_path = shutil.which("ollama") or "ollama"

    print("⏳ Starting local AI Engine (Ollama serve)...")
    try:
        subprocess.Popen([ollama_path, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(15):
            time.sleep(0.5)
            try:
                urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1)
                print("🧠 Local AI Engine (Ollama): Started successfully.")
                return
            except Exception:
                pass
        print("⚠️ Ollama did not respond within 7.5s, proceeding with server startup.")
    except Exception as e:
        print(f"⚠️ Could not auto-launch Ollama: {e}")


def main():
    ensure_ollama()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", PORT))

    print("=" * 60)
    print(f"🚀 Starting Nova AI Unified Server on http://localhost:{port}")
    print(f"   - Frontend Web UI:  http://localhost:{port}")
    print(f"   - Backend APIs:     http://localhost:{port}/api")
    print(f"   - RAG Pipeline:     http://localhost:{port}/query/stream")
    print(f"   - Health Checks:    http://localhost:{port}/health")
    print("=" * 60)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
        app_dir=SERVER_DIR,
    )


if __name__ == "__main__":
    main()
