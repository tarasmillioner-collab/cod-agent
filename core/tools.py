"""Tools, которые видит Claude. Код решает: цены/сводка/статусы — только отсюда.

exec_tool() возвращает (result_for_llm, ui_hint). ui_hint говорит хендлеру,
какую клавиатуру/экран показать после ответа LLM ("warehouse", "summary",
"confirmed", "handoff", "city", ...). Телефон тут не tool — только request_contact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core import state as S
from core.offer import Offer
from core.store import Store, TransitionError

NAME_RX = re.compile(r"^[А-ЯІЇЄҐа-яіїєґ'’\- ]{2,80}$")

TOOLS: list[dict] = [
    {"name": "get_offer", "description": "Набори, ціни, умови доставки/повернення. ЄДИНЕ джерело цифр.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_faq", "description": "Факт про продукт/доставку за темою: what_is, how_to_use, results, course, sensitive_skin, shelf_life, eye_cream, delivery, return, no_prepay, where_we_are, health, support_hours.",
     "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}},
    {"name": "get_order_state", "description": "Поточний стан замовлення: стадія, набір, що вже зібрано, чого бракує.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "set_bundle", "description": "Змінити набір (код з get_offer: s1/s2/s3). Клієнт хоче менше — погоджуйся одразу.",
     "input_schema": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
    {"name": "set_name", "description": "Записати ім'я (ПІБ) для накладної, українською.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "np_search_city", "description": "Знайти населений пункт Нової пошти за назвою. Повертає до 5 варіантів з ref.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "set_city", "description": "Зафіксувати місто за ref з np_search_city.",
     "input_schema": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}},
    {"name": "np_search_warehouse", "description": "Знайти відділення у вибраному місті за номером або вулицею. postomat=true — шукати поштомати.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "postomat": {"type": "boolean"}}, "required": ["query"]}},
    {"name": "set_warehouse", "description": "Зафіксувати відділення/поштомат за ref з np_search_warehouse.",
     "input_schema": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]}},
    {"name": "request_confirm", "description": "Показати клієнту підсумок замовлення з кнопкою підтвердження (система сама рендерить суму).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "cancel_order", "description": "Скасувати замовлення на прохання клієнта (до відправки — безкоштовно).",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "schedule_reminder", "description": "Нагадати клієнту через N годин (наприклад, «нагадайте завтра» = 24).",
     "input_schema": {"type": "object", "properties": {"hours": {"type": "integer"}}, "required": ["hours"]}},
    {"name": "handoff", "description": "Передати діалог живому менеджеру: просять подзвонити, медичне питання, агресія, скарга на отриманий товар, оплата карткою, 3 сумніви без просування.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "note", "description": "Записати важливу деталь до замовлення (наприклад, побажання клієнта).",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
]


@dataclass
class ToolCtx:
    store: Store
    offer: Offer
    np: Any                       # clients.novaposhta.NovaPoshta
    chat: dict
    order: dict | None
    ui: list[str] = field(default_factory=list)
    extra_amounts: set[int] = field(default_factory=set)

    def refresh(self) -> None:
        if self.order:
            self.order = self.store.get_order(self.order["id"])


def _order_public(ctx: ToolCtx) -> dict:
    o = ctx.order
    if not o:
        return {"stage": "none", "hint": "замовлення ще не створено"}
    s = ctx.offer.set(o["set_code"]) if o.get("set_code") else None
    return {
        "stage": o["stage"],
        "set": {"code": s["code"], "label": s["label"], "price_text": ctx.offer.fmt_price(int(s["price"]))} if s else None,
        "name": o.get("name"),
        "phone_collected": bool(o.get("phone")),
        "city": o.get("np_city_name"),
        "warehouse": o.get("np_wh_name"),
        "delivery_type": o.get("delivery_type"),
        "missing": S.ready_to_confirm(o),
        "ttn": o.get("ttn"),
        "np_status": o.get("np_status_text"),
        "storage_until": o.get("storage_until"),
    }


async def exec_tool(ctx: ToolCtx, name: str, args: dict) -> dict:
    st, o = ctx.store, ctx.order
    try:
        if name == "get_offer":
            return ctx.offer.public_summary()

        if name == "get_faq":
            topic = (args.get("topic") or "").strip().lower()
            if topic == "health":
                topic = "health_safe_phrase"
            fact = ctx.offer.faq.get(topic)
            return {"topic": topic, "fact": fact or "Такого факту немає — не вигадуй, запропонуй передати менеджеру."}

        if name == "get_order_state":
            return _order_public(ctx)

        if not o and name in ("set_bundle", "set_name", "set_city", "set_warehouse", "request_confirm", "cancel_order", "note"):
            return {"error": "замовлення не створено; спочатку потрібен телефон (кнопка)"}

        if name == "set_bundle":
            code = (args.get("code") or "").strip().lower()
            if not ctx.offer.has_set(code):
                return {"error": f"невідомий набір {code}", "valid": [s["code"] for s in ctx.offer.sets]}
            if o["stage"] not in S.PRE_SHIP_STAGES[:7]:
                return {"error": "після підтвердження набір змінює лише менеджер", "hint": "handoff"}
            cur_price = int(ctx.offer.set(o["set_code"])["price"]) if o.get("set_code") else 0
            new = ctx.offer.set(code)
            st.update_order(o["id"], set_code=code, price_uah=int(new["price"]))
            if int(new["price"]) < cur_price:
                st.set_flag(ctx.chat["tg_user_id"], "downgraded", True)
                st.funnel("downsell", ctx.chat["tg_user_id"], o["id"], {"from": o["set_code"], "to": code})
            st.event(o["id"], "set_changed", dedup_key=code, meta={"to": code})
            ctx.refresh()
            return {"ok": True, "set": code, "price_text": ctx.offer.fmt_price(int(new["price"]))}

        if name in ("set_name", "set_city", "set_warehouse") and o["stage"] not in S.COLLECT_STAGES:
            return {"error": "після підтвердження дані змінює менеджер", "hint": "handoff"}

        if name == "set_name":
            nm = re.sub(r"\s+", " ", (args.get("name") or "")).strip()
            if not NAME_RX.match(nm):
                return {"error": "ім'я має бути українською, 2–40 літер"}
            st.update_order(o["id"], name=nm)
            st.update_chat(ctx.chat["tg_user_id"], name=nm)
            if o["stage"] == S.NAME:
                st.transition(o["id"], S.CITY, "name_received")
                ctx.ui.append("city")
            ctx.refresh()
            return {"ok": True, "name": nm}

        if name == "np_search_city":
            q = (args.get("query") or "").strip()
            if len(q) < 2:
                return {"error": "надто короткий запит"}
            cities = await ctx.np.search_cities(q)
            if not cities:
                return {"results": [], "hint": "не знайдено — попроси уточнити назву або область"}
            return {"results": [{"ref": c["ref"], "name": c["present"] or c["name"]} for c in cities]}

        if name == "set_city":
            ref = (args.get("ref") or "").strip()
            city = await ctx.np.city_by_ref(ref)
            cname = (city.get("present") or city.get("name")) if city else None
            if not cname:
                return {"error": "ref не з результатів np_search_city"}
            st.update_order(o["id"], np_city_ref=ref, np_city_name=cname, np_wh_ref=None, np_wh_name=None)
            if o["stage"] in (S.CITY, S.NAME, S.PHONE):
                try:
                    st.transition(o["id"], S.WAREHOUSE, "city_received")
                except TransitionError:
                    pass
            ctx.ui.append("warehouse")
            ctx.refresh()
            return {"ok": True, "city": cname}

        if name == "np_search_warehouse":
            if not o or not o.get("np_city_ref"):
                return {"error": "спочатку set_city"}
            q = (args.get("query") or "").strip()
            postomat = bool(args.get("postomat"))
            if postomat and not ctx.offer.delivery.get("postomat_allowed"):
                return {"error": "поштомати недоступні для цього товару"}
            whs = await ctx.np.warehouses(o["np_city_ref"], q, limit=6, postomat=postomat or False)
            if not whs and not postomat:
                whs = await ctx.np.warehouses(o["np_city_ref"], "", limit=6, postomat=False)
            return {"results": [{"ref": w["ref"], "desc": w["desc"], "postomat": w["postomat"]} for w in whs],
                    "postomat_warning": ctx.offer.delivery.get("postomat_allowed") and postomat}

        if name == "set_warehouse":
            if not o or not o.get("np_city_ref"):
                return {"error": "спочатку set_city"}
            ref = (args.get("ref") or "").strip()
            w = await ctx.np.warehouse_by_ref(o["np_city_ref"], ref)
            if not w:
                return {"error": "ref не з результатів np_search_warehouse"}
            dtype = "postomat" if w["postomat"] else "warehouse"
            st.update_order(o["id"], np_wh_ref=ref, np_wh_name=w["desc"], delivery_type=dtype)
            if o["stage"] == S.WAREHOUSE:
                st.transition(o["id"], S.UPSELL, "warehouse_received", meta={"type": dtype})
            ctx.ui.append("after_warehouse")
            ctx.refresh()
            return {"ok": True, "warehouse": w["desc"], "type": dtype}

        if name == "request_confirm":
            missing = S.ready_to_confirm(o)
            if missing:
                return {"error": "не всі дані зібрано", "missing": missing}
            if o["stage"] in (S.UPSELL, S.WAREHOUSE):
                st.transition(o["id"], S.REVIEW, "review")
            ctx.ui.append("summary")
            ctx.refresh()
            return {"ok": True, "hint": "підсумок і кнопку показує система; сам суму не дублюй"}

        if name == "cancel_order":
            if o["stage"] in (S.SHIPPED, S.ARRIVED):
                return {"error": "посилка вже в дорозі — скасування через менеджера", "hint": "handoff"}
            st.transition(o["id"], S.CANCELLED, "cancelled", meta={"reason": args.get("reason", "")})
            st.funnel("cancelled_before_ship", ctx.chat["tg_user_id"], o["id"], {"reason": args.get("reason", ""), "stage": o["stage"]})
            ctx.ui.append("cancelled")
            ctx.refresh()
            return {"ok": True}

        if name == "schedule_reminder":
            h = max(1, min(int(args.get("hours") or 24), 72))
            from datetime import datetime, timedelta, timezone
            due = (datetime.now(timezone.utc) + timedelta(hours=h)).replace(microsecond=0).isoformat()
            st.set_flag(ctx.chat["tg_user_id"], "reminder_due", due)
            st.funnel("reminder_scheduled", ctx.chat["tg_user_id"], o and o["id"], {"hours": h})
            ctx.ui.append("reminder_set")
            return {"ok": True, "hours": h}

        if name == "handoff":
            ctx.ui.append("handoff:" + (args.get("reason") or "")[:120])
            return {"ok": True, "hint": "скажи, що передаєш колезі; далі пише менеджер"}

        if name == "note":
            txt = "клієнт: " + re.sub(r"[<>\"]", "", (args.get("text") or ""))[:200]
            st.event(o["id"], "note", dedup_key=txt[:60], meta={"text": txt})
            return {"ok": True}

        return {"error": f"unknown tool {name}"}
    except TransitionError as e:
        return {"error": str(e)}
