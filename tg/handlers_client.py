"""Клиентские хендлеры: детерминированный скелет сбора заказа + маршрутизация
свободного текста в LLM-агента. Кнопки обрабатывает код без LLM."""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, FSInputFile, Message
from pathlib import Path

CARDS_DIR = Path(__file__).resolve().parent.parent / "assets" / "cards"

from core import handoff
from core import state as S
from core import experiments as X
from core import objections as OBJ
from core import names as N
import voice as V
from core.agent import LLMLimited
from core.guards import detect_russian
from core.services import Services, is_night, normalize_phone
from core.tools import NAME_RX
from db import now_utc
from tg import keyboards as K
from tg import texts as T


async def ack(cb, text: str | None = None) -> None:
    """cb.answer, який не падає на застарілих callback після рестарту."""
    try:
        await cb.answer(text)
    except Exception:  # noqa: BLE001
        pass

log = logging.getLogger("client")
router = Router(name="client")
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")

UPSELL_WAIT_SEC = 600
UPSELL_DELAY_SEC = 3    # коротка пауза після квитанції

CANCEL_RX = re.compile(r"\b(скасу|отмен|відмін|не треба|не потрібно|передумал)", re.IGNORECASE)
ONLY_ONE_RX = re.compile(r"\b(тільки|лише|только)\s+(одн|1\b|сироват)", re.IGNORECASE)
PRICE_OBJ_RX = re.compile(r"(дорог|дешев|знижк|скидк|ціна|цена|акці)", re.IGNORECASE)


# ---------- helpers ----------
def parse_start(payload: str | None) -> tuple[str | None, dict]:
    """'s2_fb_6a8...' → ('s2', {'start': 's2_fb_6a8...', 'utm_source': 'fb', 'rtkcid': '6a8...'})."""
    if not payload:
        return None, {}
    parts = payload.split("_")
    code = parts[0].lower()
    if code.startswith("b") and code[1:].isdigit():
        code = "s" + code[1:]
    utm = {"start": payload}
    if len(parts) > 1:
        utm["utm_source"] = parts[1]
    if len(parts) > 2:
        utm["rtkcid"] = "_".join(parts[2:])
    return (code if re.fullmatch(r"s\d", code) else None), utm


from html import escape as _esc


async def send(svc: Services, chat: dict, text: str, kb=None, html: bool = True) -> None:
    """html=False — текст LLM/клиента: экранируем, чтобы не сломать HTML parse mode."""
    if not html:
        text = _esc(text)
    try:
        await svc.bot.send_message(chat["chat_id"], text, reply_markup=kb)
    except TelegramForbiddenError:
        svc.store.update_chat(chat["tg_user_id"], blocked_utc=now_utc())
        return
    svc.store.add_message(chat["tg_user_id"], "assistant", text)
    svc.store.touch_chat(chat["tg_user_id"], bot=True)


async def send_voice(svc: Services, chat: dict, text: str, wait: bool = False) -> bool:
    """Голосове Олі (якщо варіант і бекенд дозволяють). wait=False — лише з кешу/фону, не блокуємо чат."""
    chat = svc.store.get_chat(chat["tg_user_id"]) or chat
    v = getattr(svc, "voice", None)
    if not v or not v.enabled or not X.vcfg(svc.offer, chat.get("variant"), "voice"):
        return False
    path = await v.get(text, wait=wait)
    if not path:
        return False
    try:
        from aiogram.types import FSInputFile
        await svc.bot.send_voice(chat["chat_id"], FSInputFile(path))
        svc.store.add_message(chat["tg_user_id"], "assistant", "[голосове] " + text)
        svc.store.funnel("voice_sent", chat["tg_user_id"], None, {"len": len(text)})
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("send_voice failed: %s", e)
        return False


async def send_card(svc: Services, chat: dict, card: str, caption: str, kb=None, path: Path | None = None) -> None:
    """Фото-карточка (assets/cards/<card>.jpg или явный path) с подписью; file_id кэшируется в settings."""
    path = path or CARDS_DIR / f"{card}.jpg"
    if not path.exists():
        await send(svc, chat, caption, kb)
        return
    stt = path.stat()
    key = f"card_file_id:{card}:{stt.st_size}:{int(stt.st_mtime)}"   # новая картинка = новый кэш
    photo = svc.store.get_setting(key) or FSInputFile(path)
    try:
        msg = await svc.bot.send_photo(chat["chat_id"], photo, caption=caption, reply_markup=kb)
        if not isinstance(photo, str) and getattr(msg, "photo", None):
            svc.store.set_setting(key, msg.photo[-1].file_id)
    except TelegramForbiddenError:
        svc.store.update_chat(chat["tg_user_id"], blocked_utc=now_utc())
        return
    except Exception as e:  # noqa: BLE001
        log.warning("send_photo failed (%s), fallback to text", e)
        await send(svc, chat, caption, kb)
        return
    svc.store.add_message(chat["tg_user_id"], "assistant", caption)
    svc.store.touch_chat(chat["tg_user_id"], bot=True)


def _prewarm(svc: Services, chat: dict, full_name: str) -> None:
    pc = getattr(svc, "pcards", None)
    if pc and getattr(pc, "enabled", False):
        pc.prewarm(N.address(full_name))
    v = getattr(svc, "voice", None)
    ch = svc.store.get_chat(chat["tg_user_id"]) or chat
    if v and v.enabled and X.vcfg(svc.offer, ch.get("variant"), "voice"):
        a = N.address(full_name)
        for ph in (V.phrase_thanks(a), V.phrase_arrived(a)):
            v.prewarm(ph)


def card_for_set(code: str | None) -> str:
    return {"s1": "s1", "s2": "s2"}.get(code or "", "sets")


def ctx(svc: Services, m: Message | CallbackQuery) -> tuple[dict, dict | None]:
    u = m.from_user
    chat_obj = getattr(m, "chat", None)
    chat_id = chat_obj.id if chat_obj is not None else m.message.chat.id
    chat = svc.store.upsert_chat(u.id, chat_id, u.username, u.first_name)
    svc.store.touch_chat(u.id)
    return chat, svc.store.active_order(u.id)


def _cyr_name(s: str | None) -> str | None:
    if s and NAME_RX.match(s.strip()) and len(s.strip().split()) <= 2:
        return s.strip()
    return None


# ---------- шаги (переиспользуются хендлерами и UI-хинтами агента) ----------
async def step_phone(svc: Services, chat: dict, order: dict) -> None:
    if order["stage"] == S.NEW:
        svc.store.transition(order["id"], S.PHONE, "set_chosen")
    svc.store.funnel("phone_requested", chat["tg_user_id"], order["id"])
    await send(svc, chat, T.ask_phone(svc.offer, (svc.store.get_chat(chat["tg_user_id"]) or chat).get("variant")), K.phone_kb())


