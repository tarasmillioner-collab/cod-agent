"""Передача живому менеджеру: форум-топик на клиента в супергруппе менеджеров.

open()  — создать топик (один раз на чат), карточку заказа, последние реплики; mode=human
relay_client_to_topic() — сообщения клиента в human-режиме копируются в топик
relay_manager_to_client() — ответы менеджера из топика уходят клиенту от имени бота
close() — /close или кнопка «Повернути боту» → mode=bot
"""
from __future__ import annotations

import logging
from html import escape as e

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

from core.services import Services
from tg import keyboards as K
from tg import texts as T

log = logging.getLogger("handoff")


def order_card(svc: Services, chat: dict, order: dict | None, reason: str) -> str:
    lines = [f"🙋 Клієнт: {e(chat.get('name') or chat.get('first_name') or '-')} (@{e(chat.get('username') or '-')}, id {chat['tg_user_id']})",
             f"📞 {chat.get('phone') or order and order.get('phone') or '-'}",
             f"❓ Причина: {e(reason or '-')}"]
    if order:
        s = svc.offer.set(order["set_code"]) if order.get("set_code") else None
        lines += [f"🧾 Замовлення #{order['id']} · стадія {order['stage']}",
                  f"📦 {s['label'] + ' — ' + svc.offer.fmt_price(int(s['price'])) if s else 'набір не обрано'}",
                  f"📍 {e(order.get('np_city_name') or '-')}, {e(order.get('np_wh_name') or '-')}",
                  f"🚚 ТТН: {order.get('ttn') or '-'} · CRM: {order.get('lpcrm_order_id') or '-'}"]
    utm = chat.get("utm") or {}
    if utm.get("start"):
        lines.append(f"🔗 start: {utm['start']}")
    hist = svc.store.history(chat["tg_user_id"], limit=12)
    if hist:
        lines.append("\n— останні репліки —")
        for h in hist:
            if h["role"] in ("user", "assistant", "manager"):
                who = {"user": "👤", "assistant": "🤖", "manager": "🧑‍💼"}[h["role"]]
                lines.append(f"{who} {e(h['content'][:300])}")
    lines.append("\nВідповідайте в цій темі — клієнт отримає повідомлення від бота. /close — повернути боту.")
    return "\n".join(lines)[:4000]


async def open(svc: Services, bot: Bot, chat: dict, order: dict | None, reason: str, notify_client: bool = True) -> int | None:
    st = svc.store
    if not svc.cfg.managers_chat_id:
        # Без групи: картка кожному адміну в особисті. Відповідь — реплаєм на картку (див. handlers_client.on_admin_reply).
        st.update_chat(chat["tg_user_id"], mode="human")
        st.open_handoff(chat["tg_user_id"], order and order["id"], None, reason)
        st.funnel("handoff", chat["tg_user_id"], order and order["id"], {"reason": reason, "stage": order["stage"] if order else None})
        card = order_card(svc, chat, order, reason) + f"\n\n↩️ Відповідайте РЕПЛАЄМ на це повідомлення — клієнт отримає від бота. /close_{chat['tg_user_id']} — повернути боту."
        for aid in svc.cfg.admin_ids:
            try:
                await bot.send_message(aid, card)
            except Exception as ex:  # noqa: BLE001
                log.warning("admin %s card failed: %s", aid, ex)
        if notify_client:
            txt = T.handoff_to_client(svc.offer.faq.get("support_hours", "робочі години"), getattr(svc.cfg, "manager_name", ""))
            try:
                await bot.send_message(chat["chat_id"], txt, reply_markup=K.remove_kb())
                st.add_message(chat["tg_user_id"], "assistant", txt)
            except Exception as ex:  # noqa: BLE001
                log.warning("notify client failed: %s", ex)
        return None
    topic_id = chat.get("topic_id")
    title = f"{(chat.get('name') or chat.get('first_name') or 'Клієнт')[:20]} · {chat.get('phone') or '-'} · #{order['id'] if order else '-'}"
    if not topic_id:
        try:
            t = await bot.create_forum_topic(svc.cfg.managers_chat_id, name=title[:128])
            topic_id = t.message_thread_id
            st.update_chat(chat["tg_user_id"], topic_id=topic_id)
        except Exception as ex:  # noqa: BLE001
            log.error("create_forum_topic failed: %s", ex)
            topic_id = None
    st.update_chat(chat["tg_user_id"], mode="human")
    st.open_handoff(chat["tg_user_id"], order and order["id"], topic_id, reason)
    st.funnel("handoff", chat["tg_user_id"], order and order["id"], {"reason": reason, "stage": order["stage"] if order else None})
    if order:
        st.event(order["id"], "handoff", dedup_key=reason[:40], meta={"reason": reason})
    try:
        await bot.send_message(svc.cfg.managers_chat_id, order_card(svc, chat, order, reason),
                               message_thread_id=topic_id, reply_markup=K.manager_card_kb(chat["tg_user_id"]))
    except TelegramBadRequest as e:
        log.error("send card failed: %s", e)
    if notify_client:
        txt = T.handoff_to_client(svc.offer.faq.get("support_hours", "робочі години"), getattr(svc.cfg, "manager_name", ""))
        try:
            await bot.send_message(chat["chat_id"], txt, reply_markup=K.remove_kb())
            st.add_message(chat["tg_user_id"], "assistant", txt)
        except Exception as ex:  # noqa: BLE001
            log.warning("notify client failed: %s", ex)
    return topic_id


async def close(svc: Services, bot: Bot, tg_user_id: int) -> None:
    st = svc.store
    st.update_chat(tg_user_id, mode="bot")
    st.close_handoff(tg_user_id)
    st.add_message(tg_user_id, "system", "[менеджер повернув діалог боту]")
    ch = st.get_chat(tg_user_id)
    if ch and ch.get("topic_id") and svc.cfg.managers_chat_id:
        try:
            await bot.send_message(svc.cfg.managers_chat_id, "↩️ Повернуто боту.", message_thread_id=ch["topic_id"])
        except TelegramBadRequest:
            pass


async def relay_client_to_topic(svc: Services, bot: Bot, chat: dict, message) -> None:
    if not svc.cfg.managers_chat_id:
        who = f"👤 {e(chat.get('name') or chat.get('first_name') or '')} (id {chat['tg_user_id']}):\n"
        for aid in svc.cfg.admin_ids:
            try:
                await bot.send_message(aid, who + e(message.text or message.caption or "[медіа]"))
            except Exception as ex:  # noqa: BLE001
                log.warning("relay to admin %s failed: %s", aid, ex)
        return
    if not chat.get("topic_id"):
        return
    try:
        await message.copy_to(svc.cfg.managers_chat_id, message_thread_id=chat["topic_id"])
    except TelegramBadRequest as e:
        log.warning("copy to topic failed: %s", e)


async def relay_manager_to_client(svc: Services, bot: Bot, chat: dict, message) -> None:
    try:
        await message.copy_to(chat["chat_id"])
        svc.store.add_message(chat["tg_user_id"], "manager", message.text or message.caption or "[медіа]")
        svc.store.touch_chat(chat["tg_user_id"], bot=True)
    except TelegramBadRequest as e:
        log.warning("copy to client failed: %s", e)
        if "blocked" in str(e).lower():
            svc.store.update_chat(chat["tg_user_id"], blocked_utc=__import__("db").now_utc())
