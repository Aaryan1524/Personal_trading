# Chat endpoint and Anthropic integration
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .session import SessionManager

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2048

_sessions = SessionManager()
_client: anthropic.Anthropic | None = None


def _client_instance() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def send_message(session_id: str, user_message: str, system_prompt: str) -> str:
    _sessions.add_message(session_id, "system", system_prompt)
    _sessions.add_message(session_id, "user", user_message)

    history = _sessions.get_history(session_id)
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if m["role"] in ("user", "assistant")
    ]

    try:
        response = _client_instance().messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
    except anthropic.APIError as e:
        return f"Sorry, Claude returned an API error: {e}"
    except Exception as e:
        return f"Sorry, an unexpected error occurred while contacting Claude: {e}"

    _sessions.add_message(session_id, "assistant", text)
    return text
