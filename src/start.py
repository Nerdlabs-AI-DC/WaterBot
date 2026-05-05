"""
WaterBot - AI Discord bot manager
Copyright (C) 2026  Nerdlabs AI

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import socket
from pathlib import Path
from gunicorn.app.base import BaseApplication
from werkzeug.security import generate_password_hash

BASE_DIR  = Path(__file__).parent.parent

_data_env = os.environ.get("WATERBOT_DATA_DIR")
DATA_DIR = Path(_data_env) / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

GLOBAL_CONFIG_FILE = DATA_DIR / "global_settings.json"
SERVER_PY          = Path(__file__).parent / "server.py"
STATIC_DIR         = Path(__file__).parent

ONBOARD_PORT = 8222
MAIN_PORT    = 8221


# Helpers

def is_configured() -> bool:
    if not GLOBAL_CONFIG_FILE.exists():
        return False
    try:
        with open(GLOBAL_CONFIG_FILE, encoding="utf-8") as f:
            config = json.load(f)
        return bool((config.get("ai_provider") or "").strip())
    except Exception:
        return False


def launch_server(port: int | None = None) -> subprocess.Popen:
    if port is None:
        if GLOBAL_CONFIG_FILE.exists():
            try:
                with open(GLOBAL_CONFIG_FILE, encoding="utf-8") as f:
                    config = json.load(f)
                port = config.get("web_ui_port", MAIN_PORT)
            except Exception:
                port = MAIN_PORT
        else:
            port = MAIN_PORT
    
    return subprocess.Popen(
        [
            "gunicorn",
            "-w", "1",
            "--threads", "4",
            "-b", f"0.0.0.0:{port}",
            "server:app",
        ],
        cwd=str(SERVER_PY.parent),
    )


def wait_for_server(port: int = MAIN_PORT, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(
                f"http://localhost:{port}/api/global-config", timeout=2
            )
            return True
        except Exception:
            time.sleep(0.5)
    return False


def build_config(data: dict) -> dict:
    provider    = (data.get("provider") or "").lower().strip()
    api_key     = (data.get("api_key") or "").strip()
    base_url    = (data.get("base_url") or "").strip()
    password    = (data.get("password") or "").strip()
    user_id     = (data.get("discord_user_id") or "").strip() or None
    web_ui_port = int(data.get("web_ui_port", 8221)) if data.get("web_ui_port") else 8221
    app_settings = data.get("app_settings") or {
        "notifications": True,
        "autoRefresh":   True,
        "visualEffects": True,
    }

    config: dict = {
        "ai_provider":    provider,
        "api_keys":       {},
        "discord_user_id": user_id,
        "web_ui_port":    web_ui_port,
        "app_settings":   app_settings,
    }

    if password:
        config["password_hash"] = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

    if provider == "ollama":
        if api_key:
            config["ollama_url"] = api_key
    else:
        if api_key:
            config["api_keys"][provider] = api_key

    if provider == "openai" and base_url:
        config["openai_endpoint"] = base_url

    return config

def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "localhost"

# Already configured

if is_configured():
    print("WaterBot: configuration found - starting server…")
    proc = launch_server()
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    sys.exit(proc.returncode or 0)


# Onboarding

try:
    from flask import Flask, Response, jsonify, request, send_from_directory
    from flask_cors import CORS
except ImportError:
    print("ERROR: Flask is required.  Install it with:  pip install flask flask-cors")
    sys.exit(1)

app = Flask(__name__, static_folder='../static/assets', static_url_path='/assets')
CORS(app)

# Shared state
_server_proc: subprocess.Popen | None = None
_save_lock = threading.Lock()


def _setup_signal_forwarding():
    def _handler(sig, frame):
        if _server_proc:
            _server_proc.terminate()
            _server_proc.wait()
        sys.exit(0)
    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


@app.route("/")
def index():
    return send_from_directory(str(STATIC_DIR), "onboarding.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(str(STATIC_DIR), filename)


@app.route("/api/setup/save", methods=["POST"])
def setup_save():
    with _save_lock:
        try:
            data   = request.get_json(force=True) or {}
            config = build_config(data)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(GLOBAL_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/setup/launch-stream")
def launch_stream():
    def _event(msg: str, pct: int, *, done: bool = False, error: bool = False, **kwargs) -> str:
        payload = {"msg": msg, "pct": pct, "done": done, "error": error}
        payload.update(kwargs)
        return f"data: {json.dumps(payload)}\n\n"

    def generate():
        global _server_proc

        yield _event("Verifying configuration…", 10)
        time.sleep(0.3)

        if not GLOBAL_CONFIG_FILE.exists():
            yield _event("Config file not found. Did /api/setup/save succeed?", 10, error=True)
            return

        try:
            with open(GLOBAL_CONFIG_FILE, encoding="utf-8") as f:
                config = json.load(f)
            configured_port = config.get("web_ui_port", MAIN_PORT)
        except Exception:
            configured_port = MAIN_PORT

        yield _event("Starting server…", 30)
        time.sleep(0.3)

        try:
            _server_proc = launch_server(port=configured_port)
        except Exception as exc:
            yield _event(f"Failed to start server: {exc}", 30, error=True)
            return

        yield _event("Connecting to services…", 50)

        ready = wait_for_server(port=configured_port, timeout=30)
        if not ready:
            yield _event(
                "Server is taking too long to start. "
                "Check the terminal for errors.",
                50, error=True,
            )
            return

        yield _event("Checking AI provider…", 72)
        time.sleep(0.4)

        try:
            req = urllib.request.Request(
                f"http://localhost:{configured_port}/api/global-config"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                saved = json.loads(resp.read())
            if not saved.get("ai_provider"):
                yield _event("Config was not saved correctly.", 72, error=True)
                return
        except Exception as exc:
            yield _event(f"Could not verify config: {exc}", 72, error=True)
            return

        yield _event("Preparing dashboard…", 90)
        time.sleep(0.5)

        yield _event("Launching dashboard…", 100, done=True, web_ui_port=configured_port)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main():
    _setup_signal_forwarding()
    print("\nWelcome to WaterBot!")
    print("Since this is your first time running WaterBot, let's get you set up.")
    print(f"To get started, open your browser and go to: http://{get_local_ip()}:{ONBOARD_PORT}\n")

    class _StandaloneApp(BaseApplication):
        def __init__(self, application, options=None):
            self.options = options or {}
            self.application = application
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    _StandaloneApp(app, {
        'bind':         f'0.0.0.0:{ONBOARD_PORT}',
        'workers':      1,
        'threads':      4,
        'worker_class': 'sync',
    }).run()


if __name__ == "__main__":
    main()