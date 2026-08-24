"""Outbox-воркер: lpcrm_create (заказ в LP-CRM) и tg_send (отложенные сообщения).

Идемпотентность: UNIQUE(kind, ref_id). Backoff 1м→…→1ч, после 24 попыток — failed + алерт.
Клиент уже получил «прийнято» — CRM догоняет.
"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramForbiddenError

from core import state as S
from core.services import Services
from db import now_utc

log = logging.getLogger("outbox")

BACKOFF = [60, 120, 300, 600, 1800, 3600]
GIVE_UP = 30


def crm_payload(svc: Services, order: dict, chat: dict, lead: bool = False) -> dict:
    s = svc.offer.set(order["set_code"] or svc.offer.default_set["code"])
    lp = svc.offer.product.get("lpcrm", {})
    utm = {**(chat.get("utm") or {}), **(order.get("utm") or {})}
    if lead:
        missing = [m for m in S.ready_to_confirm(order) if m != "set_code"]
        comment = ("🤖 TG-БОТ: лід НЕ завершив оформлення в Telegram (бракує: " + ", ".join(missing) +
                   ") → ЗАТЕЛЕФОНУВАТИ. " + s["label"])
    else:
        comment = "✅ ПІДТВЕРДЖЕНО AI-АГЕНТОМ (Telegram): клієнт натиснув «Підтверджую» → статус «Прийнято», НЕ ДЗВОНИТИ. " + s["label"]
    if svc.cfg.env == "test":
        comment = "⚠️ ТЕСТ БОТА (не відправляти) · " + comment
    if order.get("delivery_type") == "postomat":
        comment += " · ПОШТОМАТ"
    notes = [r["meta_json"] for r in svc.store.c.execute(
        "SELECT meta_json FROM order_events WHERE order_id=? AND name='note'", (order["id"],)).fetchall()]
    if notes:
        comment += " · нотатки: " + "; ".join(n[:100] for n in notes)
    return dict(
        order_id=f"tg{order['id']}",
        site=svc.cfg.lpcrm_site or lp.get("site", ""),
        office=svc.cfg.lpcrm_office or lp.get("office", ""),
        bayer_name=order.get("name") or "",
        phone=order.get("phone") or "",
        products=[{"product_id": it["product_id"], "price": it["price"], "count": it.get("qty", 1)} for it in s["items"]],
        delivery_id=lp.get("delivery_id", "1"),
        delivery_adress=(f"{order.get('np_city_name') or ''}, {order.get('np_wh_name') or ''}".strip(", ") if order.get("np_city_name") else ""),
        payment=lp.get("payment", "4"),
        comment=comment[:500],
        utm={k: utm.get(k) for k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")},
        status=(lp.get("status_new", "3") if lead else (svc.cfg.lpcrm_status_confirmed or lp.get("status_confirmed"))),
        additional={"additional_1": utm.get("utm_source_name") or "", "additional_2": utm.get("rtkcid") or "",
                    "additional_3": "tg-lead-call" if lead else "tg-ai-confirmed", "additional_4": utm.get("start") or ""},
    )


async def process_once(svc: Services) -> int:
    st = svc.store
    n = 0
    for item in st.due_outbox():
        n += 1
        try:
            if item["kind"] == "lpcrm_create":
                await _lpcrm_create(svc, item)
            elif item["kind"] == "tg_send":
                await _tg_send(svc, item)
            else:
                st.outbox_fail(item["id"], "unknown kind")
                continue
            st.outbox_done(item["id"])
        except TelegramForbiddenError as e:
            st.outbox_fail(item["id"], f"blocked: {e}")
            p = item["payload"]
            if p.get("chat_id"):
                st.update_chat(int(p["chat_id"]), blocked_utc=now_utc())
        except Exception as e:  # noqa: BLE001
            backoff = BACKOFF[min(item["attempts"], len(BACKOFF) - 1)]
            res = st.outbox_retry(item["id"], str(e), backoff, GIVE_UP)
            log.warning("outbox %s #%s: %s (%s)", item["kind"], item["ref_id"], e, res)
            if res == "failed":
                await alert(svc, f"⚠️ outbox FAILED {item['kind']} #{item['ref_id']}: {str(e)[:200]}")
    return n


async def _lpcrm_create(svc: Services, item: dict) -> None:
    st = svc.store
    order = st.get_order(int(item["payload"]["order_id"]))
    lead = bool(item["payload"].get("lead"))
    if not order:
        return
    if lead:
        if order["stage"] != S.LEAD_CRM:
            return
        chat = st.get_chat(order["chat_id"]) or {}
        res = await svc.lpcrm.add_order(**crm_payload(svc, order, chat, lead=True))
        st.update_order(order["id"], lpcrm_order_id=str(res.get("order_id") or f"tg{order['id']}"))
        st.event(order["id"], "crm_lead_created", meta={"crm": res})
        st.funnel("crm_lead_created", order["chat_id"], order["id"])
        return
    if order["stage"] not in (S.CONFIRMED, S.QUEUED_CRM):
        return
    chat = st.get_chat(order["chat_id"]) or {}
    try:
        res = await svc.lpcrm.add_order(**crm_payload(svc, order, chat))
    except Exception:
        if order["stage"] == S.CONFIRMED:
            st.transition(order["id"], S.QUEUED_CRM, "crm_queued")
        raise
    fresh = st.get_order(order["id"])
    if fresh and fresh.get("set_code") != order.get("set_code"):
        st.event(order["id"], "note", dedup_key="upsell_after_send", meta={"text": f"клієнт змінив набір на {fresh['set_code']} після відправки в CRM"})
        await alert(svc, f"❗️ #{order['id']}: клієнт додав набір ({fresh['set_code']}) після відправки в CRM — оновити замовлення вручну.")
    crm_id = str(res.get("order_id") or res.get("id") or f"tg{order['id']}")
    st.transition(order["id"], S.CONFIRMED_CRM, "crm_created", meta={"crm": res}, lpcrm_order_id=crm_id,
                  lpcrm_status=str(res.get("status_id") or ""))
    st.funnel("crm_created", order["chat_id"], order["id"], {"dry_run": bool(res.get("dry_run"))})
    if not st.has_event(order["id"], "what_next_sent") and st.event(order["id"], "what_next_sent"):
        from tg import texts as T
        try:
            await svc.bot.send_message(chat["chat_id"], T.what_next(svc.offer, st.get_order(order["id"])))
        except Exception as e:  # noqa: BLE001
            log.warning("what_next send failed: %s", e)


async def _tg_send(svc: Services, item: dict) -> None:
    p = item["payload"]
    await svc.bot.send_message(int(p["chat_id"]), p["text"])
    svc.store.add_message(int(p.get("tg_user_id") or p["chat_id"]), "assistant", p["text"])


async def alert(svc: Services, text: str) -> None:
    if not svc.cfg.managers_chat_id:
        log.error("ALERT: %s", text)
        return
    try:
        await svc.bot.send_message(svc.cfg.managers_chat_id, text)
    except Exception as e:  # noqa: BLE001
        log.error("alert failed: %s (%s)", e, text)
