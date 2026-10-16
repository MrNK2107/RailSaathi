"""Start RailSaathi locally: the FastAPI backend and the Vite frontend together.

    python run.py                  # backend on 8010, frontend on 5173
    python run.py --backend-port 8000 --frontend-port 5174

Installs dependencies on first run (uv sync, npm install), then runs both servers until Ctrl+C.
Needs Python 3.12, uv and Node.js 20+. No API keys: locally the app uses labelled demo data.
"""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
WINDOWS = os.name == "nt"


def tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        sys.exit(f"'{name}' was not found on PATH. Install it first (see README.md, Quick start).")
    return path


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def start(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
    return subprocess.Popen(cmd, cwd=cwd, env=env, creationflags=flags, start_new_session=not WINDOWS)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if WINDOWS:
        # npm and uvicorn --reload spawn children; kill the whole tree.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGTERM)


def wait_for(url: str, proc: subprocess.Popen, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RailSaathi backend and frontend locally.")
    parser.add_argument("--backend-port", type=int, default=8010)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--skip-install", action="store_true", help="do not run uv sync / npm install")
    args = parser.parse_args()

    uv, npm, npx = tool("uv"), tool("npm"), tool("npx")
    for port in (args.backend_port, args.frontend_port):
        if not port_free(port):
            sys.exit(f"Port {port} is already in use. Pick another with --backend-port / --frontend-port.")

    if not args.skip_install:
        print("Installing backend dependencies (uv sync)...")
        subprocess.run([uv, "sync"], cwd=BACKEND, check=True)
        if not (FRONTEND / "node_modules").exists():
            print("Installing frontend dependencies (npm install)...")
            subprocess.run([npm, "install"], cwd=FRONTEND, check=True)

    backend_url = f"http://127.0.0.1:{args.backend_port}"
    env = dict(os.environ, BACKEND_URL=backend_url)

    backend = start(
        [uv, "run", "python", "-m", "uvicorn", "app.main:create_app", "--factory", "--reload",
         "--port", str(args.backend_port)],
        BACKEND, env,
    )
    procs = [backend]
    try:
        print(f"Starting backend on {backend_url} ...")
        if not wait_for(f"{backend_url}/api/health", backend, 60):
            sys.exit("The backend did not start. Check the output above.")

        frontend = start([npx, "vite", "--port", str(args.frontend_port), "--strictPort"], FRONTEND, env)
        procs.append(frontend)
        app_url = f"http://localhost:{args.frontend_port}"
        if not wait_for(app_url, frontend, 60):
            sys.exit("The frontend did not start. Check the output above.")

        print()
        print(f"  RailSaathi is running:  {app_url}")
        print(f"  API docs:               {backend_url}/docs")
        print("  Press Ctrl+C to stop both.")
        print()
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("One of the servers stopped; shutting down the other.")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for p in procs:
            stop(p)


if __name__ == "__main__":
    main()
