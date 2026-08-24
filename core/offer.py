"""Загрузка offer.yaml + валидация лестницы (cod-offer-architect §2):
цена за набор растёт, каждый следующий набор содержит предыдущий + что-то,
upsell.from/to существуют, default_set существует."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class OfferError(Exception):
    pass


@dataclass
class Offer:
    raw: dict

    @property
    def product(self) -> dict:
        return self.raw["product"]

    @property
    def sets(self) -> list[dict]:
        return self.raw["sets"]

    def set(self, code: str | None) -> dict:
        for s in self.sets:
            if s["code"] == code:
                return s
        raise OfferError(f"unknown set code {code!r}")

    def has_set(self, code: str | None) -> bool:
        return any(s["code"] == code for s in self.sets)

    @property
    def default_set(self) -> dict:
        return self.set(self.raw.get("default_set") or self.sets[0]["code"])

    @property
    def prices(self) -> set[int]:
        """Все суммы, которые бот имеет право назвать (гейт для LLM)."""
        out: set[int] = set()
        for s in self.sets:
            out.add(int(s["price"]))
            n = sum(int(it.get("qty", 1)) for it in s["items"])
            if n:
                out.add(int(round(int(s["price"]) / n)))      # ціна «за кожен»
            if s.get("gift_value"):
                out.add(int(s["gift_value"]))
            for it in s["items"]:
                out.add(int(it["price"]))
        out.discard(0)
        return out

    @property
    def upsell(self) -> dict:
        return self.raw.get("upsell", {"enabled": False})

    @property
    def delivery(self) -> dict:
        return self.raw["delivery"]

    @property
    def storage(self) -> dict:
        return self.raw["storage"]

    @property
    def warranty(self) -> dict:
        return self.raw["warranty"]

    @property
    def faq(self) -> dict:
        return self.raw.get("faq_facts", {})

    @property
    def forbidden_claims(self) -> list[str]:
        return [c.lower() for c in self.raw.get("forbidden_claims", [])]

    @property
    def voice(self) -> dict:
        return self.raw.get("brand_voice", {})

    @property
    def persona(self) -> str:
        return self.voice.get("persona", "менеджер")

    def fmt_price(self, n: int) -> str:
        return f"{n:,}".replace(",", " ") + " грн"

    def public_summary(self) -> dict:
        """Что отдаём LLM через get_offer: наборы, цены, факты доставки. Без внутренних id."""
        return {
            "product": self.product["name_ua"],
            "sets": [
                {"code": s["code"], "label": s["label"], "price_uah": s["price"],
                 "price_text": self.fmt_price(int(s["price"])), "full_cash_text": s["full_cash_text"],
                 "items": [it["name"] for it in s["items"]], "gifts": s.get("gifts", [])}
                for s in self.sets
            ],
            "delivery": {"carrier": "Нова пошта", "eta": self.delivery["eta_text"],
                         "same_day_cutoff": self.delivery["same_day_cutoff"],
                         "payment": "оплата при отриманні після огляду, без передоплати"},
            "storage": f"{self.storage['days']} {self.storage['unit']}",
            "return_days": self.warranty["brand_return_days"],
            "no_discounts": "Окремих знижок і промокодів немає; ціни однакові для всіх.",
        }


def load_offer(path: str | Path) -> Offer:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    o = Offer(raw)
    _validate(o)
    return o


def _validate(o: Offer) -> None:
    if not o.sets:
        raise OfferError("sets пуст")
    codes = [s["code"] for s in o.sets]
    if len(codes) != len(set(codes)):
        raise OfferError("дубли кодов наборов")
    prev_price = 0
    prev_items: set[str] = set()
    for s in o.sets:
        price = int(s["price"])
        items_sum = sum(int(it["price"]) * int(it.get("qty", 1)) for it in s["items"])
        if price != items_sum:
            raise OfferError(f"{s['code']}: price {price} != сумма позиций {items_sum}")
        if price <= prev_price:
            raise OfferError(f"{s['code']}: цена набора должна расти ({price} <= {prev_price})")
        ids = {it["product_id"] for it in s["items"]}
        if prev_items and not prev_items <= ids:
            raise OfferError(f"{s['code']}: набор должен включать предыдущий")
        prev_price, prev_items = price, ids
        if not s.get("full_cash_text"):
            raise OfferError(f"{s['code']}: нет full_cash_text")
        if o.delivery.get("commission_paid_by") == "customer" and "рівно" in s["full_cash_text"]:
            raise OfferError(f"{s['code']}: «рівно» запрещено, если доставку платит клиент")
    o.default_set  # noqa: B018 — бросит, если default_set неизвестен
    up = o.upsell
    if up.get("enabled"):
        if not (o.has_set(up.get("from")) and o.has_set(up.get("to"))):
            raise OfferError("upsell.from/to должны быть кодами наборов")
        if int(o.set(up["to"])["price"]) <= int(o.set(up["from"])["price"]):
            raise OfferError("upsell.to должен быть дороже upsell.from")
        if not up.get("text"):
            raise OfferError("upsell.text пуст")
