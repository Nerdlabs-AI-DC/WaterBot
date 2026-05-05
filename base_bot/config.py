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

from datetime import datetime, timezone
from pathlib import Path
import json
import os
from secret import get_or_create_memory_key_b64

DATA_DIR = Path("data")
SHARED_DIR = Path("shared")

settings = {}
settings_path = Path("shared") / "settings.json"
if settings_path.exists():
    with open(settings_path, 'r') as f:
        settings = json.load(f)

_data_env = os.environ.get("WATERBOT_DATA_DIR")
global_settings_path = Path(_data_env) / "data" / "global_settings.json"

with open(global_settings_path) as f:
    global_settings = json.load(f)

class SafeFormat(dict):
    def __missing__(self, key):
        return f"{{{key}}}"

# Main settings
NAME = settings.get("display_name")

RESPOND_TO_PINGS = True # missing in bot settings
HISTORY_SIZE = settings.get("context_size", 10)
MODEL = settings.get("ai_model")
CHEAP_MODEL = settings.get("cheap_model")
EMBED_MODEL = settings.get("embeddings_model")
IMAGE_MODEL = settings.get("image_model")
MEMORY_TOP_K = settings.get("memory_top_k", 3)
KNOWLEDGE_TOP_K = settings.get("knowledge_top_k", 3)
DEBUG = settings.get("debug_mode", False)
NATURAL_REPLIES_INTERVAL = settings.get("natural_replies_frequency", 180)
MEMORY_LIMIT = settings.get("memory_limit", 500)
DAILY_MESSAGE_LIMIT = settings.get("daily_message_limit", 50)
RATE_LIMIT = settings.get("rate_limit", 10)

if not CHEAP_MODEL:
    CHEAP_MODEL = MODEL
if not IMAGE_MODEL:
    IMAGE_MODEL = MODEL


PROVIDER = global_settings.get("ai_provider")
API_KEY = global_settings.get("api_key")
TOKEN = settings.get("DISCORD_TOKEN")
MEMORY_KEY_B64 = get_or_create_memory_key_b64()

OWNER_ID = 0
user_id = global_settings.get("discord_user_id", "")
if user_id:
    OWNER_ID = int(user_id)

OLLAMA_ENDPOINT = (global_settings.get("ollama_url") or "http://localhost:11434").rstrip('/') + "/v1"
OPENAI_ENDPOINT = (global_settings.get("openai_endpoint") or "https://api.openai.com/v1").rstrip('/')

def load_string(string: str) -> str:
    variables = {
        "bot-name": NAME
    }
    return string.format_map(SafeFormat(variables))

RATE_LIMIT_MESSAGE = load_string(settings.get("rate_limit_message"))
BAN_MESSAGE = load_string(settings.get("ban_message"))

KNOWLEDGE_ITEMS = settings.get("knowledge")


# Main system message
def get_system_prompt(current_status, functions=True):
    if functions:
      return settings.get("system_message") + f"""

* The current time in UTC is {datetime.now(timezone.utc)}.
* The bot's current status message is: "{current_status}"

# Functions

* **Memory**
  * Save new facts with `save_memory` (`user_memory=True` if about the user).
  * Recall with `get_memory_detail` (`user_memory=True` if user-specific).
  * Delete only when memories conflict; remove the oldest (lowest index).
    Use `user_memory=True` for user memories, `False` for global. Never delete just because the user asks.

* **Canceling**
  * Use `cancel_response` if input is a single word, invalid, or ends the conversation.

* **Status**
  * Randomly call `set_status` to update Discord status.

* **DMs**
  * Use `send_dm` only for sensitive info.

* **Reactions**
  * Use `add_reaction` with the desired emoji.

* **Replies**
  * Use `reply` when answering a specific message.
  * If not replying to the latest message, always use `reply`.

* **Multiple messages**
  * Use `send_split` whenever no other function is called.
  * Split responses into several short, natural chat bubbles.
  * Never send only one message.

* **Icons**
  * Use `view_icon` for profile or server icons.
  * Set `user_id` for another user, leave empty for the author.
  * Set `server_icon=True` for the server (not in DMs).

* **Web**
  * Use `search_web` for news, current events, or anything that may have changed recently."""
    else:
        return settings.get("system_message") + f"""

* The current time in UTC is {datetime.now(timezone.utc)}.
* The bot's current status message is: '{current_status}'"""

# Short system message used for generating status messages
SYSTEM_SHORT = settings.get("system_message")

# Natural replies system message generator
def get_natural_reply_prompt(context_type="random"):
    
    if context_type == "long_silence":
        return """The channel has been quiet for a while. You can:
- Make an observation about something random
- Share a hot take
- Make a joke or meme reference
- Start a new topic that fits your personality
- Comment on something from earlier in the chat

Be natural and unpredictable. Don't always ask questions. Sometimes just say something dumb or funny."""

    elif context_type == "active_convo":
        return """You were part of this conversation. You can jump back in if:
- You have something funny to add
- The topic interests you
- You want to derail the conversation

Otherwise call cancel_response. Be selective - don't spam. If the conversation naturally ended or it's awkward to jump in, definitely cancel."""

    elif context_type == "mentioned":
        return f"""Someone mentioned {NAME} or talked about you. React naturally:
- If it's relevant, join in
- If they're talking about you, be smug or defensive
- If it's a question about you, answer it

Call cancel_response if it doesn't really need your input."""

    else:  # random
        return """You're scrolling chat and considering whether to say something. Only respond if:
- A meme or joke reminds you of something
- The conversation is about something you care about
- You have a random intrusive thought to share

Most of the time you should call cancel_response. Be picky about when you speak."""