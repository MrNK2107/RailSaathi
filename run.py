"""Start RailSaathi locally: the FastAPI backend and the Vite frontend together.

    python run.py                  # backend on 8010, frontend on 5173 (HTTPS, open to your Wi-Fi)
    python run.py --no-https       # plain HTTP (camera, microphone and motion sensors won't work on phones)
    python run.py --backend-port 8000 --frontend-port 5174
    python run.py --public         # a production build behind a public Cloudflare quick-tunnel link (needs cloudflared)
    python run.py --warm-llm       # load the local Ollama model into memory before the demo starts

Installs dependencies on first run (uv sync, npm install), then runs both servers until Ctrl+C.
Prints a QR code for the Wi-Fi address so phones on the same network can open the app.
Needs Python 3.12, uv and Node.js 20+. No API keys: train data comes live from NTES through the unofficial
ntes-client package (RAILWAY_DATA_MODE=ntes). Set RAILWAY_DATA_MODE yourself (environment or backend/.env) to
override it, e.g. RAILWAY_DATA_MODE=demo for the built-in sample data.
"""

import argparse
import json
import os
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
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
DATA_MODE_VARS = ("RAILWAY_DATA_MODE", "DATA_PROVIDER")  # the backend's names for the setting (app/config.py)
LOCAL_DATA_MODE = "ntes"


def default_data_mode(environ: dict[str, str], env_file: Path = BACKEND / ".env") -> str | None:
    """`ntes` unless the data mode is already chosen in the environment or in backend/.env (then None: the user's
    choice stands)."""
    if any(environ.get(name, "").strip() for name in DATA_MODE_VARS):
        return None
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    except OSError:
        lines = []
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#") and key.strip().upper() in DATA_MODE_VARS and value.strip():
            return None
    return LOCAL_DATA_MODE


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


TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
CLOUDFLARED_HINT = ("cloudflared was not found. Install it: winget install Cloudflare.cloudflared (Windows), "
                    "brew install cloudflared (macOS).")
PUBLIC_NOTICE = "This link is public while RailSaathi runs: anyone with it can use the app. It changes every run."
LLM_VARS = ("LLM_PROVIDER", "LLM_FALLBACK", "OLLAMA_URL", "OLLAMA_MODEL")
LLM_DEFAULTS = {"LLM_PROVIDER": "", "LLM_FALLBACK": "", "OLLAMA_URL": "http://127.0.0.1:11434",
                "OLLAMA_MODEL": "gemma4:latest"}
NEEDED_RAM_GB = 10


def llm_settings(environ: dict[str, str], env_file: Path = BACKEND / ".env") -> dict[str, str]:
    """LLM_PROVIDER, LLM_FALLBACK, OLLAMA_URL, OLLAMA_MODEL from the environment, else backend/.env, else defaults."""
    found: dict[str, str] = {}
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    except OSError:
        lines = []
    for line in lines:
        key, sep, value = line.strip().partition("=")
        key = key.strip().upper()
        if sep and not key.startswith("#") and key in LLM_VARS and value.strip():
            found[key] = value.strip().strip("\"'")
    out = {name: environ.get(name, "").strip() or found.get(name, "") or LLM_DEFAULTS[name] for name in LLM_VARS}
    out["LLM_PROVIDER"] = out["LLM_PROVIDER"].lower()
    out["LLM_FALLBACK"] = out["LLM_FALLBACK"].lower()
    return out


def parse_tunnel_url(line: str) -> str | None:
    match = TUNNEL_URL.search(line)
    return match.group(0) if match else None


