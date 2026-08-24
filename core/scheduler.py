"""Фоновые тики в том же процессе (паттерн gopure scheduler): каждая джоба —
идемпотентна через order_events(dedup_key) и безопасна к рестарту.

outbox        10 с     заказы в LP-CRM, отложенные сообщения
poll_ttn      10 мин   ТТН появился в LP-CRM → shipped + сообщение
poll_np       30 мин   статус Нової Пошти → arrived/picked/returned + сообщения (07–22 Київ)
reminders     1 год    день 3 / день 5 / отзыв через 7 дней
nudges        5 мин    тишина 15 хв / 2 год / 24 год на этапе сбора; отложенные «нагадати»
digest        09:00    сводка в группу менеджеров
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from core import outbox
from core import state as S
from core.services import KYIV, Services, is_night, now_kyiv
from db import now_utc, parse_utc
from tg import keyboards as K
from tg import texts as T

log = logging.getLogger("scheduler")


def business_days_after(d: date, n: int) -> date:
    """НП працює пн–сб; неділя не рахується."""
    cur = d
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() != 6:
            added += 1
    return cur


async def _send(svc: Services, order: dict, text: str, kb=None, event: str | None = None) -> bool:
    """Отправить клиенту заказа с идемпотентностью по событию."""
    if event and svc.store.has_event(order["id"], event):
        return False
    chat = svc.store.get_chat(order["chat_id"])
    if not chat or chat.get("blocked_utc"):
        return False
    try:
        await svc.bot.send_message(chat["chat_id"], text, reply_markup=kb)
    except TelegramForbiddenError:
        svc.store.update_chat(chat["tg_user_id"], blocked_utc=now_utc())
        return False
    except TelegramRetryAfter as e:
        await asyncio.sleep(min(e.retry_after, 30))
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("send to %s failed: %s", chat["tg_user_id"], e)
        return False
    if event:
        svc.store.event(order["id"], event)
    svc.store.add_message(chat["tg_user_id"], "assistant", text)
    svc.store.touch_chat(chat["tg_user_id"], bot=True)
    return True


async def _voice(svc: Services, order: dict, kind: str) -> None:
    try:
        from core import names as N
        import voice as V
        from tg.handlers_client import send_voice
        chat = svc.store.get_chat(order["chat_id"])
        if not chat:
            return
        a = N.address(order.get("name"))
        text = {"arrived": V.phrase_arrived(a), "week": V.phrase_week(a), "nudge": V.phrase_nudge(a)}[kind]
        await send_voice(svc, chat, text, wait=False)
    except Exception as e:  # noqa: BLE001
        log.warning("voice %s failed: %s", kind, e)


# ---------- jobs ----------
async def job_poll_ttn(svc: Services) -> None:
    if svc.lpcrm.dry_run:
        return
    orders = [o for o in svc.store.orders_in((S.CONFIRMED_CRM,)) if o.get("lpcrm_order_id") and not o.get("ttn")]
    if not orders:
        return
    by_crm = {o["lpcrm_order_id"]: o for o in orders}
    for i in range(0, len(orders), 50):
        ids = [o["lpcrm_order_id"] for o in orders[i:i + 50]]
        try:
            data = await svc.lpcrm.orders_by_ids(ids)
        except Exception as e:  # noqa: BLE001
            log.warning("poll_ttn: %s", e)
            return
        for crm_id, d in data.items():
            o = by_crm.get(crm_id)
            if not o:
                continue
            status = str(d.get("status") or "")
            svc.store.update_order(o["id"], lpcrm_status=status)
            if status == "13":  # Відмова
                svc.store.transition(o["id"], S.CANCELLED, "crm_refused")
                continue
            ttn = (d.get("ttn") or "").strip()
            if ttn and ttn != "0":
                o = svc.store.transition(o["id"], S.SHIPPED, "shipped", ttn=ttn)
                svc.store.funnel("ttn_sent", o["chat_id"], o["id"])
                await _send(svc, o, T.shipped(svc.offer, o), None, event="shipped_sent")


async def job_poll_np(svc: Services) -> None:
    h = now_kyiv().hour
    if h < 7 or h >= 22:
        return
    orders = [o for o in svc.store.orders_in((S.SHIPPED, S.ARRIVED)) if o.get("ttn")]
    if not orders:
        return
    try:
        statuses = await svc.np.track([o["ttn"] for o in orders])
    except Exception as e:  # noqa: BLE001
        log.warning("poll_np: %s", e)
        return
    for o in orders:
        stt = statuses.get(o["ttn"])
        if not stt:
            continue
        code = stt["code"]
        svc.store.update_order(o["id"], np_status_code=code, np_status_text=stt["text"])
        target = S.stage_from_np(code)
        if target == S.ARRIVED and o["stage"] == S.SHIPPED:
            arrived_day = now_kyiv().date()
            until = business_days_after(arrived_day, int(svc.offer.storage["days"]))
            o = svc.store.transition(o["id"], S.ARRIVED, "arrived", storage_until=until.isoformat(), meta={"np": stt})
            svc.store.funnel("arrived_notified", o["chat_id"], o["id"])
            await _send(svc, o, T.arrived(svc.offer, o, until), K.arrived_kb(o["id"]), event="arrived_sent")
            await _voice(svc, o, "arrived")
        elif target == S.PICKED:
            o = svc.store.transition(o["id"], S.PICKED, "picked", meta={"np": stt})
            svc.store.funnel("picked_up", o["chat_id"], o["id"], {"set": o["set_code"]})
            await _send(svc, o, T.picked(svc.offer, o), None, event="picked_sent")
            svc.store.transition(o["id"], S.DONE, "done")
        elif target == S.RETURNED:
            o = svc.store.transition(o["id"], S.RETURNED, "returned", meta={"np": stt})
            announced = svc.store.has_event(o["id"], "not_picked_up_announced")
            svc.store.funnel("not_picked_up_announced" if announced else "not_picked_up_silent", o["chat_id"], o["id"], {"set": o["set_code"]})
            await _send(svc, o, T.returned(o), None, event="returned_sent")


async def job_reminders(svc: Services) -> None:
    if is_night():
        return
    now = datetime.now(timezone.utc)
    today = now_kyiv().date()
    for o in svc.store.orders_in((S.ARRIVED,)):
        if svc.store.has_event(o["id"], "not_picked_up_announced"):
            continue
        arrived = parse_utc(o.get("arrived_utc"))
        until = date.fromisoformat(o["storage_until"]) if o.get("storage_until") else None
        if arrived and now - arrived >= timedelta(days=3) and not svc.store.has_event(o["id"], "reminder_d3_sent"):
            if await _send(svc, o, T.reminder_d3(svc.offer, o, until), K.reminder_kb(o["id"]), event="reminder_d3_sent"):
                svc.store.funnel("reminder_d3_sent", o["chat_id"], o["id"])
            continue
        if until and today >= until and now_kyiv().hour >= 9 and not svc.store.has_event(o["id"], "reminder_d5_sent"):
            if await _send(svc, o, T.reminder_d5(o), K.reminder_kb(o["id"]), event="reminder_d5_sent"):
                svc.store.funnel("reminder_d5_sent", o["chat_id"], o["id"])
    for o in svc.store.orders_in((S.DONE,)):
        picked = parse_utc(o.get("picked_utc"))
        if not picked:
            continue
        if now - picked >= timedelta(days=1) and now - picked < timedelta(days=3):
            if await _send(svc, o, T.care_day1(svc.offer, o.get("name"), o.get("variant")), None, event="care_day1"):
                svc.store.funnel("care_day1", o["chat_id"], o["id"])
        if now - picked >= timedelta(days=25) and now - picked < timedelta(days=30) and svc.offer.has_set(o.get("set_code")):
            if await _send(svc, o, T.care_day25(svc.offer, svc.offer.set(o["set_code"]), o.get("name")), K.repeat_kb(o["set_code"]), event="care_day25"):
                svc.store.funnel("care_day25", o["chat_id"], o["id"])
        if now - picked >= timedelta(days=7) and now - picked < timedelta(days=10):
            if await _send(svc, o, T.review_request(o), None, event="review_requested"):
                svc.store.funnel("review_requested", o["chat_id"], o["id"])
                await _voice(svc, o, "week")


NUDGE_STEPS = [(15, "nudge_15"), (60, "nudge_60"), (120, "nudge_120")]
LEAD_TO_CRM_MIN = 180   # мовчить 3 години після телефону → у CRM як «Новий» на прозвон


async def job_nudges(svc: Services) -> None:
    st = svc.store
    now = datetime.now(timezone.utc)
    # 1) отложенные «нагадати через N годин»
    for row in st.c.execute("SELECT tg_user_id FROM chats WHERE flags_json LIKE '%reminder_due%' AND mode='bot' AND opted_out_utc IS NULL").fetchall():
        ch = st.get_chat(row[0])
        due = parse_utc((ch or {}).get("flags", {}).get("reminder_due"))
        if ch and due and now >= due and not is_night():
            flags = ch["flags"]
            flags.pop("reminder_due", None)
            st.update_chat(ch["tg_user_id"], flags=flags)
            o = st.active_order(ch["tg_user_id"])
            try:
                await svc.bot.send_message(ch["chat_id"], T.reminder_fire(svc.offer, o), reply_markup=K.nudge_kb(o["id"] if o else 0))
                st.add_message(ch["tg_user_id"], "assistant", T.reminder_fire(svc.offer, o))
                st.touch_chat(ch["tg_user_id"], bot=True)
                st.funnel("reminder_fired", ch["tg_user_id"], o and o["id"])
            except Exception as e:  # noqa: BLE001
                log.warning("reminder send failed: %s", e)
    if is_night():
        return
    # 2) тишина на этапе сбора
    for o in st.orders_in(S.COLLECT_STAGES):
        if o["stage"] in (S.NEW, S.PHONE):
            continue   # без телефону не реанімуємо і в CRM не віддаємо
        ch = st.get_chat(o["chat_id"])
        if not ch or ch.get("mode") != "bot" or ch.get("opted_out_utc") or ch.get("blocked_utc"):
            continue
        last_bot = parse_utc(ch.get("last_bot_utc"))
        last_seen = parse_utc(ch.get("last_seen_utc"))
        if not last_bot or (last_seen and last_seen > last_bot):
            continue  # клиент ответил последним — ждём бота, не пушим
        due = parse_utc((ch.get("flags") or {}).get("reminder_due"))
        if due and due > now:
            continue  # клієнт попросив нагадати пізніше — не чіпаємо і не віддаємо в CRM
        silent_min = (now - (last_seen or last_bot)).total_seconds() / 60   # тиша = від ОСТАННЬОГО слова клієнта
        if silent_min >= LEAD_TO_CRM_MIN:
            if o.get("phone"):
                st.transition(o["id"], S.LEAD_CRM, "lead_to_crm", meta={"silent_min": int(silent_min)})
                st.enqueue("lpcrm_create", f"lead{o['id']}", {"order_id": o["id"], "lead": True})
                st.funnel("lead_to_crm", o["chat_id"], o["id"], {"stage": o["stage"]})
            else:
                st.transition(o["id"], S.CANCELLED, "silence_no_phone")
                st.funnel("cancelled_before_ship", o["chat_id"], o["id"], {"reason": "silence", "stage": o["stage"]})
            continue
        for minutes, ev in reversed(NUDGE_STEPS):
            if silent_min >= minutes and not st.has_event(o["id"], ev):
                if any(st.has_event(o["id"], e2) for m2, e2 in NUDGE_STEPS if m2 > minutes):
                    break
                review = o["stage"] in (S.UPSELL, S.REVIEW)
                text = (T.nudge_review(svc.offer, o, minutes) if review and o.get("set_code")
                        else (T.nudge15(svc.offer, o.get("variant"), o.get("name"), S.steps_left(o)) if minutes <= 15
                              else T.nudge(o["stage"], minutes, o.get("name"), S.steps_left(o))))
                if review and o.get("set_code") and not S.ready_to_confirm(o):
                    kb = K.summary_kb(svc.offer, o)
                elif minutes <= 15 and o["stage"] == S.CITY:
                    kb = K.geo_kb()                          # 15 хв: конкретний крок + кнопка
                elif minutes <= 15 and o["stage"] in (S.NEW, S.PHONE):
                    kb = K.phone_kb()
                else:
                    kb = K.nudge_kb(o["id"])
                if await _send(svc, o, text, kb, event=ev):
                    st.funnel("nudge_sent", o["chat_id"], o["id"], {"timer": minutes, "stage": o["stage"]})
                    if minutes == 60:
                        await _voice(svc, o, "nudge")
                break


async def job_sla(svc: Services) -> None:
    """Handoff без відповіді менеджера 30 хв → алерт; approve за день < 60% при n≥20 → алерт."""
    st = svc.store
    now = datetime.now(timezone.utc)
    for h in st.c.execute("SELECT chat_id, opened_utc, reason FROM handoffs WHERE state='open'").fetchall():
        opened = parse_utc(h[1])
        if opened and now - opened > timedelta(minutes=30) and not st.get_setting(f"sla_alerted:{h[0]}:{h[1]}"):
            last_mgr = st.c.execute("SELECT 1 FROM messages WHERE chat_id=? AND role='manager' AND ts_utc>=?", (h[0], h[1])).fetchone()
            if not last_mgr:
                st.set_setting(f"sla_alerted:{h[0]}:{h[1]}", "1")
                await outbox.alert(svc, f"⏰ Клієнт id {h[0]} чекає відповіді менеджера вже 30 хв ({h[2]}). Відповідайте реплаєм на картку.")
    from obs.stats import metrics
    m = metrics(st, 1, None, svc.offer.default_set["code"])
    today = now_kyiv().strftime("%Y-%m-%d")
    if m["entered"] >= 20 and m["approve"] < 60 and st.get_setting("approve_alerted") != today:
        st.set_setting("approve_alerted", today)
        await outbox.alert(svc, f"📉 Approve за сьогодні {m['approve']:.0f}% при {m['entered']} зайшлих — нижче 60%. Перевір тексти кроків і чи живий ШІ.")


async def job_sweep(svc: Services) -> None:
    """Страховка: confirmed-замовлення без запису в outbox (впали між confirm і enqueue) → у чергу."""
    for o in svc.store.orders_in((S.CONFIRMED, S.QUEUED_CRM)):
        r = svc.store.c.execute("SELECT 1 FROM outbox WHERE kind='lpcrm_create' AND ref_id=?", (str(o["id"]),)).fetchone()
        if not r:
            svc.store.enqueue("lpcrm_create", str(o["id"]), {"order_id": o["id"]})
            log.warning("sweep: order %s re-enqueued to CRM", o["id"])


async def job_digest(svc: Services) -> None:
    """09:00 Київ: текст + PNG-дашборд адмінам (і в групу, якщо є)."""
    from aiogram.types import FSInputFile
    from core import experiments as X
    from obs.dashboard import render_png
    from obs.stats import stats_text
    today = now_kyiv().strftime("%Y-%m-%d")
    if now_kyiv().hour < 9 or svc.store.get_setting("digest_last_date") == today:
        return
    svc.store.set_setting("digest_last_date", today)
    variants = X.variants_of(svc.offer)
    labels = {v: X.label(svc.offer, v) for v in variants}
    text = f"☀️ {svc.offer.product.get('slug', 'cod-agent')} · {now_kyiv().strftime('%d.%m')}\n" + stats_text(
        svc.store, 1, variants, labels, svc.offer.default_set["code"]) + "\n\n7 днів:\n" + stats_text(
        svc.store, 7, variants, labels, svc.offer.default_set["code"])
    png = render_png(svc.store, svc.cfg.base_dir / "var" / "dashboard.jpg", 7, variants, labels,
                     f"{svc.offer.product.get('slug', 'cod-agent')} · дашборд", svc.offer.default_set["code"])
    targets = list(svc.cfg.admin_ids) + ([svc.cfg.managers_chat_id] if svc.cfg.managers_chat_id else [])
    for t in targets:
        try:
            await svc.bot.send_photo(t, FSInputFile(png), caption=text[:1000])
            if len(text) > 1000:
                await svc.bot.send_message(t, text[1000:4000])
        except Exception as e:  # noqa: BLE001
            log.warning("digest to %s failed: %s", t, e)


async def job_dashboard_html(svc: Services) -> None:
    from core import experiments as X
    from web.pages import render_broadcast, render_dashboard, render_dialogs, render_flow, render_pwa
    variants = X.variants_of(svc.offer)
    labels = {v: X.label(svc.offer, v) for v in variants}
    await _refresh_netcost(svc)
    slug = svc.offer.product.get("slug", "cod-agent")
    render_dashboard(svc.store, svc.cfg.base_dir / "var" / "dashboard.html", variants, labels,
                     f"{slug} · пульт", svc.offer.default_set["code"])
    render_dialogs(svc.store, svc.cfg.base_dir / "var" / "dialogs.html", slug)
    render_broadcast(svc.cfg.base_dir / "var" / "broadcast.html", slug)
    render_flow(svc.cfg.base_dir / "var" / "flow.html", slug)
    render_pwa(svc.cfg.base_dir / "var", slug)
    if now_kyiv().hour == 4:                       # раз на добу — зріз стану в git
        from web import state_sync
        await state_sync.snapshot(svc, "Система", "щоденний зріз")


async def _refresh_netcost(svc: Services) -> None:
    """Собівартість наборів із CRM (price_enter) → settings.set_netcost = {set_code: грн}."""
    import json
    try:
        nc = await svc.lpcrm.products_netcost()
        costs = {}
        for s in svc.offer.sets:
            ids = [(it["product_id"], int(it.get("qty", 1))) for it in s["items"]]
            if all(pid in nc for pid, _ in ids):
                costs[s["code"]] = round(sum(nc[pid] * q for pid, q in ids), 2)
        if costs:
            svc.store.set_setting("set_netcost", json.dumps(costs))
    except Exception as e:  # noqa: BLE001
        log.warning("netcost refresh failed: %s", e)


async def job_push(svc: Services) -> None:
    """Пуш власнику в Telegram про кожне нове підтверджене замовлення. Вимикається з пульта (settings.push_orders)."""
    if not svc.cfg.admin_ids:
        return
    rows = svc.store.c.execute(
        "SELECT id, set_code, price_uah, np_city_name, np_wh_name, name, variant FROM orders "
        "WHERE confirmed_utc IS NOT NULL AND stage!='cancelled' ORDER BY id DESC LIMIT 30").fetchall()
    if not rows:
        return
    top = max(int(r["id"]) for r in rows)
    raw = svc.store.get_setting("push_last_order", "")
    if not raw:                       # перший запуск — не спамимо історією
        svc.store.set_setting("push_last_order", str(top))
        return
    if svc.store.get_setting("push_orders", "1") != "1":
        svc.store.set_setting("push_last_order", str(top))
        return
    last = int(raw or 0)
    fresh = sorted([r for r in rows if int(r["id"]) > last], key=lambda r: r["id"])
    if not fresh:
        return
    from obs.stats import grn, metrics
    m = metrics(svc.store, 1, None, svc.offer.default_set["code"])
    for r in fresh:
        s = svc.offer.set(r["set_code"]) if svc.offer.has_set(r["set_code"]) else None
        city = (r["np_city_name"] or "").replace("м. ", "")
        txt = (f"💰 <b>Замовлення №{r['id']}</b>\n"
               f"{(s['label'] if s else '—')} · <b>{grn(r['price_uah'] or 0)}</b>\n"
               f"📍 {city}\n"
               f"👤 {r['name'] or '—'} · школа {r['variant'] or '?'}\n\n"
               f"Сьогодні: {m['confirmed']} підтв. · середній чек {grn(m['avg_check'])}")
        for uid in svc.cfg.admin_ids:
            try:
                await svc.bot.send_message(uid, txt)
            except Exception as ex:  # noqa: BLE001
                log.warning("push to %s failed: %s", uid, ex)
    svc.store.set_setting("push_last_order", str(max(int(r["id"]) for r in fresh)))


# ---------- loop ----------
async def _loop(name: str, fn, svc: Services, every: int, first_delay: int = 0) -> None:
    await asyncio.sleep(first_delay)
    while True:
        try:
            await fn(svc)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s crashed: %s", name, e)
        await asyncio.sleep(every)


async def run(svc: Services) -> None:
    await asyncio.gather(
        _loop("outbox", outbox.process_once, svc, 10, 2),
        _loop("poll_ttn", job_poll_ttn, svc, 600, 20),
        _loop("poll_np", job_poll_np, svc, 1800, 40),
        _loop("reminders", job_reminders, svc, 3600, 60),
        _loop("nudges", job_nudges, svc, 300, 30),
        _loop("digest", job_digest, svc, 600, 90),
        _loop("dashboard_html", job_dashboard_html, svc, 3600, 120),
        _loop("sweep", job_sweep, svc, 900, 180),
        _loop("sla", job_sla, svc, 600, 240),
        _loop("push", job_push, svc, 60, 25),
    )
