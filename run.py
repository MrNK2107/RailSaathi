"""Start RailSaathi locally: the FastAPI backend and the Vite frontend together.

    python run.py                  # backend on 8010, frontend on 5173 (HTTPS, open to your Wi-Fi)
    python run.py --no-https       # plain HTTP (camera, microphone and motion sensors won't work on phones)
    python run.py --backend-port 8000 --frontend-port 5174

Installs dependencies on first run (uv sync, npm install), then runs both servers until Ctrl+C.
Prints a QR code for the Wi-Fi address so phones on the same network can open the app.
Needs Python 3.12, uv and Node.js 20+. No API keys: locally the app uses built-in sample data.
"""

import argparse
import os
import shutil
import signal
import socket
import ssl
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
    # The dev HTTPS certificate is self-signed, so this local readiness probe skips verification.
    insecure = ssl._create_unverified_context()
    deadline = time.time() + seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=2, context=insecure):
                return True
        except OSError:
            time.sleep(1)
    return False


def lan_ip() -> str | None:
    """The address other devices on this Wi-Fi reach us at (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        except OSError:
            return None
    return None if ip.startswith("127.") else ip


QR_FILE = ROOT / "railsaathi-qr.svg"


def print_qr(uv: str, url: str) -> None:
    """Draw a scannable QR code in the terminal and save it as an SVG (uv fetches qrcode on first use)."""
    code = (
        "import qrcode, qrcode.image.svg, sys\n"
        f"q = qrcode.QRCode(border=2); q.add_data({url!r}); q.make(fit=True)\n"
        "q.print_ascii(invert=True)\n"
        f"q.make_image(image_factory=qrcode.image.svg.SvgPathImage).save({str(QR_FILE)!r})\n"
    )
    env = dict(os.environ, PYTHONIOENCODING="utf-8")  # the block characters fail in the Windows cp1252 codec
    result = subprocess.run([uv, "run", "--no-project", "--quiet", "--with", "qrcode==8.0", "python", "-c", code],
                            env=env)
    if result.returncode != 0:
        print("  (Could not draw the QR code; type the address above into the phone's browser.)")
    elif QR_FILE.exists():
        print(f"  QR code also saved to {QR_FILE} (open it if the one above does not scan).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RailSaathi backend and frontend locally.")
    parser.add_argument("--backend-port", type=int, default=8010)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--skip-install", action="store_true", help="do not run uv sync / npm install")
    parser.add_argument("--no-https", action="store_true",
                        help="serve plain HTTP (phones then block camera, microphone and motion sensors)")
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
    scheme = "http" if args.no_https else "https"
    if not args.no_https:
        env["VITE_HTTPS"] = "1"  # self-signed certificate via @vitejs/plugin-basic-ssl (see vite.config.ts)

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
        app_url = f"{scheme}://localhost:{args.frontend_port}"
        if not wait_for(app_url, frontend, 60):
            sys.exit("The frontend did not start. Check the output above.")

        ip = lan_ip()
        print()
        print(f"  RailSaathi is running:  {app_url}")
        print(f"  API docs:               {backend_url}/docs")
        if ip:
            lan_url = f"{scheme}://{ip}:{args.frontend_port}"
            print(f"  On the same Wi-Fi:      {lan_url}")
            print()
            print("  Scan to open on a phone:")
            print_qr(uv, lan_url)
            if scheme == "https":
                print("  The phone will warn that the certificate is not trusted (it is a local test certificate):")
                print("  tap Advanced -> Proceed / Visit website. Camera, microphone and AR need this HTTPS address.")
            print("  Nothing loads on the phone? Allow Node.js through Windows Firewall on Private networks,")
            print("  set this Wi-Fi to a Private network, and avoid guest networks that isolate devices.")
        else:
            print("  No Wi-Fi address found; connect to a network to share the app with phones.")
        print()
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
