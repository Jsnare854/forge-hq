"""Thin wrapper around the Claude API that returns parsed JSON."""
from __future__ import annotations

import json
import re

from .config import secret


class LLMError(RuntimeError):
    pass


def parse_json(text: str):
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if starts:
        start = min(starts)
        end = max(text.rfind("]"), text.rfind("}"))
        if end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError("Claude's reply wasn't valid JSON: " + text[:300])


def ask_json(prompt: str, model: str, max_tokens: int = 12000):
    import anthropic

    client = anthropic.Anthropic(api_key=secret("ANTHROPIC_API_KEY"))
    last_err = None
    for _ in range(2):  # one retry on a garbled reply
        msg = client.messages.create(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            return parse_json(text)
        except LLMError as e:
            last_err = e
    raise last_err