def _tg_full_name(chat: dict) -> str | None:
    fn, ln = (chat.get("first_name") or "").strip(), (chat.get("last_name") or "").strip()
    full = f"{fn} {ln}".strip()
    if fn and ln and NAME_RX.match(full) and len(full.split()) == 2:
        return full
    return None


async def step_name(svc: Services, chat: dict, order: dict) -> None:
    chat = svc.store.get_chat(chat["tg_user_id"]) or chat
    if X.vcfg(svc.offer, chat.get("variant"), "name_mode") == "prefill":
        full = _tg_full_name(chat)
        if full:
            await send(svc, chat, T.ask_name_prefill(full), K.name_prefill_kb(full))
            return
        fn = (chat.get("first_name") or "").strip()
        if fn and NAME_RX.match(fn) and len(fn.split()) == 1:
            await send(svc, chat, T.ask_name_first(fn), K.name_first_kb(fn))
            return
    await send(svc, chat, T.ask_name(), K.remove_kb())


async def step_city(svc: Services, chat: dict, order: dict) -> None:
    chat = svc.store.get_chat(chat["tg_user_id"]) or chat
    if X.vcfg(svc.offer, chat.get("variant"), "address_mode") == "geo":
        await send(svc, chat, T.ask_city_geo(order.get("name")), K.geo_kb())
        return
    await send(svc, chat, T.ask_city(order.get("name")), K.remove_kb())


async def step_warehouse(svc: Services, chat: dict, order: dict, query: str = "", postomat: bool = False) -> None:
    whs = await svc.np.warehouses(order["np_city_ref"], query, limit=6, postomat=postomat)
    if not whs and query:
        await send(svc, chat, T.warehouse_not_found())
        return
    if not whs:
        whs = await svc.np.warehouses(order["np_city_ref"], "", limit=6, postomat=False)
    kb = K.warehouses_kb(whs, svc.offer.delivery.get("postomat_allowed", False), show_postomat=not postomat)
    await send(svc, chat, T.ask_warehouse(order["np_city_name"]) if not query else "Оберіть відділення:", kb)


async def after_warehouse(svc: Services, chat: dict, order: dict) -> None:
    """Після відділення — одразу підсумок. Апсейл живе після підтвердження (offer.upsell.moment)."""
    await step_summary(svc, chat, order)


def upsell_allowed(svc: Services, chat: dict, order: dict) -> tuple[bool, list[str]]:
    up = svc.offer.upsell
    flags = (svc.store.get_chat(chat["tg_user_id"]) or {}).get("flags", {})
    suppress = set(up.get("suppress_if", []))
    reasons = [f for f in ("downgraded", "objection_price", "reentry", "said_only_one") if f in suppress and flags.get(f)]
    if "night" in suppress and is_night(up.get("night_hours")):
        reasons.append("night")
    ok = bool(up.get("enabled") and order["set_code"] == up.get("from") and not order.get("upsell_shown") and not reasons)
    return ok, reasons


async def offer_upsell_after_confirm(svc: Services, chat: dict, order: dict) -> bool:
    ok, reasons = upsell_allowed(svc, chat, order)
    up = svc.offer.upsell
    if not ok:
        if up.get("enabled") and order["set_code"] == up.get("from") and not order.get("upsell_shown"):
            svc.store.funnel("upsell_suppressed", chat["tg_user_id"], order["id"], {"reasons": reasons})
        return False
    svc.store.update_order(order["id"], upsell_shown=1)
    svc.store.funnel("upsell_shown", chat["tg_user_id"], order["id"], {"from": up["from"], "to": up["to"], "moment": "after_confirm"})
    pc = getattr(svc, "pcards", None)
    ppath = pc.cached(N.address(order.get("name"))) if pc and getattr(pc, "enabled", False) and order.get("name") else None
    if ppath:
        svc.store.funnel("upsell_personal_card", chat["tg_user_id"], order["id"])
    await send_card(svc, chat, "upsell", T.upsell(svc.offer, order.get("name"), order.get("variant")), K.upsell_kb(svc.offer), path=ppath)
    return True


async def step_summary(svc: Services, chat: dict, order: dict) -> None:
    order = svc.store.get_order(order["id"])
    missing = S.ready_to_confirm(order)
    if missing:
        nxt = S.next_collect_stage(order)
        await {S.PHONE: step_phone, S.NAME: step_name, S.CITY: step_city}.get(nxt, step_warehouse)(svc, chat, order)
        return
    if order["stage"] in (S.UPSELL, S.WAREHOUSE):
        svc.store.transition(order["id"], S.REVIEW, "review")
    svc.store.funnel("summary_shown", chat["tg_user_id"], order["id"])
    await send(svc, chat, T.summary(svc.offer, order), K.summary_kb(svc.offer, order))


async def do_confirm(svc: Services, chat: dict, order: dict) -> None:
    order = svc.store.get_order(order["id"])
    if order["stage"] != S.REVIEW:
        if order["stage"] in (S.CONFIRMED, S.QUEUED_CRM, S.CONFIRMED_CRM):
            await send(svc, chat, "Замовлення вже підтверджено ✅ Напишу, щойно посилка поїде.")
        else:
            await step_summary(svc, chat, order)
        return
    if S.ready_to_confirm(order):
        await step_summary(svc, chat, order)
        return
    svc.store.transition(order["id"], S.CONFIRMED, "confirmed")
    svc.store.funnel("lead_confirmed", chat["tg_user_id"], order["id"], {"set": order["set_code"], "price": order["price_uah"]})
    # CRM ставимо в чергу ОДРАЗУ (із затримкою на апсейл); якщо апсейл не покажемо — знімемо затримку нижче
    svc.store.enqueue("lpcrm_create", str(order["id"]), {"order_id": order["id"]}, delay_sec=UPSELL_WAIT_SEC)
    await send(svc, chat, T.receipt(svc.offer, svc.store.get_order(order["id"])), K.remove_kb())
    svc.store.funnel("receipt_sent", chat["tg_user_id"], order["id"])
    await send_voice(svc, chat, V.phrase_thanks(N.address(order.get("name"))), wait=False)
    ok, _ = upsell_allowed(svc, chat, svc.store.get_order(order["id"]))
    if ok:
        asyncio.create_task(_delayed_upsell(svc, chat, order["id"]))
    else:
        svc.store.c.execute("UPDATE outbox SET next_try_utc=? WHERE kind='lpcrm_create' AND ref_id=? AND state='pending'", (now_utc(), str(order["id"])))


