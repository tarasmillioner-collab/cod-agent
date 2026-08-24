"""LLM через Claude Agent SDK = CLI `claude` + подписка (CLAUDE_CODE_OAUTH_TOKEN). Без API-ключа.

Отличие от clients.claude.ClaudeClient: цикл tool-calling крутит сам SDK, наши tools
отдаются ему как in-process MCP-сервер. Интерфейс: run(system, transcript, tool_specs, executor)
→ SdkResult(text, tool_names, usd, limited). `limited=True` — упёрлись в лимит подписки/авторизацию:
вызывающий код шлёт детерминированный fallback и зовёт человека.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, ToolUseBlock,
                              create_sdk_mcp_server, query, tool)

log = logging.getLogger("claude_sdk")

LIMIT_MARKERS = ("weekly limit", "usage limit", "rate limit", "hit your", "organization has disabled", "invalid api key",
                 "not logged in", "authentication", "401")


async def _timeout_iter(agen, seconds: float):
    """Обмеження загального часу на один хід SDK."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + seconds
    it = agen.__aiter__()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"sdk turn > {seconds}s")
        try:
            yield await asyncio.wait_for(it.__anext__(), remaining)
        except StopAsyncIteration:
            return


@dataclass
class SdkResult:
    text: str
    tool_names: list[str] = field(default_factory=list)
    usd: float = 0.0
    limited: bool = False
    error: str = ""


class ClaudeSdkClient:
    model = "sdk"

    def __init__(self, oauth_token: str, model: str = "claude-sonnet-5", max_turns: int = 8, cwd: str | None = None,
                 parallel: int = 4, timeout_s: float = 90.0):
        self.token = oauth_token
        self.model = model
        self.max_turns = max_turns
        self.cwd = cwd or "/tmp"
        self._sem = asyncio.Semaphore(parallel)
        self.timeout_s = timeout_s

    async def run(self, system: str, transcript: str, tool_specs: list[dict],
                  executor: Callable[[str, dict], Awaitable[dict]]) -> SdkResult:
        sdk_tools = []
        for spec in tool_specs:
            name = spec["name"]

            def make(n: str):
                async def handler(args: dict[str, Any]) -> dict[str, Any]:
                    res = await executor(n, args or {})
                    return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}]}
                return handler

            sdk_tools.append(tool(name, spec["description"], spec.get("input_schema") or {"type": "object", "properties": {}})(make(name)))
        server = create_sdk_mcp_server(name="cod", version="1.0.0", tools=sdk_tools)
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
        env["CLAUDE_CODE_OAUTH_TOKEN"] = self.token
        env["ANTHROPIC_API_KEY"] = ""   # CLI не повинен авторизуватись ключем
        opts = ClaudeAgentOptions(
            system_prompt=system,
            mcp_servers={"cod": server},
            allowed_tools=[f"mcp__cod__{s['name']}" for s in tool_specs],
            disallowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite", "ToolSearch", "Skill"],
            model=self.model,
            max_turns=self.max_turns,
            cwd=self.cwd,
            env=env,
            setting_sources=[],
        )
        text_parts: list[str] = []
        tool_names: list[str] = []
        usd = 0.0
        err = ""
        try:
          async with self._sem:
            async for msg in _timeout_iter(query(prompt=transcript, options=opts), self.timeout_s):
                if isinstance(msg, AssistantMessage):
                    text_parts = []  # берём текст последнего ассистентского сообщения
                    for b in msg.content:
                        if isinstance(b, TextBlock):
                            text_parts.append(b.text)
                        elif isinstance(b, ToolUseBlock):
                            tool_names.append(b.name.replace("mcp__cod__", ""))
                elif isinstance(msg, ResultMessage):
                    usd = float(getattr(msg, "total_cost_usd", 0) or 0)
                    if getattr(msg, "is_error", False):
                        err = str(getattr(msg, "result", "") or "error")
        except Exception as e:  # noqa: BLE001
            err = str(e)
            log.error("sdk query failed: %s", e)
        text = "\n".join(t for t in text_parts if t.strip()).strip()
        low = (err + " " + text).lower()
        limited = any(m in low for m in LIMIT_MARKERS)
        if limited:
            text = ""
        elif err and not text:
            raise RuntimeError(err)          # інша помилка SDK → лічильник llm_errors у хендлері
        return SdkResult(text=text, tool_names=tool_names, usd=usd, limited=limited, error=err)