def start_tunnel(cloudflared: str, local_url: str) -> tuple[subprocess.Popen, str]:
    """Start a cloudflared quick tunnel to local_url and return it with its public URL (exits after 30 s without one)."""
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0
    proc = subprocess.Popen([cloudflared, "tunnel", "--url", local_url, "--no-autoupdate"], stderr=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                            creationflags=flags, start_new_session=not WINDOWS)
    found: list[str] = []

    def read() -> None:
        for line in proc.stderr:  # keeps draining so cloudflared never blocks on a full pipe
            url = parse_tunnel_url(line)
            if url and not found:
                found.append(url)

    threading.Thread(target=read, daemon=True).start()
    deadline = time.time() + 30
    while time.time() < deadline and not found and proc.poll() is None:
        time.sleep(0.2)
    if not found:
        stop(proc)
        sys.exit("cloudflared did not give a public link within 30 seconds. Check your connection and try again.")
    return proc, found[0]


def free_ram_bytes() -> int | None:
    """Free physical memory, or None where it cannot be read (macOS)."""
    try:
        if WINDOWS:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                            ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                            ("avail_ext", ctypes.c_ulonglong)]

            status = MemoryStatus()
            status.length = ctypes.sizeof(MemoryStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return int(status.avail_phys)
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            for line in meminfo.read_text().splitlines():
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, AttributeError):
        return None
    return None


def loaded_ollama_models(url: str) -> list[str]:
    """Names of the models Ollama holds in memory right now (GET /api/ps); [] on any error."""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/ps", timeout=2) as resp:
            data = json.load(resp)
        return [m.get("name", "?") for m in data.get("models", [])]
    except (OSError, ValueError, AttributeError):
        return []


