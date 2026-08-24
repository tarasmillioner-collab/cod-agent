"""Группа менеджеров (форум): ответы в топиках → клиенту; команды /bot, /stats, /order, /close."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from core import handoff
from core.services import Services
from obs.stats import stats_text


async def ack(cb, text: str | None = None) -> None:
    """cb.answer, який не падає на застарілих callback після рестарту."""
    try:
        await cb.answer(text)
    except Exception:  # noqa: BLE001
        pass

log = logging.getLogger("admin")
router = Router(name="admin")
router.message.filter(F.chat.type.in_({"group", "supergroup"}))
router.callback_query.filter(F.message.chat.type.in_({"group", "supergroup"}))


def _is_admin(svc: Services, user_id: int) -> bool:
    return not svc.cfg.admin_ids or user_id in svc.cfg.admin_ids


@router.message(Command("bot"))
async def cmd_bot(m: Message, command: CommandObject, svc: Services) -> None:
    if not _is_admin(svc, m.from_user.id):
        return
    arg = (command.args or "status").strip().lower()
    if arg == "off":
        svc.store.set_setting("bot_enabled", "0")
        await m.reply("🔴 Бот вимкнено: нові діалоги йдуть менеджерам, сповіщення про доставку працюють.")
    elif arg == "on":
        svc.store.set_setting("bot_enabled", "1")
        await m.reply("🟢 Бот увімкнено.")
    else:
        en = svc.store.bot_enabled()
        usd = svc.store.usage_today_usd()
        await m.reply(f"{'🟢 увімкнено' if en else '🔴 вимкнено'} · LLM сьогодні ≈ ${usd:.2f} / cap ${svc.cfg.llm_daily_usd_cap:.0f} · DRY_RUN={'так' if svc.lpcrm.dry_run else 'ні'}")


@router.message(Command("stats"))
async def cmd_stats(m: Message, command: CommandObject, svc: Services) -> None:
    if not _is_admin(svc, m.from_user.id):
        return
    days = 1
    if command.args and command.args.strip().rstrip("d").isdigit():
        days = int(command.args.strip().rstrip("d"))
    from core import experiments as X
    variants = X.variants_of(svc.offer)
    await m.reply(stats_text(svc.store, days, variants, {v: X.label(svc.offer, v) for v in variants}, svc.offer.default_set["code"]))


@router.message(Command("order"))
async def cmd_order(m: Message, command: CommandObject, svc: Services) -> None:
    if not (command.args and command.args.strip().isdigit()):
        await m.reply("/order <id>")
        return
    o = svc.store.get_order(int(command.args.strip()))
    if not o:
        await m.reply("Немає такого замовлення.")
        return
    ch = svc.store.get_chat(o["chat_id"]) or {}
    await m.reply(handoff.order_card(svc, ch, o, "(/order)"))


@router.message(Command("close"))
async def cmd_close(m: Message, svc: Services) -> None:
    if not m.message_thread_id:
        await m.reply("Команда працює всередині теми клієнта.")
        return
    ch = svc.store.chat_by_topic(m.message_thread_id)
    if not ch:
        await m.reply("Не знайшла клієнта для цієї теми.")
        return
    await handoff.close(svc, svc.bot, ch["tg_user_id"])


@router.callback_query(F.data.startswith("mgr:close:"))
async def cb_close(cb: CallbackQuery, svc: Services) -> None:
    await ack(cb, "Повернуто боту")
    uid = int(cb.data.rsplit(":", 1)[1])
    await handoff.close(svc, svc.bot, uid)


@router.message(F.message_thread_id, ~F.text.startswith("/"))
async def on_manager_message(m: Message, svc: Services) -> None:
    """Любое сообщение менеджера в теме клиента → клиенту."""
    if m.from_user.is_bot:
        return
    if svc.cfg.managers_chat_id and m.chat.id != svc.cfg.managers_chat_id:
        return
    ch = svc.store.chat_by_topic(m.message_thread_id)
    if not ch:
        return
    if ch.get("mode") != "human":
        svc.store.update_chat(ch["tg_user_id"], mode="human")
        svc.store.open_handoff(ch["tg_user_id"], None, m.message_thread_id, "manager_joined")
    await handoff.relay_manager_to_client(svc, svc.bot, ch, m)
