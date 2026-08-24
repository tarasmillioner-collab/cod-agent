"""Один чат — одна обработка за раз: два сообщения подряд не порождают два LLM-хода."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class ChatLockMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        self.locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        uid = None
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            uid = event.from_user.id
        if uid is None:
            return await handler(event, data)
        async with self.locks[uid]:
            return await handler(event, data)