async def _delayed_upsell(svc: Services, chat: dict, order_id: int) -> None:
    await asyncio.sleep(UPSELL_DELAY_SEC)
    order = svc.store.get_order(order_id)
    if not order or order["stage"] != S.CONFIRMED:
        return
    shown = await offer_upsell_after_confirm(svc, chat, order)
    if not shown:
        svc.store.c.execute("UPDATE outbox SET next_try_utc=? WHERE kind='lpcrm_create' AND ref_id=? AND state='pending'", (now_utc(), str(order_id)))


async def run_agent(svc: Services, chat: dict, order: dict | None, message: Message | None = None) -> None:
    """Свободный текст → LLM. После ответа — UI по хинтам инструментов."""
    chat = svc.store.get_chat(chat["tg_user_id"]) or chat
    if not svc.store.bot_enabled():
        await handoff.open(svc, svc.bot, chat, order, "bot_off", notify_client=True)
        return
    if svc.store.usage_today_usd() >= svc.cfg.llm_daily_usd_cap:
        log.error("LLM daily cap reached; auto bot off")
        svc.store.set_setting("bot_enabled", "0")
        await handoff.open(svc, svc.bot, chat, order, "llm_cap", notify_client=True)
        return
    try:
        reply = await svc.agent.reply(chat, order)
    except LLMLimited as e:
        log.error("LLM limited: %s", e)
        svc.store.funnel("llm_limited", chat["tg_user_id"], order and order["id"])
        await send(svc, chat, "Хвилинку — передам ваше питання колезі, вона відповість тут 💛")
        await handoff.open(svc, svc.bot, chat, order, "llm_limited: " + str(e)[:80], notify_client=False)
        return
    except Exception as e:  # noqa: BLE001
        log.exception("agent error: %s", e)
        flags = svc.store.set_flag(chat["tg_user_id"], "llm_errors", (chat.get("flags", {}).get("llm_errors", 0) or 0) + 1)
        if flags.get("llm_errors", 0) >= 3:
            await handoff.open(svc, svc.bot, chat, order, "llm_error", notify_client=True)
        else:
            await send(svc, chat, "Хвилинку, перевірю і відповім.")
        return
    if reply.blocked_reasons:
        svc.store.funnel("llm_blocked", chat["tg_user_id"], order and order["id"], {"reasons": reply.blocked_reasons})
    order = svc.store.active_order(chat["tg_user_id"])
    handoff_reason = next((u.split(":", 1)[1] for u in reply.ui if u.startswith("handoff")), None)
    kb = None
    if order and order["stage"] in (S.NEW, S.PHONE) and not order.get("phone") and not handoff_reason:
        kb = K.phone_kb()
    if reply.text:
        await send(svc, chat, reply.text, kb, html=False)
    if handoff_reason is not None:
        await handoff.open(svc, svc.bot, chat, order, handoff_reason or "llm", notify_client=not reply.text)
        return
    if not order:
        return
    if "cancelled" in reply.ui:
        await send(svc, chat, T.cancelled(), K.remove_kb())
        return
    if "warehouse" in reply.ui:
        await step_warehouse(svc, chat, svc.store.get_order(order["id"]))
    elif "after_warehouse" in reply.ui:
        await after_warehouse(svc, chat, order)
    elif "summary" in reply.ui:
        await step_summary(svc, chat, order)
    # прогресс-счётчик: 2 хода без смены стадии → кнопки шага; 4 → оффер handoff
    prev_stage = chat.get("flags", {}).get("stage_seen")
    flags = chat.get("flags", {})
    if prev_stage == order["stage"] and not reply.ui:
        n = (flags.get("no_progress", 0) or 0) + 1
        svc.store.set_flag(chat["tg_user_id"], "no_progress", n)
        if n == 2 and order["stage"] in S.COLLECT_STAGES:
            await step_summary(svc, chat, order) if order["stage"] in (S.UPSELL, S.REVIEW) else await _repeat_step(svc, chat, order)
        elif n >= 4:
            await send(svc, chat, "Хочете, передам живій людині? Вона відповість тут.", K.yes_no_kb("Так", "Ні, продовжимо", "hand:yes", "hand:no"))
    else:
        svc.store.set_flag(chat["tg_user_id"], "no_progress", 0)
    svc.store.set_flag(chat["tg_user_id"], "stage_seen", order["stage"])


async def _repeat_step(svc: Services, chat: dict, order: dict) -> None:
    order = svc.store.get_order(order["id"])
    fn = {S.NEW: step_phone, S.PHONE: step_phone, S.NAME: step_name, S.CITY: step_city, S.WAREHOUSE: step_warehouse}.get(order["stage"])
    if fn:
        await fn(svc, chat, order)


# ---------- адмін у особистих: реплай на картку → клієнту; /close_<id> ----------
async def is_admin(m: Message, svc: Services) -> bool:
    return bool(svc.cfg.admin_ids) and m.from_user.id in svc.cfg.admin_ids


@router.message(F.text.regexp(r"^/(stats|dashboard)\b"), is_admin)
async def on_admin_stats(m: Message, svc: Services) -> None:
    from aiogram.types import FSInputFile
    from core import experiments as X
    from obs.dashboard import render_png
    from obs.stats import stats_text
    parts = m.text.split()
    days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 7
    variants = X.variants_of(svc.offer)
    labels = {v: X.label(svc.offer, v) for v in variants}
    text = stats_text(svc.store, days, variants, labels, svc.offer.default_set["code"])
    if parts[0].startswith("/dashboard"):
        png = render_png(svc.store, svc.cfg.base_dir / "var" / "dashboard.jpg", days, variants, labels, "Olavita · дашборд", svc.offer.default_set["code"])
        await svc.bot.send_photo(m.chat.id, FSInputFile(png), caption=text[:1000])
    else:
        await m.reply(text)


@router.message(F.text.regexp(r"^/close_(\d+)"), is_admin)
async def on_admin_close(m: Message, svc: Services) -> None:
    uid = int(re.match(r"^/close_(\d+)", m.text).group(1))
    await handoff.close(svc, svc.bot, uid)
    await m.reply("↩️ Повернуто боту.")


