"""Контейнер зависимостей — один объект передаётся в хендлеры и планировщик."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from config import Config
from core.guards import Guards
from core.offer import Offer
from core.store import Store

KYIV = ZoneInfo("Europe/Kyiv")

PHONE_RX = re.compile(r"^(?:\+?38)?0(39|50|63|66|67|68|73|75|77|91|92|93|94|95|96|97|98|99)\d{7}$")


def normalize_phone(raw: str) -> str | None:
    """→ '380XXXXXXXXX' (как хранит LP-CRM) или None."""
    s = re.sub(r"[\s\-\(\)]", "", raw or "")
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("380") and len(s) == 12:
        s = "0" + s[3:]
    elif s.startswith("80") and len(s) == 11:
        s = "0" + s[2:]
    if not PHONE_RX.match(s):
        return None
    if len(set(s[1:])) <= 2:       # 0000000000, 0111111111
        return None
    return "38" + s


def now_kyiv() -> datetime:
    return datetime.now(KYIV)


def is_night(hours: list[int] | None = None) -> bool:
    start, end = (hours or [23, 8])
    h = now_kyiv().hour
    return h >= start or h < end


@dataclass
class Services:
    cfg: Config
    store: Store
    offer: Offer
    guards: Guards
    np: object
    lpcrm: object
    agent: object
    bot: object = None   # aiogram Bot; ставится после создания
    voice: object = None
    objections: list = None
    pcards: object = None
