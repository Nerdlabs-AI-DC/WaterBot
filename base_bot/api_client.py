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

import asyncio
import base64
import functools
import requests
import html
from typing import List
from openai import OpenAI
from openrouter import OpenRouter
from config import MODEL, DEBUG, EMBED_MODEL, IMAGE_MODEL, PROVIDER, API_KEY, OPENAI_ENDPOINT, OLLAMA_ENDPOINT

if PROVIDER == 'openai':
    _oai = OpenAI(api_key=API_KEY, base_url=OPENAI_ENDPOINT)
elif PROVIDER == 'ollama':
    _oai = OpenAI(api_key="ollama", base_url=OLLAMA_ENDPOINT)
elif PROVIDER == 'openrouter':
    _oai = OpenAI(api_key=API_KEY, base_url="https://openrouter.ai/api/v1")

reddit_headers = {
    "User-Agent": "WaterBot/1.0"
}

async def generate_response(messages, tools=None, tool_choice=None, model=MODEL, channel_id=None, instructions=None, effort=None, user=None):
    loop = asyncio.get_event_loop()
    if DEBUG:
        print(f"Instructions: {instructions}. Generating response with model: {model} and channel id: {channel_id}.")
    if instructions:
        messages.insert(0, {"role": "developer", "content": instructions})
    kwargs = dict(
    model=model,
    input=messages,
    max_output_tokens=2000
    )
    if tools:
        fixed_tools = []
        for tool in tools:
            if 'type' not in tool:
                tool = dict(tool)
                tool['type'] = 'function'
            fixed_tools.append(tool)
        kwargs["tools"] = fixed_tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    if channel_id:
        kwargs["prompt_cache_key"] = str(channel_id)
    if user:
        kwargs["user"] = user
    completion = await loop.run_in_executor(
        None,
        functools.partial(
            _oai.responses.create,
            **kwargs
        )
    )
    return completion

def embed_text(text: str) -> List[float]:
    if DEBUG:
        print(f'Embedding text "{text}" with model: {EMBED_MODEL} via {PROVIDER}')

    try:
        if PROVIDER == "ollama" or PROVIDER == "openai":
            res = _oai.embeddings.create(
                model=EMBED_MODEL,
                input=text
            )
            return res.data[0].embedding

        elif PROVIDER == "openrouter":
            with OpenRouter(api_key=API_KEY, timeout_ms=10000) as open_router:
                res = open_router.embeddings.generate(input=text, model=EMBED_MODEL)
                return res.data[0].embedding

    except Exception as e:
        if DEBUG:
            print(f"embed_text failed: {e}")
        return []

def get_subreddit_posts(subreddit: str, limit: int):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit={limit}"
    try:
        res = requests.get(url, headers=reddit_headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        posts = data["data"]["children"]
        return [p["data"]["title"] for p in posts]
    except Exception:
        return []

async def analyze_image(image_url):
    if DEBUG:
        print(f"Analyzing image: {image_url}")

    loop = asyncio.get_event_loop()
    image_data = image_url  # fallback
    try:
        resp = await loop.run_in_executor(
            None,
            functools.partial(requests.get, image_url, timeout=15)
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/png"
        b64 = base64.b64encode(resp.content).decode("utf-8")
        image_data = f"data:{content_type};base64,{b64}"
    except Exception as e:
        if DEBUG:
            print(f"Failed to fetch image for base64 encoding, falling back to URL: {e}")

    response = await generate_response(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Describe this image in detail."},
                    {
                        "type": "input_image",
                        "image_url": image_data
                    }
                ]
            }
        ],
        model=IMAGE_MODEL,
    )
    if DEBUG:
        print(f"Image analysis response: {response.output_text}")
    return response.output_text

async def reddit_search(query: str, limit: int = 5):
    url = "https://www.reddit.com/search.json"
    params = {
        "q": query,
        "limit": limit,
        "sort": "relevance",
        "t": "year"
    }

    try:
        r = requests.get(url, params=params, headers=reddit_headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        results = []

        for item in data["data"]["children"]:
            post = item["data"]

            title = html.unescape(post.get("title", ""))
            text = html.unescape(post.get("selftext", ""))

            combined = f"{title}\n{text}".strip()

            results.append({combined})

        return results

    except Exception:
        return []