@router.message(F.reply_to_message, is_admin)
async def on_admin_reply(m: Message, svc: Services) -> None:
    src = m.reply_to_message.text or m.reply_to_message.caption or ""
    mm = re.search(r"\bid (\d+)\b", src)
    if not mm:
        await m.reply("Не бачу id клієнта в повідомленні, на яке відповідаєте.")
        return
    ch = svc.store.get_chat(int(mm.group(1)))
    if not ch:
        await m.reply("Клієнта не знайдено.")
        return
    if ch.get("mode") != "human":
        svc.store.update_chat(ch["tg_user_id"], mode="human")
        svc.store.open_handoff(ch["tg_user_id"], None, None, "manager_joined")
    await handoff.relay_manager_to_client(svc, svc.bot, ch, m)
    await m.reply("✅ Надіслано клієнту.")



# ---------- /stop, /help ----------
@router.message(F.text.regexp(r"^/(stop|стоп)\b"))
async def on_stop(m: Message, svc: Services) -> None:
    chat, order = ctx(svc, m)
    svc.store.add_message(chat["tg_user_id"], "user", "/stop", tg_message_id=m.message_id)
    svc.store.update_chat(chat["tg_user_id"], opted_out_utc=now_utc())
    if order and order["stage"] in S.COLLECT_STAGES:
        svc.store.transition(order["id"], S.CANCELLED, "stop_command")
        svc.store.funnel("cancelled_before_ship", chat["tg_user_id"], order["id"], {"reason": "stop"})
    svc.store.funnel("opted_out", chat["tg_user_id"], order and order["id"], {"via": "stop"})
    await send(svc, chat, T.opted_out(), K.remove_kb())


@router.message(F.text.regexp(r"^/help\b"))
async def on_help(m: Message, svc: Services) -> None:
    chat, order = ctx(svc, m)
    svc.store.add_message(chat["tg_user_id"], "user", "/help", tg_message_id=m.message_id)
    await send(svc, chat, T.help_text(svc.offer),
               K.yes_no_kb("Так, покличте людину", "Ні, продовжимо", "hand:yes", "hand:no"))


# ---------- /start ----------
@router.message(CommandStart())
async def on_start(m: Message, command: CommandObject, svc: Services) -> None:
    code, utm = parse_start(command.args)
    if not code:
        code = svc.offer.default_set["code"]      # без deep-link = товар з лендингу, без екрана вибору
    u = m.from_user
    chat = svc.store.upsert_chat(u.id, m.chat.id, u.username, u.first_name, utm=utm, start_payload=command.args)
    if not chat.get("variant"):
        svc.store.update_chat(u.id, variant=X.pick(u.id, X.variants_of(svc.offer)), last_name=getattr(u, "last_name", None))
        chat = svc.store.get_chat(u.id)
    elif getattr(u, "last_name", None) and not chat.get("last_name"):
        svc.store.update_chat(u.id, last_name=u.last_name)
    svc.store.add_message(u.id, "user", f"/start {command.args or ''}".strip(), tg_message_id=m.message_id)
    order = svc.store.active_order(u.id)
    # тест-режим / адмін: /start завжди починає заново (видалив чат → пройшов шлях з нуля)
    if order and (svc.cfg.env == "test" or u.id in svc.cfg.admin_ids) and order["stage"] not in (S.SHIPPED, S.ARRIVED):
        svc.store.transition(order["id"], S.CANCELLED, "reset_by_start")
        svc.store.c.execute("UPDATE outbox SET state='failed', last_error='reset' WHERE kind='lpcrm_create' AND ref_id=? AND state='pending'", (str(order["id"]),))
        svc.store.update_chat(u.id, flags={}, mode="bot", opted_out_utc=None)
        order = None
    if order and order["stage"] not in S.COLLECT_STAGES:
        await send(svc, chat, "Ваше замовлення в роботі ✅ Якщо є питання — пишіть сюди.")
        return
    if order:
        svc.store.set_flag(u.id, "reentry", True)
    if not order:
        s = svc.offer.set(code) if code else None
        order = svc.store.create_order(u.id, s and s["code"], s and int(s["price"]), utm, phone=chat.get("phone"), name=chat.get("name"))
    svc.store.funnel("bot_start", u.id, order["id"], {"set": code, **utm})
    if chat.get("mode") == "human":
        svc.store.update_chat(u.id, mode="bot")
        svc.store.close_handoff(u.id)
    last = svc.store.last_shipped_order(u.id)
    if last and order["stage"] == S.NEW:
        s = svc.offer.set(code) if code else (svc.offer.set(last["set_code"]) if svc.offer.has_set(last.get("set_code")) else svc.offer.default_set)
        svc.store.update_order(order["id"], set_code=s["code"], price_uah=int(s["price"]))
        svc.store.funnel("repeat_offer_shown", u.id, order["id"])
        await send_card(svc, chat, card_for_set(s["code"]), T.repeat_offer(svc.offer, s, last, last.get("name")), K.repeat_kb(s["code"]))
        return
    await send_voice(svc, chat, V.phrase_greeting(), wait=False)
    default_bundle = X.vcfg(svc.offer, chat.get("variant"), "entry_default_set")
    if default_bundle and svc.offer.has_set(default_bundle) and (not code or code == svc.offer.default_set["code"]):
        bundle, single = svc.offer.set(default_bundle), svc.offer.default_set
        svc.store.funnel("bundle_entry_shown", u.id, order["id"], {"bundle": default_bundle})
        await send_card(svc, chat, card_for_set(default_bundle), T.greet_bundle(svc.offer, bundle, single), K.bundle_entry_kb(svc.offer, bundle, single))
    elif code:
        s = svc.offer.set(code)
        if order["stage"] == S.NEW:
            svc.store.transition(order["id"], S.PHONE, "set_chosen")
        svc.store.funnel("phone_requested", u.id, order["id"])
        await send_card(svc, chat, card_for_set(code), T.greet_with_set(svc.offer, s, chat.get("variant")), K.phone_kb())
    else:
        await send_card(svc, chat, "sets", T.greet_choose(svc.offer), K.sets_kb(svc.offer))


