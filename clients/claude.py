"""Anthropic Messages API с tool-calling. Тонкая обёртка: один вызов = один ход."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic

log = logging.getLogger("claude")

# Ориентировочные тарифы $/1M токенов (для дневного капа; точность ±, не биллинг)
PRICE_IN_PER_M = 3.0
PRICE_OUT_PER_M = 15.0


@dataclass
class LLMTurn:
    text: str
    tool_calls: list[dict]          # [{id, name, input}]
    raw_content: list[Any]          # content blocks для истории
    stop_reason: str
    in_tokens: int = 0
    out_tokens: int = 0
    usd: float = 0.0
    blocks: list[dict] = field(default_factory=list)


class ClaudeClient:
    def __init__(self, api_key: str, model: str, max_tokens: int = 600, timeout: float = 30.0):
        self.client = AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=1)
        self.model = model
        self.max_tokens = max_tokens

    async def turn(self, system: str, messages: list[dict], tools: list[dict]) -> LLMTurn:
        resp = await self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system, messages=messages, tools=tools,
        )
        text_parts: list[str] = []
        calls: list[dict] = []
        blocks: list[dict] = []
        for b in resp.content:
            if b.type == "text":
                text_parts.append(b.text)
                blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                calls.append({"id": b.id, "name": b.name, "input": dict(b.input or {})})
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input or {})})
        u = resp.usage
        usd = (u.input_tokens * PRICE_IN_PER_M + u.output_tokens * PRICE_OUT_PER_M) / 1_000_000
        return LLMTurn(text="\n".join(t for t in text_parts if t.strip()), tool_calls=calls, raw_content=resp.content,
                       stop_reason=resp.stop_reason or "", in_tokens=u.input_tokens, out_tokens=u.output_tokens,
                       usd=usd, blocks=blocks)


class FakeClaude:
    """Для тестов: очередь заранее заданных ходов."""

    def __init__(self, turns: list[LLMTurn]):
        self.turns = list(turns)
        self.calls: list[dict] = []
        self.model = "fake"

    async def turn(self, system: str, messages: list[dict], tools: list[dict]) -> LLMTurn:
        self.calls.append({"system": system, "messages": messages})
        await asyncio.sleep(0)
        if not self.turns:
            return LLMTurn(text="", tool_calls=[], raw_content=[], stop_reason="end_turn")
        return self.turns.pop(0)
