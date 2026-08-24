"""A/B: два цельных варианта воронки. Вариант стабилен по tg_user_id (хэш), живёт в chats.variant.

vcfg(offer, variant, key, default) — значение механики для варианта из offer.yaml → variants:{A:{...},B:{...}}.
"""
from __future__ import annotations

import hashlib

from core.offer import Offer


_OVERRIDES: dict[str, str] = {}   # "A.greet" | "obj.price" -> текст із дашборда


def set_overrides(d: dict | None) -> None:
    global _OVERRIDES
    _OVERRIDES = {str(k): str(v) for k, v in (d or {}).items() if str(v).strip()}


def overrides() -> dict[str, str]:
    return dict(_OVERRIDES)


def pick(tg_user_id: int, variants: list[str]) -> str:
    if not variants:
        return "A"
    h = int(hashlib.sha1(str(tg_user_id).encode()).hexdigest(), 16)
    return variants[h % len(variants)]


def variants_of(offer: Offer) -> list[str]:
    v = offer.raw.get("variants") or {}
    active = [k for k, cfg in v.items() if k != "_default" and (cfg or {}).get("enabled", True)]
    return active or ["A"]


def vcfg(offer: Offer, variant: str | None, key: str, default=None):
    v = (offer.raw.get("variants") or {}).get(variant or "A") or {}
    if key in v:
        return v[key]
    base = (offer.raw.get("variants") or {}).get("_default") or {}
    return base.get(key, default)


def tone(offer: Offer, variant: str | None, key: str, default: str = "") -> str:
    ov = _OVERRIDES.get(f"{variant or 'A'}.{key}")
    if ov:
        return ov
    v = (offer.raw.get("variants") or {}).get(variant or "A") or {}
    return ((v.get("tone") or {}).get(key)) or default


def persona_line(offer: Offer, variant: str | None) -> str:
    v = (offer.raw.get("variants") or {}).get(variant or "A") or {}
    return v.get("persona_line", "")


def label(offer: Offer, variant: str | None) -> str:
    v = (offer.raw.get("variants") or {}).get(variant or "A") or {}
    return v.get("label", variant or "A")
