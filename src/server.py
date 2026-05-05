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

import os
import json
import subprocess
import sys
import threading
import time
import shutil
import urllib.request
import urllib.error
import socket
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
from flask_session import Session
from collections import deque
from gunicorn.app.base import BaseApplication
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

_data_env = os.environ.get("WATERBOT_DATA_DIR")
BASE_DIR = Path(_data_env)
DATA_DIR = BASE_DIR / "data"
APP_DIR = Path(__file__).parent.parent

DATA_DIR.mkdir(exist_ok=True, parents=True)
BASE_BOT_DIR = APP_DIR / "base_bot"
BOTS_DIR = BASE_DIR / "bots"
BOTS_DIR.mkdir(exist_ok=True, parents=True)
GLOBAL_CONFIG_FILE = DATA_DIR / "global_settings.json"
MAIN_PORT = 8221

DEFAULT_CONFIG = {
    "display_name": "",
    "system_message": "",
    "knowledge": [],
    "ai_model": "",
    "cheap_model": "",
    "image_model": "",
    "embeddings_model": "",
    "DISCORD_TOKEN": None,
    "autostart": False,
    "natural_replies_enabled": True,
    "natural_replies_frequency": 180,
    "context_size": 10,
    "rate_limit": 10,
    "rate_limit_message": "You are going too fast. Let me take a breath pls",
    "ban_message": "You have been banned from using {bot-name}. Further messages will be ignored.",
    "memory_limit": 500,
    "daily_message_limit": 50,
    "memory_top_k": 3,
    "knowledge_top_k": 3,
    "debug_mode": False,
    "other_options": {}
}

DEFAULT_GLOBAL_CONFIG = {
    "ai_provider": None,
    "api_keys": {},
    "discord_user_id": None,
    "web_ui_port": 8221,
    "app_settings": {
        "notifications": True,
        "autoRefresh": True,
        "visualEffects": True
    }
}

# Default models per provider
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_OPENROUTER_MODEL = "deepseek/deepseek-v3.2"
DEFAULT_OPENAI_EMBEDDINGS_MODEL = "text-embedding-3-small"
DEFAULT_OPENROUTER_EMBEDDINGS_MODEL = "openai/text-embedding-3-small"
DEFAULT_OPENROUTER_IMAGE_MODEL = "openai/gpt-5.4-mini"

app = Flask(__name__, static_folder='../static/assets', static_url_path='/assets')
CORS(app)

# Configure session
app.config['SECRET_KEY'] = os.urandom(24).hex() if not os.environ.get('WATERBOT_SECRET_KEY') else os.environ.get('WATERBOT_SECRET_KEY')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 days
app.config['SESSION_COOKIE_SECURE'] = False  # note to self: set to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
session_dir = DATA_DIR / 'sessions'
session_dir.mkdir(exist_ok=True, parents=True)
app.config['SESSION_FILE_DIR'] = str(session_dir)
Session(app)


def requires_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('authenticated'):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


def check_password_setup():
    try:
        config = load_global_config()
        return 'password_hash' in config and config['password_hash']
    except Exception:
        return False


