"""Банк возражений без LLM: regex → готовый ответ из offer.yaml (objections[]).
Работает мгновенно и даже при лимите подписки. Ответ всегда возвращает к текущему шагу (кнопки добавляет хендлер)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.offer import Offer


@dataclass
class Objection:
    key: str
    rx: re.Pattern
    answer: str
    handoff: bool = False


def load(offer: Offer) -> list[Objection]:
    from core import experiments as X
    ov = X.overrides()
    out = []
    for o in offer.raw.get("objections") or []:
        try:
            ans = ov.get("obj." + o["key"]) or o["answer"]
            out.append(Objection(o["key"], re.compile(o["match"], re.IGNORECASE), ans, bool(o.get("handoff"))))
        except re.error:
            continue
    return out


def match(bank: list[Objection], text: str) -> Objection | None:
    t = text.strip()
    if len(t) > 400:
        return None
    for ob in bank:
        if ob.rx.search(t):
            return ob
    return None