def warm_llm(url: str, model: str) -> float:
    """Load the model into memory (empty prompt, kept 10 minutes) and return the seconds it took."""
    body = json.dumps({"model": model, "prompt": "", "keep_alive": "10m"}).encode()
    req = urllib.request.Request(f"{url.rstrip('/')}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=300) as resp:
        resp.read()
    return time.time() - started


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the RailSaathi backend and frontend locally.")
    parser.add_argument("--backend-port", type=int, default=8010)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--skip-install", action="store_true", help="do not run uv sync / npm install")
    parser.add_argument("--no-https", action="store_true",
                        help="serve plain HTTP (phones then block camera, microphone and motion sensors)")
    parser.add_argument("--public", action="store_true",
                        help="serve a production build and share it through a public Cloudflare quick-tunnel link")
    parser.add_argument("--skip-build", action="store_true",
                        help="with --public: reuse frontend/dist instead of building again")
    parser.add_argument("--warm-llm", action="store_true",
                        help="load the local Ollama model into memory before starting")
    return parser


def build_env(args: argparse.Namespace, environ: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ, BACKEND_URL=f"http://127.0.0.1:{args.backend_port}")
    if args.public:
        env["PUBLIC_TUNNEL"] = "1"
        env["VITE_ALLOWED_HOSTS"] = ".trycloudflare.com"
        env.pop("VITE_HTTPS", None)  # the tunnel terminates TLS with a real certificate
    elif not args.no_https:
        env["VITE_HTTPS"] = "1"  # self-signed certificate via @vitejs/plugin-basic-ssl (see vite.config.ts)
    return env


def backend_cmd(args: argparse.Namespace, uv: str) -> list[str]:
    cmd = [uv, "run", "python", "-m", "uvicorn", "app.main:create_app", "--factory"]
    if not args.public:
        cmd.append("--reload")  # a reload mid-demo would drop the in-memory state
    return cmd + ["--port", str(args.backend_port)]


def llm_warnings(settings: dict[str, str], public: bool, free_ram: int | None, loaded: list[str]) -> list[str]:
    provider, fallback = settings["LLM_PROVIDER"], settings["LLM_FALLBACK"]
    out = []
    if public and provider in ("gemini", "bedrock") and fallback != "ollama":
        out.append(f"Warning: the {provider} free quota can run out with many visitors and there is no local "
                   "fallback. Set LLM_FALLBACK=ollama (and start Ollama) so answers keep working.")
    if "ollama" in (provider, fallback) and free_ram is not None and free_ram < NEEDED_RAM_GB * 1024**3:
        out.append(f"Warning: {free_ram / 1024**3:.1f} GB RAM is free, about {NEEDED_RAM_GB} GB is needed for "
                   f"{settings['OLLAMA_MODEL']}. Close other apps or use a smaller model: OLLAMA_MODEL=llama3.2:3b")
    if len(loaded) > 1:
        out.append(f"Warning: Ollama has {len(loaded)} models loaded ({', '.join(loaded)}); each takes memory. "
                   "Stop the ones you do not need (ollama stop <model>).")
    return out


def main() -> None:
    args = make_parser().parse_args()
    if args.public:
        args.no_https = True  # the tunnel supplies HTTPS
    uv, npm, npx = tool("uv"), tool("npm"), tool("npx")
    cloudflared = None
    if args.public:
        cloudflared = shutil.which("cloudflared")
        if not cloudflared:
            sys.exit(CLOUDFLARED_HINT)
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
    env = build_env(args)
    mode = default_data_mode(env)
    if mode:
        env["RAILWAY_DATA_MODE"] = mode
    scheme = "http" if args.no_https else "https"

    settings = llm_settings(env)
    ollama_in_use = "ollama" in (settings["LLM_PROVIDER"], settings["LLM_FALLBACK"])
    if args.warm_llm and not ollama_in_use:
        print("--warm-llm: Ollama is neither LLM_PROVIDER nor LLM_FALLBACK, so there is nothing to warm.")
    elif args.warm_llm:
        print(f"Loading {settings['OLLAMA_MODEL']} into memory (the first load can take a minute)...")
        try:
            print(f"  Model ready in {warm_llm(settings['OLLAMA_URL'], settings['OLLAMA_MODEL']):.1f} s.")
        except OSError as exc:
            print(f"  Could not warm the model ({exc}). Is Ollama running at {settings['OLLAMA_URL']}?")
    loaded = loaded_ollama_models(settings["OLLAMA_URL"]) if ollama_in_use else []
    for warning in llm_warnings(settings, args.public, free_ram_bytes() if ollama_in_use else None, loaded):
        print(warning)

    if args.public and not (args.skip_build and (FRONTEND / "dist").exists()):
        print("Building the frontend (npx vite build)...")
        subprocess.run([npx, "vite", "build"], cwd=FRONTEND, env=env, check=True)

    backend = start(backend_cmd(args, uv), BACKEND, env)
    procs = [backend]
    try:
        print(f"Starting backend on {backend_url} ...")
        if not wait_for(f"{backend_url}/api/health", backend, 60):
            sys.exit("The backend did not start. Check the output above.")

        if args.public:  # a production build: far smaller and faster over the tunnel than the dev server
            front_cmd = [npx, "vite", "preview", "--port", str(args.frontend_port), "--strictPort",
                         "--host", "0.0.0.0"]
        else:
            front_cmd = [npx, "vite", "--port", str(args.frontend_port), "--strictPort"]
        frontend = start(front_cmd, FRONTEND, env)
        procs.append(frontend)
        app_url = f"{scheme}://localhost:{args.frontend_port}"
        if not wait_for(app_url, frontend, 60):
            sys.exit("The frontend did not start. Check the output above.")

        public_url = None
        if args.public:
            print("Opening the public tunnel ...")
            tunnel, public_url = start_tunnel(cloudflared, f"http://127.0.0.1:{args.frontend_port}")
            procs.append(tunnel)
        ip = lan_ip()
        print()
        if public_url:
            print(f"  Public link:            {public_url}")
            print(f"  {PUBLIC_NOTICE}")
            print()
            print("  Scan to open on any phone:")
            print_qr(uv, public_url)
            print()
        print(f"  RailSaathi is running:  {app_url}")
        print(f"  API docs:               {backend_url}/docs")
        if mode:
            print("  Train data:             live from NTES through ntes-client, an unofficial client "
                  "(RAILWAY_DATA_MODE=ntes)")
        else:
            print("  Train data:             RAILWAY_DATA_MODE as you set it")
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