def validate_discord_token(token: str) -> dict:
    """Validate a Discord bot token and return bot info + intent flags."""
    headers = {
        'Authorization': f'Bot {token}',
        'Content-Type': 'application/json',
        'User-Agent': 'BotManager/1.0'
    }

    try:
        req = urllib.request.Request('https://discord.com/api/v10/users/@me', headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            user_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"valid": False, "error": "Invalid token"}
        return {"valid": False, "error": f"Discord API error: {e.code}"}
    except Exception as e:
        return {"valid": False, "error": f"Could not reach Discord: {e}"}

    avatar_url = None
    if user_data.get('avatar'):
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/{user_data['id']}"
            f"/{user_data['avatar']}.png?size=128"
        )

    members_intent = None
    message_content_intent = None
    try:
        req = urllib.request.Request('https://discord.com/api/v10/applications/@me', headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            app_data = json.loads(resp.read())
        flags = app_data.get('flags', 0)
        # GATEWAY_GUILD_MEMBERS = 1<<14, GATEWAY_GUILD_MEMBERS_LIMITED = 1<<15
        members_intent = bool(flags & (1 << 14)) or bool(flags & (1 << 15))
        # GATEWAY_MESSAGE_CONTENT = 1<<18, GATEWAY_MESSAGE_CONTENT_LIMITED = 1<<19
        message_content_intent = bool(flags & (1 << 18)) or bool(flags & (1 << 19))
    except Exception:
        pass

    guild_count = None
    try:
        req = urllib.request.Request('https://discord.com/api/v10/users/@me/guilds', headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            guilds = json.loads(resp.read())
        guild_count = len(guilds)
    except Exception:
        pass

    return {
        "valid": True,
        "id": user_data.get('id'),
        "username": user_data.get('username'),
        "avatar_url": avatar_url,
        "guild_count": guild_count,
        "members_intent": members_intent,
        "message_content_intent": message_content_intent,
    }


def read_bot_meta(bot_dir: Path) -> dict:
    """Read bot_meta.json"""
    meta_file = bot_dir / "shared" / "bot_meta.json"
    if meta_file.exists():
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def write_bot_meta(bot_dir: Path, updates: dict):
    """Merge updates into bot_meta.json"""
    meta_file = bot_dir / "shared" / "bot_meta.json"
    meta = read_bot_meta(bot_dir)
    meta.update(updates)
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def load_global_config() -> dict:
    if GLOBAL_CONFIG_FILE.exists():
        try:
            with open(GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if "app_settings" not in config:
                config["app_settings"] = DEFAULT_GLOBAL_CONFIG["app_settings"].copy()
            return config
        except Exception:
            return {}
    return {}


def fetch_provider_models(provider: str, config: dict) -> list:
    provider = (provider or '').lower().strip()

    if provider == 'openrouter':
        api_keys = config.get('api_keys', {})
        api_key = api_keys.get('openrouter', '')
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        req = urllib.request.Request('https://openrouter.ai/api/v1/models', headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        models = []
        for model in data.get('data', []):
            arch = model.get('architecture', {})
            input_mod = arch.get('input_modalities', [])
            output_mod = arch.get('output_modalities', [])
            supported_params = model.get('supported_parameters', [])
            if 'text' in input_mod and 'text' in output_mod and 'tools' in supported_params:
                models.append(model.get('id', ''))
        return sorted(models)

    elif provider == 'openai':
        api_keys = config.get('api_keys', {})
        api_key = api_keys.get('openai', '')
        if not api_key:
            return []

        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        req = urllib.request.Request('https://api.openai.com/v1/models', headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        return sorted(m.get('id', '') for m in data.get('data', []))

    elif provider == 'ollama':
        ollama_url = (config.get('ollama_url') or 'http://localhost:11434').rstrip('/')
        req = urllib.request.Request(f'{ollama_url}/api/tags')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        return sorted(m.get('name', '') for m in data.get('models', []))

    return []


def normalize_model_for_provider(model: str, provider: str, available_models: list) -> str:
    model = (model or '').strip()
    provider = (provider or '').lower().strip()
    if not model:
        return ''

    if provider == 'openai':
        if model in available_models:
            return model
        if model.startswith('openai/'):
            candidate = model.split('/', 1)[1]
            if candidate in available_models:
                return candidate
        return ''

    if provider == 'openrouter':
        if model in available_models:
            return model
        # map unprefixed model to openrouter style
        if not model.startswith('openai/') and f'openai/{model}' in available_models:
            return f'openai/{model}'
        # normalize prefixed model that is supported
        if model.startswith('openai/') and model in available_models:
            return model
        return ''

    if provider == 'ollama':
        if model in available_models:
            return model
        return ''

    return model


def adjust_existing_bots_for_provider(provider: str, config: dict):
    provider = (provider or '').lower().strip()
    available_models = []
    try:
        available_models = fetch_provider_models(provider, config)
    except Exception:
        available_models = []

    for bot_dir in BOTS_DIR.iterdir():
        if not bot_dir.is_dir():
            continue

        settings_file = bot_dir / 'shared' / 'settings.json'
        if not settings_file.exists():
            continue

        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except Exception:
            continue

        current_model = (settings.get('ai_model') or '').strip()
        normalized_model = normalize_model_for_provider(current_model, provider, available_models)

        if normalized_model != current_model:
            settings['ai_model'] = normalized_model
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)


        current_model = (settings.get('embeddings_model') or '').strip()
        normalized_model = normalize_model_for_provider(current_model, provider, available_models)

        if normalized_model != current_model:
            settings['embeddings_model'] = normalized_model
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)

# Store running bot processes
bot_processes = {}

class BotProcess:
    def __init__(self, bot_path: Path):
        self.bot_path = bot_path
        self.name = bot_path.name
        self.log_path = bot_path / "logs"
        self.log_path.mkdir(exist_ok=True)
        self.log_file = self.log_path / "bot.log"
        self.process = None
        self._thread = None
        self.recent = deque(maxlen=1000)

    def start(self):
        if self.is_running():
            return
        env = os.environ.copy()
        env["GLOBAL_CONFIG_PATH"] = str(GLOBAL_CONFIG_FILE)
        
        # Check if bot.py exists
        bot_py = self.bot_path / "src" / "bot.py"
        if not bot_py.exists():
            raise FileNotFoundError(f"bot.py not found in {self.bot_path / 'src'}")
        
        self.process = subprocess.Popen(
            [sys.executable, "-u", "src/bot.py"],  # Add -u flag here
            cwd=str(self.bot_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            bufsize=1,
            universal_newlines=True
        )
        f = open(self.log_file, "a", encoding="utf-8")

        def reader():
            try:
                for line in self.process.stdout:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    entry = f"[{ts}] {line.rstrip()}"
                    f.write(entry + "\n")
                    f.flush()
                    self.recent.append(entry)
            finally:
                f.close()

        self._thread = threading.Thread(target=reader, daemon=True)
        self._thread.start()

    def stop(self):
        if not self.is_running():
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.process = None

    def is_running(self):
        return self.process is not None and self.process.poll() is None

    def tail(self, n=100):
        return list(self.recent)[-n:]

    def get_stats(self):
        if not self.is_running():
            return None
        try:
            import psutil
            p = psutil.Process(self.process.pid)
            return {
                "cpu": round(p.cpu_percent(interval=0.1), 1),
                "memory": round(p.memory_info().rss / (1024 * 1024), 1)
            }
        except Exception:
            return None


# API Endpoints

# Authentication Endpoints

@app.route('/api/auth/status', methods=['GET'])
def auth_status():
    password_set = check_password_setup()
    authenticated = session.get('authenticated', False)
    return jsonify({
        'authenticated': authenticated,
        'password_setup': password_set
    })


@app.route('/login.html')
def login_page():
    return send_from_directory('.', 'login.html')


@app.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.json or {}
        password = data.get('password', '').strip()
        
        if not password:
            return jsonify({"error": "Password is required"}), 400
        
        config = load_global_config()
        password_hash = config.get('password_hash')
        
        if not password_hash:
            return jsonify({"error": "Password not configured"}), 400
        
        if not check_password_hash(password_hash, password):
            return jsonify({"error": "Invalid password"}), 401
        
        session.permanent = True
        session['authenticated'] = True
        session.modified = True
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True})


def _deferred_exit(code: int = 0, delay: float = 0.25):
    import signal as _signal
    def shutdown():
        time.sleep(delay)
        try:
            os.kill(os.getppid(), _signal.SIGTERM)
        except Exception:
            pass
        os._exit(code)
    threading.Thread(target=shutdown, daemon=True).start()


def _deferred_restart(delay: float = 0.25):
    import signal as _signal
    def restart():
        time.sleep(delay)
        try:
            os.kill(os.getppid(), _signal.SIGHUP)
        except Exception:
            os._exit(0)
    threading.Thread(target=restart, daemon=True).start()


@app.route('/api/system/shutdown', methods=['POST'])
@requires_auth
def shutdown_system():
    _deferred_exit(0)
    return jsonify({"success": True, "message": "Shutting down WaterBot..."})


@app.route('/api/system/restart', methods=['POST'])
@requires_auth
def restart_system():
    _deferred_restart()
    return jsonify({"success": True, "message": "Restarting WaterBot..."})


# Regular Endpoints

@app.route('/')
def index():
    """Serve dashboard (protected by frontend auth check)"""
    return send_from_directory('.', 'bot-manager.html')

@app.route('/bot-settings.html')
def bot_settings():
    return send_from_directory('.', 'bot-settings.html')

@app.route('/docs.html')
def docs():
    return send_from_directory('.', 'docs.html')

@app.route('/api/global-config', methods=['GET'])
@requires_auth
def get_global_config():
    """Get global configuration"""
    if GLOBAL_CONFIG_FILE.exists():
        try:
            with open(GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            if "api_key" in config and "api_keys" not in config:
                provider = config.get("ai_provider") or "openai"
                config["api_keys"] = {provider: config.get("api_key")}
            if "api_keys" not in config:
                config["api_keys"] = {}
            if "app_settings" not in config:
                config["app_settings"] = DEFAULT_GLOBAL_CONFIG["app_settings"].copy()
            if "web_ui_port" not in config:
                config["web_ui_port"] = DEFAULT_GLOBAL_CONFIG["web_ui_port"]
            config.pop("password_hash", None)
            return jsonify(config)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify(dict(DEFAULT_GLOBAL_CONFIG))

@app.route('/api/global-config', methods=['POST'])
@requires_auth
def save_global_config():
    """Save global configuration"""
    try:
        config = request.json or {}
        old_config = load_global_config()

        if "app_settings" not in config:
            config["app_settings"] = DEFAULT_GLOBAL_CONFIG["app_settings"].copy()

        if "web_ui_port" not in config:
            config["web_ui_port"] = old_config.get("web_ui_port", DEFAULT_GLOBAL_CONFIG["web_ui_port"])

        new_password = (config.pop('password', '') or '').strip()
        config.pop('password_hash', None)
        if new_password:
            config['password_hash'] = generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=16)
        elif old_config.get('password_hash'):
            config['password_hash'] = old_config['password_hash']

        new_provider = (config.get('ai_provider') or '').lower().strip()
        old_provider = (old_config.get('ai_provider') or '').lower().strip()

        with open(GLOBAL_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        # If the AI provider changed, re-check existing bot models
        if new_provider and new_provider != old_provider:
            try:
                adjust_existing_bots_for_provider(new_provider, config)
            except Exception:
                pass

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/validate-token', methods=['POST'])
@requires_auth
def api_validate_token():
    """Validate a Discord bot token and return bot info."""
    token = (request.json or {}).get('token', '').strip()
    if not token:
        return jsonify({"valid": False, "error": "Token is required"}), 400
    result = validate_discord_token(token)
    return jsonify(result)


@app.route('/api/bots', methods=['GET'])
@requires_auth
def get_bots():
    """Get list of all bots"""
    refresh_meta = request.args.get('refreshMeta', 'false')
    refresh_meta = refresh_meta.lower() == 'true'

    bots = []
    for bot_dir in BOTS_DIR.iterdir():
        if bot_dir.is_dir():
            settings_file = bot_dir / "shared" / "settings.json"
            bot_data = {
                "id": bot_dir.name,
                "name": bot_dir.name,
                "running": bot_dir.name in bot_processes and bot_processes[bot_dir.name].is_running()
            }

            # Load settings
            if settings_file.exists():
                try:
                    with open(settings_file, 'r', encoding='utf-8') as f:
                        settings = json.load(f)
                        bot_data.update({
                            "displayName": settings.get("display_name", ""),
                            "systemMessage": settings.get("system_message", ""),
                            "aiModel": settings.get("ai_model"),
                            "cheapModel": settings.get("cheap_model", ""),
                            "imageModel": settings.get("image_model", ""),
                            "embeddingsModel": settings.get("embeddings_model", ""),
                            "discordToken": settings.get("DISCORD_TOKEN", ""),
                            "autostart": settings.get("autostart", False),
                            "knowledge": settings.get("knowledge", []),
                            "naturalRepliesEnabled": settings.get("natural_replies_enabled", True),
                            "naturalRepliesFrequency": settings.get("natural_replies_frequency", 180),
                            "contextSize": settings.get("context_size", 10),
                            "rateLimit": settings.get("rate_limit", 10),
                            "rateLimitMessage": settings.get("rate_limit_message", "You are going too fast. Let me take a breath pls"),
                            "banMessage": settings.get("ban_message", "You have been banned from using {bot-name}. Further messages will be ignored."),
                            "memoryLimit": settings.get("memory_limit", 500),
                            "dailyMessageLimit": settings.get("daily_message_limit", 50),
                            "memoryTopK": settings.get("memory_top_k", 3),
                            "knowledgeTopK": settings.get("knowledge_top_k", 3),
                            "debugMode": settings.get("debug_mode", False)
                        })
                except Exception:
                    pass

            # Load meta
            if refresh_meta and bot_data.get("discordToken"):
                try:
                    discord_info = validate_discord_token(bot_data["discordToken"])
                    if discord_info.get("valid"):
                        write_bot_meta(bot_dir, {
                            "discord_id": discord_info.get("id"),
                            "discord_username": discord_info.get("username"),
                            "discord_avatar_url": discord_info.get("avatar_url"),
                            "discord_guild_count": discord_info.get("guild_count"),
                        })
                except Exception:
                    pass

            meta = read_bot_meta(bot_dir)
            bot_data["lastStarted"] = meta.get("last_started")
            bot_data["discordBotId"] = meta.get("discord_id")
            bot_data["discordUsername"] = meta.get("discord_username")
            bot_data["discordAvatarUrl"] = meta.get("discord_avatar_url")
            bot_data["discordGuildCount"] = meta.get("discord_guild_count")
            bot_data["users"] = meta.get("unique_users")

            # Get stats if running
            if bot_data["running"]:
                bot_process = bot_processes[bot_dir.name]
                stats = bot_process.get_stats()
                bot_data["stats"] = stats

            bots.append(bot_data)

    bots.sort(
        key=lambda b: b.get("lastStarted") or "",
        reverse=True
    )

    return jsonify(bots)

@app.route('/api/bots', methods=['POST'])
@requires_auth
def create_bot():
    """Create a new bot"""
    try:
        data = request.json
        bot_name = data.get('name', '').strip()
        
        if not bot_name:
            return jsonify({"error": "Bot name is required"}), 400
        
        # Sanitize bot name
        import re
        import unicodedata
        bot_name = unicodedata.normalize("NFKD", bot_name)
        bot_name = bot_name.encode("ascii", "ignore").decode("ascii")
        bot_name = bot_name.lower()
        bot_name = re.sub(r"\s+", "-", bot_name)
        bot_name = re.sub(r"[^a-z0-9_-]", "", bot_name)
        bot_name = re.sub(r"-+", "-", bot_name).strip("-_")
        
        bot_dir = BOTS_DIR / bot_name
        src_dir = bot_dir / "src"
        shared_dir = bot_dir / "shared"
        
        if bot_dir.exists():
            return jsonify({"error": "Bot already exists"}), 400
        
        # Create bot directory
        bot_dir.mkdir(parents=True, exist_ok=True)
        src_dir.mkdir(exist_ok=True)
        shared_dir.mkdir(exist_ok=True)
        
        # Determine provider model behavior
        global_config = load_global_config()
        provider = (global_config.get('ai_provider') or '').lower().strip()
        requested_model = (data.get('aiModel') or '').strip()

        if provider == 'ollama':
            if not requested_model:
                return jsonify({"error": "AI model is required for Ollama provider"}), 400
            chosen_model = requested_model
            requested_embeddings = (data.get('embeddingsModel') or '').strip()
            if not requested_embeddings:
                return jsonify({"error": "Embeddings model is required for Ollama provider"}), 400
            chosen_embeddings = requested_embeddings
        elif provider == 'openrouter':
            chosen_model = requested_model or DEFAULT_OPENROUTER_MODEL
            chosen_embeddings = (data.get('embeddingsModel') or '').strip() or DEFAULT_OPENROUTER_EMBEDDINGS_MODEL
            chosen_image_model = DEFAULT_OPENROUTER_IMAGE_MODEL
        elif provider == 'openai':
            chosen_model = requested_model or DEFAULT_OPENAI_MODEL
            chosen_embeddings = (data.get('embeddingsModel') or '').strip() or DEFAULT_OPENAI_EMBEDDINGS_MODEL
        else:
            chosen_model = requested_model or ''
            chosen_embeddings = (data.get('embeddingsModel') or '').strip()

        # Create settings.json
        settings = {
            "display_name": data.get('displayName', ''),
            "system_message": data.get('systemMessage', ''),
            "knowledge": data.get('knowledge', []),
            "ai_model": chosen_model,
            "cheap_model": (data.get('cheapModel') or '').strip(),
            "image_model": chosen_image_model if chosen_image_model else (data.get('imageModel') or '').strip(),
            "embeddings_model": chosen_embeddings,
            "DISCORD_TOKEN": data.get('discordToken', None),
            "autostart": data.get('autostart', False),
            "natural_replies_enabled": data.get('naturalRepliesEnabled', True),
            "natural_replies_frequency": data.get('naturalRepliesFrequency', 180),
            "context_size": data.get('contextSize', 10),
            "rate_limit": data.get('rateLimit', 10),
            "rate_limit_message": data.get('rateLimitMessage', 'You are going too fast. Let me take a breath pls'),
            "ban_message": data.get('banMessage', 'You have been banned from using {bot-name}. Further messages will be ignored.'),
            "memory_limit": data.get('memoryLimit', 500),
            "memory_top_k": data.get('memoryTopK', 3),
            "knowledge_top_k": data.get('knowledgeTopK', 3),
            "debug_mode": data.get('debugMode', False),
            "other_options": {}
        }
        
        settings_file = shared_dir / "settings.json"
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        
        shutil.copytree(BASE_BOT_DIR, src_dir, dirs_exist_ok=True)

        # Cache Discord info in bot_meta.json
        discord_token = data.get('discordToken', '')
        if discord_token:
            try:
                discord_info = validate_discord_token(discord_token)
                if discord_info.get('valid'):
                    write_bot_meta(bot_dir, {
                        "discord_username": discord_info.get("username"),
                        "discord_avatar_url": discord_info.get("avatar_url"),
                        "discord_guild_count": discord_info.get("guild_count"),
                    })
            except Exception:
                pass

        return jsonify({"success": True, "name": bot_name})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bots/<bot_id>', methods=['PUT'])
@requires_auth
def update_bot(bot_id):
    """Update bot settings"""
    try:
        bot_dir = BOTS_DIR / bot_id
        if not bot_dir.exists():
            return jsonify({"error": "Bot not found"}), 404
        
        data = request.json
        settings_file = bot_dir / "shared" / "settings.json"
        
        # Load existing settings or use defaults
        if settings_file.exists():
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        else:
            settings = DEFAULT_CONFIG.copy()
        
        # Update settings
        settings.update({
            "display_name": data.get('displayName', ''),
            "system_message": data.get('systemMessage', ''),
            "knowledge": data.get('knowledge', []),
            "ai_model": data.get('aiModel', ''),
            "cheap_model": (data.get('cheapModel') or '').strip(),
            "image_model": (data.get('imageModel') or '').strip(),
            "embeddings_model": (data.get('embeddingsModel') or '').strip(),
            "DISCORD_TOKEN": data.get('discordToken', None),
            "autostart": data.get('autostart', False),
            "natural_replies_enabled": data.get('naturalRepliesEnabled', True),
            "natural_replies_frequency": data.get('naturalRepliesFrequency', 180),
            "context_size": data.get('contextSize', 10),
            "rate_limit": data.get('rateLimit', 10),
            "rate_limit_message": data.get('rateLimitMessage', 'You are going too fast. Let me take a breath pls'),
            "ban_message": data.get('banMessage', 'You have been banned from using {bot-name}. Further messages will be ignored.'),
            "memory_limit": data.get('memoryLimit', 500),
            "daily_message_limit": data.get('dailyMessageLimit', 50),
            "memory_top_k": data.get('memoryTopK', 3),
            "knowledge_top_k": data.get('knowledgeTopK', 3),
            "debug_mode": data.get('debugMode', False)
        })
        
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)

        # Refresh Discord info cache if token was updated
        new_token = data.get('discordToken', '')
        if new_token:
            try:
                discord_info = validate_discord_token(new_token)
                if discord_info.get('valid'):
                    write_bot_meta(bot_dir, {
                        "discord_username": discord_info.get("username"),
                        "discord_avatar_url": discord_info.get("avatar_url"),
                        "discord_guild_count": discord_info.get("guild_count"),
                    })
            except Exception:
                pass

        return jsonify({"success": True})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bots/<bot_id>', methods=['DELETE'])
@requires_auth
def delete_bot(bot_id):
    """Delete a bot"""
    try:
        bot_dir = BOTS_DIR / bot_id
        if not bot_dir.exists():
            return jsonify({"error": "Bot not found"}), 404
        
        # Stop bot if running
        if bot_id in bot_processes:
            bot_processes[bot_id].stop()
            del bot_processes[bot_id]
        
        # Delete directory
        import shutil
        shutil.rmtree(bot_dir)
        
        return jsonify({"success": True})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bots/<bot_id>/start', methods=['POST'])
@requires_auth
def start_bot(bot_id):
    """Start a bot"""
    try:
        bot_dir = BOTS_DIR / bot_id
        if not bot_dir.exists():
            return jsonify({"error": "Bot not found"}), 404
        
        if bot_id not in bot_processes:
            bot_processes[bot_id] = BotProcess(bot_dir)
        
        if bot_processes[bot_id].is_running():
            return jsonify({"error": "Bot is already running"}), 400
        
        bot_processes[bot_id].start()

        try:
            write_bot_meta(bot_dir, {"last_started": time.strftime("%Y-%m-%dT%H:%M:%S")})
        except Exception:
            pass

        return jsonify({"success": True})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bots/<bot_id>/stop', methods=['POST'])
@requires_auth
def stop_bot(bot_id):
    """Stop a bot"""
    try:
        if bot_id not in bot_processes:
            return jsonify({"error": "Bot is not running"}), 400
        
        bot_processes[bot_id].stop()
        return jsonify({"success": True})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bots/<bot_id>/restart', methods=['POST'])
@requires_auth
def restart_bot(bot_id):
    """Restart a bot"""
    try:
        bot_dir = BOTS_DIR / bot_id
        if not bot_dir.exists():
            return jsonify({"error": "Bot not found"}), 404

        if bot_id in bot_processes:
            bot_processes[bot_id].stop()

        if bot_id not in bot_processes:
            bot_processes[bot_id] = BotProcess(bot_dir)

        bot_processes[bot_id].start()

        try:
            write_bot_meta(bot_dir, {"last_started": time.strftime("%Y-%m-%dT%H:%M:%S")})
        except Exception:
            pass

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/bots/<bot_id>/logs', methods=['GET'])
@requires_auth
def get_bot_logs(bot_id):
    """Get bot logs"""
    try:
        bot_dir = BOTS_DIR / bot_id
        if not bot_dir.exists():
            return jsonify({"error": "Bot not found"}), 404
        
        logs = []
        
        # Get recent logs from running bot
        if bot_id in bot_processes:
            logs = bot_processes[bot_id].tail(100)
        
        # Also read from log file if exists
        log_file = bot_dir / "logs" / "bot.log"
        if log_file.exists() and len(logs) == 0:
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    logs = [line.rstrip() for line in lines[-100:]]
            except Exception:
                pass
        
        return jsonify({"logs": logs})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/bots/<bot_id>/stats', methods=['GET'])
@requires_auth
def get_bot_stats(bot_id):
    """Get comprehensive statistics for a bot"""
    try:
        bot_dir = BOTS_DIR / bot_id
        if not bot_dir.exists():
            return jsonify({"error": "Bot not found"}), 404

        # Debug logging
        print(f"DEBUG: Getting stats for bot_id={bot_id}")
        print(f"DEBUG: bot_id in bot_processes: {bot_id in bot_processes}")
        print(f"DEBUG: Available bot processes: {list(bot_processes.keys())}")
        if bot_id in bot_processes:
            print(f"DEBUG: bot_processes[{bot_id}].is_running() = {bot_processes[bot_id].is_running()}")

        data_dir = bot_dir / "data"
        stats = {
            "system": {},
            "growth": {},
            "engagement": {},
            "storage": {}
        }

        if bot_id in bot_processes and bot_processes[bot_id].is_running():
            try:
                import psutil
                p = psutil.Process(bot_processes[bot_id].process.pid)
                uptime_seconds = time.time() - p.create_time()
                stats["system"] = {
                    "cpu": round(p.cpu_percent(interval=0.1), 1),
                    "memory_mb": round(p.memory_info().rss / (1024 * 1024), 1),
                    "uptime_seconds": int(uptime_seconds),
                    "uptime_display": f"{int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m"
                }
            except Exception as e:
                print(f"Error getting system stats for bot {bot_id}: {e}")

        try:
            import sys
            import importlib.util

            storage_path = bot_dir / "src" / "storage.py"
            if storage_path.exists():
                spec = importlib.util.spec_from_file_location("storage", storage_path)
                storage_module = importlib.util.module_from_spec(spec)

                old_cwd = os.getcwd()
                os.chdir(bot_dir)

                try:
                    spec.loader.exec_module(storage_module)

                    user_metrics = storage_module.load_user_metrics() or {}
                    daily_counts = storage_module.load_daily_counts() or {}
                    user_count = len(user_metrics)
                    message_count = sum(
                        int(v.get('messages', 0)) if isinstance(v, dict) else int(v)
                        for v in user_metrics.values()
                    ) if user_metrics else 0

                    stats["growth"] = {
                        "user_count": user_count,
                        "message_count": message_count,
                        "daily_messages": daily_counts
                    }

                    avg_messages_per_user = message_count / user_count if user_count > 0 else 0

                    avg_daily_messages_latest = 0
                    if isinstance(daily_counts, dict):
                        date_keys = [k for k in daily_counts.keys() if not str(k).startswith('_')]
                        if date_keys:
                            latest_date = sorted(date_keys)[-1]
                            latest_data = daily_counts.get(latest_date) or {}
                            counts = []
                            for v in latest_data.values():
                                try:
                                    c = int(v)
                                except Exception:
                                    continue
                                if c > 0:
                                    counts.append(c)
                            if counts:
                                avg_daily_messages_latest = round(sum(counts) / len(counts), 2)

                    stats["engagement"] = {
                        "avg_messages_per_user": round(avg_messages_per_user, 2),
                        "avg_daily_messages_latest": avg_daily_messages_latest,
                        "daily_messages": daily_counts
                    }

                    freewill_attempts = storage_module.get_freewill_attempts() or {}
                    recent_questions = storage_module.load_recent_questions() or {}
                    daily_quiz = storage_module.load_daily_quiz_records() or {}
                    server_settings = storage_module.load_settings() or {}

                    stats["storage"] = {
                        "user_count": user_count,
                        "daily_quiz_records": len(daily_quiz),
                        "server_settings": len(server_settings),
                        "user_metrics": len(user_metrics),
                        "freewill_entries": len(freewill_attempts),
                        "recent_questions": len(recent_questions)
                    }
                finally:
                    os.chdir(old_cwd)
        except Exception as e:
            print(f"Error loading bot stats: {e}")

        return jsonify(stats)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/models', methods=['GET'])
@requires_auth
def get_models():
    """Fetch available models from the configured AI provider"""
    try:
        if not GLOBAL_CONFIG_FILE.exists():
            return jsonify({"error": "No global config found. Configure a provider in global settings first."}), 400

        with open(GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)

        provider = (config.get('ai_provider') or '').lower().strip()
        api_keys = config.get('api_keys', {})

        # Handle legacy single api_key field
        if not api_keys and config.get('api_key'):
            api_keys = {provider: config['api_key']}

        if provider == 'openrouter':
            api_key = api_keys.get('openrouter', '')
            headers = {'Content-Type': 'application/json'}
            if api_key:
                headers['Authorization'] = f'Bearer {api_key}'

            req = urllib.request.Request(
                'https://openrouter.ai/api/v1/models',
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            models = []
            for model in data.get('data', []):
                arch = model.get('architecture', {})
                input_mod = arch.get('input_modalities', [])
                output_mod = arch.get('output_modalities', [])
                supported_params = model.get('supported_parameters', [])

                if (
                    'text' in input_mod and
                    'text' in output_mod and
                    'tools' in supported_params
                ):
                    models.append(model.get('id', ''))

            return jsonify({'models': sorted(models), 'provider': 'openrouter'})

        elif provider == 'openai':
            api_key = api_keys.get('openai', '')
            if not api_key:
                return jsonify({"error": "No OpenAI API key configured in global settings."}), 400

            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }
            req = urllib.request.Request(
                'https://api.openai.com/v1/models',
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            models = sorted(m.get('id', '') for m in data.get('data', []))
            return jsonify({'models': models, 'provider': 'openai'})

        elif provider == 'ollama':
            ollama_url = (config.get('ollama_url') or 'http://localhost:11434').rstrip('/')
            req = urllib.request.Request(f'{ollama_url}/api/tags')
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            models = sorted(m.get('name', '') for m in data.get('models', []))
            return jsonify({'models': models, 'provider': 'ollama'})

        else:
            msg = "No AI provider configured." if not provider else f"Unknown provider: '{provider}'."
            return jsonify({"error": f"{msg} Configure a provider in global settings first."}), 400

    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            pass
        return jsonify({"error": f"Provider API error {e.code}: {body or e.reason}"}), 502
    except urllib.error.URLError as e:
        return jsonify({"error": f"Could not reach provider: {e.reason}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/models/embeddings', methods=['GET'])
@requires_auth
def get_embedding_models():
    """Fetch embedding-capable models from the configured AI provider"""
    try:
        if not GLOBAL_CONFIG_FILE.exists():
            return jsonify({"error": "No global config found. Configure a provider in global settings first."}), 400

        with open(GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)

        provider = (config.get('ai_provider') or '').lower().strip()
        api_keys = config.get('api_keys', {})

        if not api_keys and config.get('api_key'):
            api_keys = {provider: config['api_key']}

        if provider == 'openrouter':
            req = urllib.request.Request(
                'https://openrouter.ai/api/v1/embeddings/models',
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            models = []
            for model in data.get('data', []):
                arch = model.get('architecture', {})
                output_mod = arch.get('output_modalities', [])
                if 'embeddings' in output_mod:
                    models.append(model.get('id', ''))

            return jsonify({'models': sorted(models), 'provider': 'openrouter'})

        elif provider == 'openai':
            api_key = api_keys.get('openai', '')
            if not api_key:
                return jsonify({"error": "No OpenAI API key configured in global settings."}), 400

            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }
            req = urllib.request.Request(
                'https://api.openai.com/v1/models',
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            # openai too lazy to add proper metadata, so just filter by name
            models = sorted(
                m.get('id', '') for m in data.get('data', [])
                if m.get('id', '').startswith('text-embedding-')
            )
            return jsonify({'models': models, 'provider': 'openai'})

        elif provider == 'ollama':
            ollama_url = (config.get('ollama_url') or 'http://localhost:11434').rstrip('/')
            req = urllib.request.Request(f'{ollama_url}/api/tags')
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            # ollama even more lazy than openai, so just return everything and let user figure it out
            models = sorted(m.get('name', '') for m in data.get('models', []))
            return jsonify({'models': models, 'provider': 'ollama'})

        else:
            msg = "No AI provider configured." if not provider else f"Unknown provider: '{provider}'."
            return jsonify({"error": f"{msg} Configure a provider in global settings first."}), 400

    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', errors='replace')[:200]
        except Exception:
            pass
        return jsonify({"error": f"Provider API error {e.code}: {body or e.reason}"}), 502
    except urllib.error.URLError as e:
        return jsonify({"error": f"Could not reach provider: {e.reason}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/version', methods=['GET'])
def get_version():
    try:
        from src import __version__
        return jsonify({'version': __version__})
    except ImportError:
        return jsonify({'version': 'unknown'})



def autostart_enabled_bots():
    """Start all bots with autostart enabled"""
    for bot_dir in BOTS_DIR.iterdir():
        if not bot_dir.is_dir():
            continue

        settings_file = bot_dir / "shared" / "settings.json"
        if not settings_file.exists():
            continue

        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)

            if settings.get("autostart", False):
                bot_id = bot_dir.name
                if bot_id not in bot_processes:
                    bot_processes[bot_id] = BotProcess(bot_dir)

                if not bot_processes[bot_id].is_running():
                    print(f"Autostarting bot: {bot_id}")
                    bot_processes[bot_id].start()
                    try:
                        write_bot_meta(bot_dir, {"last_started": time.strftime("%Y-%m-%dT%H:%M:%S")})
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error autostarting bot {bot_dir.name}: {e}")


def cleanup():
    """Stop all running bots on shutdown"""
    for bot_process in bot_processes.values():
        bot_process.stop()


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "localhost"


import atexit
atexit.register(cleanup)

def get_configured_port() -> int:
    try:
        if GLOBAL_CONFIG_FILE.exists():
            with open(GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config.get("web_ui_port", MAIN_PORT)
    except Exception:
        pass
    return MAIN_PORT

print("WaterBot Server starting...")
print("Bots directory:", BOTS_DIR)
print("Global config:", GLOBAL_CONFIG_FILE)

autostart_enabled_bots()

configured_port = get_configured_port()
print(f"\n✅ Dashboard is running at http://{get_local_ip()}:{configured_port}\n")


if __name__ == '__main__':
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
        'bind':         f'0.0.0.0:{configured_port}',
        'workers':      1,
        'threads':      4,
        'worker_class': 'sync',
    }).run()