# ---------- выбор набора ----------
@router.callback_query(F.data.startswith("set:"))
async def on_set(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    code = cb.data.split(":", 1)[1]
    if code == "choose":
        await send_card(svc, chat, "sets", T.choose_sets(svc.offer), K.sets_kb(svc.offer))
        return
    if not svc.offer.has_set(code):
        return
    s = svc.offer.set(code)
    if order and order["stage"] not in S.COLLECT_STAGES:
        await handoff.open(svc, svc.bot, chat, order, f"змінити набір на {code} після підтвердження")
        return
    if not order:
        order = svc.store.create_order(chat["tg_user_id"], code, int(s["price"]), chat.get("utm"), phone=chat.get("phone"), name=chat.get("name"))
    else:
        if order.get("set_code") and int(s["price"]) < int(svc.offer.set(order["set_code"])["price"]):
            svc.store.set_flag(chat["tg_user_id"], "downgraded", True)
        svc.store.update_order(order["id"], set_code=code, price_uah=int(s["price"]))
    svc.store.add_message(chat["tg_user_id"], "user", f"[обрав набір {s['label']}]")
    svc.store.funnel("set_chosen", chat["tg_user_id"], order["id"], {"set": code})
    order = svc.store.get_order(order["id"])
    if order["stage"] in (S.NEW, S.PHONE) and not order.get("phone"):
        await step_phone(svc, chat, order)
    elif order["stage"] == S.REVIEW or not S.ready_to_confirm(order):
        await step_summary(svc, chat, order)
    else:
        await _repeat_step(svc, chat, order)


# ---------- телефон ----------
async def _accept_phone(svc: Services, chat: dict, order: dict | None, phone: str, method: str) -> None:
    uid = chat["tg_user_id"]
    svc.store.update_chat(uid, phone=phone)
    if not order:
        order = svc.store.create_order(uid, None, None, chat.get("utm"), phone=phone, name=chat.get("name"))
    svc.store.update_order(order["id"], phone=phone)
    svc.store.funnel("phone_received", uid, order["id"], {"method": method})
    dup = svc.store.recent_order_by_phone(phone, 72)
    if dup and dup["id"] != order["id"] and dup["stage"] not in S.COLLECT_STAGES:
        s = svc.offer.set(dup["set_code"]) if dup.get("set_code") else None
        await send(svc, chat, f"У вас уже є замовлення №{dup['id']}" + (f" ({s['label']}, {svc.offer.fmt_price(int(s['price']))})" if s else "") + ". Оформити ще одне чи це повтор?",
                   K.yes_no_kb("Оформити ще одне", "Це повтор, не треба", "dup:new", "dup:stop"))
        return
    order = svc.store.get_order(order["id"])
    if order["stage"] in (S.NEW, S.PHONE):
        if order["stage"] == S.NEW:
            svc.store.transition(order["id"], S.PHONE, "phone_step")
        svc.store.transition(order["id"], S.NAME, "phone_received")
        if not order.get("set_code"):
            svc.store.update_order(order["id"], set_code=svc.offer.default_set["code"], price_uah=int(svc.offer.default_set["price"]))
        await step_name(svc, chat, order)
    else:
        await step_summary(svc, chat, order)


@router.message(F.contact)
async def on_contact(m: Message, svc: Services) -> None:
    chat, order = ctx(svc, m)
    if m.contact.user_id and m.contact.user_id != m.from_user.id:
        await send(svc, chat, "Це контакт іншої людини. Надішліть, будь ласка, свій номер кнопкою нижче.", K.phone_kb())
        return
    phone = normalize_phone(m.contact.phone_number)
    svc.store.add_message(chat["tg_user_id"], "user", "[надіслав контакт]", tg_message_id=m.message_id)
    if not phone:
        await send(svc, chat, T.phone_invalid(), K.phone_kb())
        return
    await _accept_phone(svc, chat, order, phone, "contact")


@router.callback_query(F.data.startswith("dup:"))
async def on_dup(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if cb.data == "dup:stop":
        if order and order["stage"] in S.COLLECT_STAGES:
            svc.store.transition(order["id"], S.CANCELLED, "duplicate")
        await send(svc, chat, "Добре, нове не оформлюю. Якщо буде питання по замовленню — пишіть сюди.", K.remove_kb())
        return
    if order:
        svc.store.transition(order["id"], S.NAME, "phone_received") if order["stage"] == S.PHONE else None
        await step_name(svc, chat, order)


# ---------- имя ----------
@router.callback_query(F.data.startswith("name:"))
async def on_name_cb(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if not order:
        return
    parts = cb.data.split(":", 2)
    if parts[1] == "first" and len(parts) > 2:
        svc.store.set_flag(chat["tg_user_id"], "pending_first", parts[2])
        await send(svc, chat, T.ask_surname(parts[2]), K.remove_kb())
        return
    if parts[1] == "yes":
        full = parts[2] if len(parts) > 2 and parts[2] else (_tg_full_name(svc.store.get_chat(chat["tg_user_id"]) or chat) or "")
        if not full:
            await send(svc, chat, T.ask_name(), K.remove_kb())
            return
        svc.store.update_order(order["id"], name=full)
        svc.store.update_chat(chat["tg_user_id"], name=full)
        _prewarm(svc, chat, full)
        svc.store.funnel("name_received", chat["tg_user_id"], order["id"], {"prefill": True})
        if order["stage"] == S.NAME:
            svc.store.transition(order["id"], S.CITY, "name_received")
        order = svc.store.get_order(order["id"])
        await (step_city if order["stage"] == S.CITY else step_summary)(svc, chat, order)
    else:
        await send(svc, chat, T.ask_name(), K.remove_kb())


# ---------- город ----------
@router.callback_query(F.data.startswith("city:"))
async def on_city_cb(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if not order:
        return
    ref = cb.data.split(":", 1)[1]
    from core.tools import ToolCtx, exec_tool
    res = await exec_tool(ToolCtx(svc.store, svc.offer, svc.np, chat, order), "set_city", {"ref": ref})
    if res.get("error"):
        await send(svc, chat, T.city_not_found())
        return
    svc.store.funnel("city_received", chat["tg_user_id"], order["id"])
    order = svc.store.get_order(order["id"])
    flags = (svc.store.get_chat(chat["tg_user_id"]) or {}).get("flags", {})
    num = flags.pop("pending_wh_num", None)
    if num:
        svc.store.update_chat(chat["tg_user_id"], flags=flags)
        whs = await svc.np.warehouses(order["np_city_ref"], str(num), limit=6, postomat=False)
        if len(whs) == 1:
            await exec_tool(ToolCtx(svc.store, svc.offer, svc.np, chat, order), "set_warehouse", {"ref": whs[0]["ref"]})
            svc.store.funnel("warehouse_received", chat["tg_user_id"], order["id"], {"type": "warehouse", "combined": True})
            await after_warehouse(svc, chat, order)
            return
    await step_warehouse(svc, chat, order)


# ---------- відділення ----------
@router.callback_query(F.data.startswith("wh:"))
async def on_wh_cb(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if not order or not order.get("np_city_ref"):
        return
    arg = cb.data.split(":", 1)[1]
    if arg == "other":
        await send(svc, chat, "Напишіть номер відділення або вулицю — підберу.")
        return
    if arg == "postomat":
        await send(svc, chat, T.postomat_warning(), K.postomat_confirm_kb())
        return
    if arg == "postomat_ok":
        await step_warehouse(svc, chat, order, "", postomat=True)
        return
    from core.tools import ToolCtx, exec_tool
    tctx = ToolCtx(svc.store, svc.offer, svc.np, chat, order)
    res = await exec_tool(tctx, "set_warehouse", {"ref": arg})
    if res.get("error"):
        await send(svc, chat, T.warehouse_not_found())
        return
    svc.store.funnel("warehouse_received", chat["tg_user_id"], order["id"], {"type": res.get("type")})
    await after_warehouse(svc, chat, order)


# ---------- апсейл ----------
@router.callback_query(F.data.startswith("up:"))
async def on_upsell(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if not order:
        return
    _, ans, code = cb.data.split(":", 2)
    svc.store.add_message(chat["tg_user_id"], "user", "[апсейл: " + ("так" if ans == "yes" else "ні") + "]")
    if svc.store.has_event(order["id"], "upsell_answered"):
        return
    svc.store.event(order["id"], "upsell_answered", meta={"answer": ans, "to": code})
    if ans == "yes" and svc.offer.has_set(code):
        if order["stage"] != S.CONFIRMED:
            # CRM уже отримала замовлення — доповнює менеджер
            svc.store.event(order["id"], "note", dedup_key="upsell_late", meta={"text": f"клієнт хоче додати набір {code} після відправки в CRM"})
            svc.store.funnel("upsell_accepted", chat["tg_user_id"], order["id"], {"to": code, "late": True})
            await handoff.open(svc, svc.bot, chat, order, f"додати до замовлення: {code}")
            return
        svc.store.update_order(order["id"], set_code=code, price_uah=int(svc.offer.set(code)["price"]), upsell_accepted=1)
        svc.store.funnel("upsell_accepted", chat["tg_user_id"], order["id"], {"to": code})
        await send(svc, chat, T.upsell_accepted(svc.offer, svc.store.get_order(order["id"])))
    else:
        svc.store.update_order(order["id"], upsell_accepted=0)
        svc.store.funnel("upsell_declined", chat["tg_user_id"], order["id"], {"to": code})
        await send(svc, chat, T.upsell_declined(svc.offer, svc.store.get_order(order["id"])))
    # відправляємо в CRM без очікування
    svc.store.c.execute("UPDATE outbox SET next_try_utc=? WHERE kind='lpcrm_create' AND ref_id=? AND state='pending'",
                        (now_utc(), str(order["id"])))


# ---------- подтверждение / правки ----------
@router.callback_query(F.data.startswith("confirm:"))
async def on_confirm(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb, "Дякую!")
    chat, order = ctx(svc, cb)
    if not order:
        return
    svc.store.add_message(chat["tg_user_id"], "user", "[натиснув Підтверджую]")
    await do_confirm(svc, chat, order)


@router.callback_query(F.data.startswith("edit:"))
async def on_edit(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if not order:
        return
    what = cb.data.split(":", 1)[1]
    if order["stage"] not in S.COLLECT_STAGES and what != "menu":
        if what == "cancel":
            await send(svc, chat, T.cancel_confirm(order), K.yes_no_kb("Так, скасувати", "Ні, лишити", "cancel:yes", "cancel:no"))
        else:
            await handoff.open(svc, svc.bot, chat, order, "змінити дані після підтвердження")
        return
    if what == "menu":
        await send(svc, chat, "Що змінити?", K.edit_kb())
    elif what == "set":
        await send_card(svc, chat, "sets", T.choose_sets(svc.offer), K.sets_kb(svc.offer))
    elif what == "name":
        if order["stage"] == S.REVIEW:
            svc.store.transition(order["id"], S.NAME, "edit_name")
        svc.store.update_order(order["id"], name=None)
        await send(svc, chat, T.ask_name(), K.remove_kb())
    elif what == "city":
        if order["stage"] == S.REVIEW:
            svc.store.transition(order["id"], S.CITY, "edit_city")
        svc.store.update_order(order["id"], np_city_ref=None, np_city_name=None, np_wh_ref=None, np_wh_name=None)
        await step_city(svc, chat, svc.store.get_order(order["id"]))
    elif what == "cancel":
        await _cancel_order(svc, chat, order, "button")


@router.callback_query(F.data.startswith("repeat:"))
async def on_repeat(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    _, ans, code = cb.data.split(":", 2)
    last = svc.store.last_shipped_order(chat["tg_user_id"])
    if not order or not last:
        return
    s = svc.offer.set(code) if svc.offer.has_set(code) else svc.offer.default_set
    svc.store.update_order(order["id"], set_code=s["code"], price_uah=int(s["price"]))
    if ans == "yes":
        svc.store.update_order(order["id"], phone=last["phone"], name=last["name"], np_city_ref=last["np_city_ref"],
                               np_city_name=last["np_city_name"], np_wh_ref=last["np_wh_ref"], np_wh_name=last["np_wh_name"],
                               delivery_type=last.get("delivery_type") or "warehouse")
        for st_ in (S.PHONE, S.NAME, S.CITY, S.WAREHOUSE, S.REVIEW):
            svc.store.transition(order["id"], st_)
        svc.store.funnel("repeat_accepted", chat["tg_user_id"], order["id"])
        await step_summary(svc, chat, svc.store.get_order(order["id"]))
    else:
        svc.store.update_order(order["id"], phone=last["phone"], name=last["name"])
        svc.store.transition(order["id"], S.PHONE)
        svc.store.transition(order["id"], S.NAME)
        svc.store.transition(order["id"], S.CITY)
        await step_city(svc, chat, svc.store.get_order(order["id"]))


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel_cb(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if not order:
        return
    if cb.data == "cancel:no":
        await send(svc, chat, "Добре, замовлення лишається ✅")
        return
    await _cancel_order(svc, chat, order, "button_after_confirm")


async def _cancel_order(svc: Services, chat: dict, order: dict, by: str) -> None:
    if order["stage"] in (S.SHIPPED, S.ARRIVED):
        await handoff.open(svc, svc.bot, chat, order, "скасування після відправки")
        return
    svc.store.c.execute("UPDATE outbox SET state='failed', last_error='cancelled' WHERE kind='lpcrm_create' AND ref_id=? AND state='pending'", (str(order["id"]),))
    svc.store.transition(order["id"], S.CANCELLED, "cancelled", meta={"by": by})
    svc.store.funnel("cancelled_before_ship", chat["tg_user_id"], order["id"], {"stage": order["stage"], "by": by})
    await send(svc, chat, T.cancelled(), K.remove_kb())
    if order.get("lpcrm_order_id"):
        from core.outbox import alert
        await alert(svc, f"❗️ Клієнт скасував замовлення #{order['id']} (CRM {order['lpcrm_order_id']}) — зняти в CRM.")


# ---------- после отправки: забрать / не забрать ----------
@router.callback_query(F.data.startswith("pick:"))
async def on_pick(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, _ = ctx(svc, cb)
    try:
        _, ans, oid = cb.data.split(":", 2)
        order = svc.store.get_order(int(oid))
    except ValueError:
        return
    if not order or order["chat_id"] != chat["tg_user_id"]:
        return
    svc.store.funnel("pickup_intent", chat["tg_user_id"], order["id"], {"answer": ans})
    svc.store.event(order["id"], "pickup_intent", dedup_key=ans, meta={"answer": ans})
    if ans == "no":
        svc.store.event(order["id"], "not_picked_up_announced")
        await send(svc, chat, T.not_pick_ack())
    elif ans == "extend":
        await handoff.open(svc, svc.bot, chat, order, "продовжити зберігання на НП", notify_client=False)
        await send(svc, chat, "Передам, щоб продовжили зберігання — напишу, коли буде готово 💛")
    elif ans == "weekend":
        await send(svc, chat, "Добре, на вихідних 💛 Нагадаю в суботу зранку.")
    elif ans == "tomorrow":
        await send(svc, chat, "Добре, до завтра 💛")
    else:
        await send(svc, chat, "Чудово! Огляньте перед оплатою — і гарного дня 💛")


# ---------- nudges / handoff-оффер ----------
@router.callback_query(F.data.startswith("nudge:"))
async def on_nudge(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if cb.data == "nudge:stop":
        svc.store.update_chat(chat["tg_user_id"], opted_out_utc=now_utc())
        if order and order["stage"] in S.COLLECT_STAGES:
            svc.store.transition(order["id"], S.CANCELLED, "not_interested")
            svc.store.funnel("cancelled_before_ship", chat["tg_user_id"], order["id"], {"reason": "not_interested"})
        await send(svc, chat, T.opted_out(), K.remove_kb())
        return
    if order:
        await (step_summary if order["stage"] in (S.UPSELL, S.REVIEW) else _repeat_step)(svc, chat, order)


@router.callback_query(F.data.startswith("hand:"))
async def on_hand(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb)
    chat, order = ctx(svc, cb)
    if cb.data == "hand:yes":
        await handoff.open(svc, svc.bot, chat, order, "client_request")
    else:
        svc.store.set_flag(chat["tg_user_id"], "no_progress", 0)
        if order:
            await _repeat_step(svc, chat, order)


# ---------- свободный текст ----------
@router.message(F.text)
async def on_text(m: Message, svc: Services) -> None:
    chat, order = ctx(svc, m)
    text = m.text.strip()
    uid = chat["tg_user_id"]
    svc.store.add_message(uid, "user", text, tg_message_id=m.message_id)
    if detect_russian(text) and not chat.get("lang_hint"):
        svc.store.update_chat(uid, lang_hint="ru")

    # human-режим: всё менеджеру
    if chat.get("mode") == "human":
        await handoff.relay_client_to_topic(svc, svc.bot, chat, m)
        return

    if ONLY_ONE_RX.search(text):
        svc.store.set_flag(uid, "said_only_one", True)
    if PRICE_OBJ_RX.search(text):
        svc.store.set_flag(uid, "objection_price", True)
        if order:
            svc.store.funnel("objection", uid, order["id"], {"type": "price", "stage": order["stage"]})

    # «скасувати» / «не треба» — детерминированно, с учётом контекста
    if order and CANCEL_RX.search(text) and len(text.split()) <= 4:
        if (order.get("upsell_shown") and not svc.store.has_event(order["id"], "upsell_answered")
                and not re.search(r"скасу|отмен|відмін", text, re.IGNORECASE)):
            svc.store.event(order["id"], "upsell_answered", meta={"answer": "no_text"})
            svc.store.update_order(order["id"], upsell_accepted=0)
            svc.store.funnel("upsell_declined", uid, order["id"], {"via": "text"})
            svc.store.c.execute("UPDATE outbox SET next_try_utc=? WHERE kind='lpcrm_create' AND ref_id=? AND state='pending'", (now_utc(), str(order["id"])))
            await send(svc, chat, T.upsell_declined(svc.offer, order))
            return
        if order["stage"] in S.COLLECT_STAGES:
            await _cancel_order(svc, chat, order, "text")
            return
        if order["stage"] in S.PRE_SHIP_STAGES:
            await send(svc, chat, T.cancel_confirm(order), K.yes_no_kb("Так, скасувати", "Ні, лишити", "cancel:yes", "cancel:no"))
            return
        await handoff.open(svc, svc.bot, chat, order, "cancel_after_ship")
        return

    if not order:
        order = svc.store.create_order(uid, None, None, chat.get("utm"), phone=chat.get("phone"), name=chat.get("name"))
        svc.store.funnel("bot_start", uid, order["id"], {"set": None, "via": "text"})

    stage = order["stage"]
    short = len(text.split()) <= 3 and "?" not in text

    # PHONE: ручной ввод
    if stage in (S.NEW, S.PHONE):
        phone = normalize_phone(text)
        if phone:
            await _accept_phone(svc, chat, order, phone, "manual")
            return
        if len(re.sub(r"\D", "", text)) >= 7:
            await send(svc, chat, T.phone_invalid(), K.phone_kb())
            return
        if not order.get("set_code") and short:
            await send_card(svc, chat, "sets", T.greet_choose(svc.offer), K.sets_kb(svc.offer))
            return

    # NAME
    if stage == S.NAME and len(text.split()) <= 4 and "?" not in text:
        nm = re.sub(r"\s+", " ", text).strip()
        pend = (chat.get("flags") or {}).get("pending_first")
        if pend and NAME_RX.match(nm) and len(nm.split()) == 1:
            nm = f"{pend} {nm}"
            _prewarm(svc, chat, nm)
            flags = chat.get("flags") or {}; flags.pop("pending_first", None); svc.store.update_chat(uid, flags=flags)
        if NAME_RX.match(nm) and len(nm.split()) == 1:
            await send(svc, chat, T.name_need_surname())
            return
        if NAME_RX.match(nm):
            svc.store.update_order(order["id"], name=nm)
            svc.store.update_chat(uid, name=nm)
            _prewarm(svc, chat, nm)
            svc.store.transition(order["id"], S.CITY, "name_received")
            svc.store.funnel("name_received", uid, order["id"], {"prefill": False})
            await step_city(svc, chat, svc.store.get_order(order["id"]))
            return
        if re.search(r"[A-Za-z]", nm):
            await send(svc, chat, T.name_invalid())
            return

    # CITY: «Київ, 12» / «Київ 12» / «Київ»
    if stage == S.CITY and len(text.split()) <= 5 and "?" not in text:
        m = re.match(r"^\s*([^\d,]+?)[\s,]*(?:№\s*)?(\d{1,4})?\s*$", text)
        if m and not re.search(r"[a-zA-Z]", text):
            city_q, wh_num = m.group(1).strip(), m.group(2)
            cities = await svc.np.search_cities(city_q)
            if len(cities) == 1:
                from core.tools import ToolCtx, exec_tool
                await exec_tool(ToolCtx(svc.store, svc.offer, svc.np, chat, order), "set_city", {"ref": cities[0]["ref"]})
                svc.store.funnel("city_received", uid, order["id"])
                order = svc.store.get_order(order["id"])
                if wh_num:
                    whs = await svc.np.warehouses(order["np_city_ref"], wh_num, limit=6, postomat=False)
                    if len(whs) == 1:
                        await exec_tool(ToolCtx(svc.store, svc.offer, svc.np, chat, order), "set_warehouse", {"ref": whs[0]["ref"]})
                        svc.store.funnel("warehouse_received", uid, order["id"], {"type": "warehouse", "combined": True})
                        await after_warehouse(svc, chat, order)
                        return
                    await send(svc, chat, f"Відділення №{wh_num} у цьому місті не знайшла — оберіть зі списку або напишіть вулицю:")
                await step_warehouse(svc, chat, order)
                return
            if cities:
                if wh_num:
                    svc.store.set_flag(uid, "pending_wh_num", wh_num)
                await send(svc, chat, "Уточніть, будь ласка, населений пункт:", K.cities_kb(cities))
                return
            if len(city_q) >= 3:
                await send(svc, chat, T.city_not_found())
                return

    # WAREHOUSE
    if stage == S.WAREHOUSE and short:
        postomat = "поштомат" in text.lower() and bool(svc.offer.delivery.get("postomat_allowed"))
        whs = await svc.np.warehouses(order["np_city_ref"], text if not postomat else "", limit=6, postomat=postomat)
        if len(whs) == 1 and not postomat:
            from core.tools import ToolCtx, exec_tool
            await exec_tool(ToolCtx(svc.store, svc.offer, svc.np, chat, order), "set_warehouse", {"ref": whs[0]["ref"]})
            svc.store.funnel("warehouse_received", uid, order["id"], {"type": "warehouse"})
            await after_warehouse(svc, chat, order)
            return
        if whs:
            if postomat:
                await send(svc, chat, T.postomat_warning(), K.postomat_confirm_kb())
            else:
                await send(svc, chat, "Оберіть відділення:", K.warehouses_kb(whs, svc.offer.delivery.get("postomat_allowed", False)))
            return
        if re.fullmatch(r"[\d№ ]+", text):
            await send(svc, chat, T.warehouse_not_found())
            return

    # банк заперечень — миттєво, без LLM
    ob = OBJ.match(svc.objections, text)
    if ob:
        svc.store.funnel("objection", uid, order["id"], {"type": ob.key, "stage": stage, "deterministic": True})
        if ob.key == "only_one":
            svc.store.set_flag(uid, "said_only_one", True)
            if stage in S.COLLECT_STAGES and order.get("set_code") != svc.offer.default_set["code"]:
                svc.store.update_order(order["id"], set_code=svc.offer.default_set["code"], price_uah=int(svc.offer.default_set["price"]))
        await send(svc, chat, ob.answer, K.phone_kb() if stage in (S.NEW, S.PHONE) else None)
        if ob.handoff:
            await handoff.open(svc, svc.bot, chat, order, ob.key, notify_client=False)
            return
        if ob.key != "think" and stage in S.COLLECT_STAGES and stage not in (S.NEW, S.PHONE):
            await (step_summary if stage in (S.UPSELL, S.REVIEW) else _repeat_step)(svc, chat, order)
        return

    # всё остальное — LLM
    await run_agent(svc, chat, order, m)


@router.message(F.location)
async def on_location(m: Message, svc: Services) -> None:
    chat, order = ctx(svc, m)
    svc.store.add_message(chat["tg_user_id"], "user", "[надіслав геолокацію]", tg_message_id=m.message_id)
    if not order or order["stage"] not in (S.CITY, S.WAREHOUSE):
        await send(svc, chat, "Дякую! Геолокація знадобиться на кроці доставки.")
        return
    lat, lon = m.location.latitude, m.location.longitude
    city_name = await svc.np.reverse_city(lat, lon)
    cities = await svc.np.search_cities(city_name) if city_name else []
    if not cities:
        svc.store.funnel("geo_failed", chat["tg_user_id"], order["id"])
        await send(svc, chat, "Не змогла визначити місто за геолокацією. Напишіть, будь ласка, назву міста.", K.remove_kb())
        return
    if len(cities) > 1 and not (cities[0].get("warehouses") or 0) >= 50:
        await send(svc, chat, "Уточніть, будь ласка, населений пункт:", K.cities_kb(cities))
        return
    from core.tools import ToolCtx, exec_tool
    await exec_tool(ToolCtx(svc.store, svc.offer, svc.np, chat, order), "set_city", {"ref": cities[0]["ref"]})
    order = svc.store.get_order(order["id"])
    svc.store.funnel("city_received", chat["tg_user_id"], order["id"], {"via": "geo"})
    near = await svc.np.nearest(order["np_city_ref"], lat, lon, limit=3)
    if not near or near[0].get("dist_m", 0) > 30_000:
        svc.store.funnel("geo_failed", chat["tg_user_id"], order["id"], {"reason": "far_or_empty"})
        await step_warehouse(svc, chat, order)
        return
    await send(svc, chat, T.nearest_found(order["np_city_name"]), K.nearest_kb(near))


@router.message(~F.text & ~F.contact & ~F.location)
async def on_other(m: Message, svc: Services) -> None:
    chat, order = ctx(svc, m)
    svc.store.add_message(chat["tg_user_id"], "user", "[медіа/голосове]", tg_message_id=m.message_id)
    if chat.get("mode") == "human":
        await handoff.relay_client_to_topic(svc, svc.bot, chat, m)
        return
    await send(svc, chat, "Я читаю лише текст 🙂 Напишіть, будь ласка, словами — або натисніть кнопку нижче.",
               K.phone_kb() if order and not order.get("phone") else None)
