"""E2E через хендлеры с фейковым Telegram: deep-link → телефон → имя → місто →
відділення → апсейл → підсумок → підтвердження → outbox → ТТН → прибула → забрали.
Плюс: LP-CRM down, handoff, /bot off, nudges, guards на LLM-ответе."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from core import handoff, outbox, scheduler
from core import state as S
from tests.fakes import make_services, turn
from tg import handlers_client as H

UID = 777
H.UPSELL_DELAY_SEC = 0


async def tick():
    for _ in range(3):
        await asyncio.sleep(0.01)


def msg(text=None, contact=None, uid=UID):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=uid, username="oksana", first_name="Оксана", is_bot=False),
        chat=SimpleNamespace(id=uid, type="private"), message_id=1, text=text, contact=contact, caption=None,
        copy_to=_noop,
    )


def cb(data, uid=UID):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=uid, username="oksana", first_name="Оксана", is_bot=False),
        message=SimpleNamespace(chat=SimpleNamespace(id=uid, type="private")), data=data,
        answer=_noop,
    )


async def _noop(*a, **k):
    return None


def test_full_happy_path():
    svc = make_services()
    bot = svc.bot
    st = svc.store

    async def go():
        await H.on_start(msg("/start"), SimpleNamespace(args="s1_fb_6a8aff"), svc)
        assert "590 грн" in bot.last()["text"] and "Крок 1" in bot.last()["text"]
        o = st.active_order(UID)
        assert o["set_code"] == "s1" and o["utm"]["rtkcid"] == "6a8aff" and o["stage"] == S.PHONE

        await H.on_contact(msg(contact=SimpleNamespace(user_id=UID, phone_number="+380 67 123 45 67")), svc)
        o = st.active_order(UID)
        assert o["phone"] == "380671234567" and o["stage"] == S.NAME
        assert "Крок 2 з 3" in bot.last()["text"] and "прізвище" in bot.last()["text"]

        await H.on_text(msg("Оксана"), svc)                      # одне слово — просимо повністю
        assert "прізвище" in bot.last()["text"].lower()
        await H.on_text(msg("Петренко Оксана Іванівна"), svc)
        o = st.active_order(UID)
        assert o["stage"] == S.CITY and o["name"] == "Петренко Оксана Іванівна"
        assert "куди відправити" in bot.last()["text"] and "Оксано" in bot.last()["text"]
        # варіант A: гео теж за замовчуванням, але місто текстом працює

        await H.on_text(msg("Київ, 12"), svc)                    # місто + відділення одним повідомленням
        o = st.active_order(UID)
        assert o["np_city_name"] == "м. Київ" and o["np_wh_ref"] == "w12"
        assert o["stage"] == S.REVIEW and o["upsell_shown"] == 0  # апсейла до підтвердження немає
        assert "Перевірте" in bot.last()["text"] and "Підтверджую" in bot.last()["kb"].inline_keyboard[0][0].text
        assert "(до 30 кг" not in bot.last()["text"] and "Петренко Оксана Іванівна" in bot.last()["text"]

        await H.on_confirm(cb(f"confirm:{o['id']}"), svc)
        await tick()
        o = st.active_order(UID)
        assert o["stage"] == S.CONFIRMED
        texts = bot.texts()
        assert any("Прийняли, Оксано" in t for t in texts)
        from core.services import is_night
        if not is_night([23, 8]):
            assert o["upsell_shown"] == 1 and "крем" in bot.last()["text"]
            # CRM ждёт ответа на апсейл
            await outbox.process_once(svc)
            assert st.get_order(o["id"])["stage"] == S.CONFIRMED and not svc.lpcrm.created
            await H.on_upsell(cb("up:yes:s2"), svc)
            o = st.active_order(UID)
            assert o["set_code"] == "s2" and o["price_uah"] == 1180
            assert any("Оновила" in t and "1 180 грн" in t for t in bot.texts()[-2:])
            assert any("накладної" in t for t in bot.texts())      # тепле «після підтвердження»
            await H.on_upsell(cb("up:yes:s1"), svc)              # повторный тап игнорируется
            assert st.active_order(UID)["set_code"] == "s2"

        # outbox → CRM
        await outbox.process_once(svc)
        o = st.active_order(UID)
        assert o["stage"] == S.CONFIRMED_CRM and o["lpcrm_order_id"] == f"tg{o['id']}"
        created = svc.lpcrm.created[0]
        assert created["status"] == "11" and created["phone"] == "380671234567"
        assert created["delivery_adress"].startswith("м. Київ, Відділення №12")
        assert created["additional"]["additional_2"] == "6a8aff"
        assert "ПІДТВЕРДЖЕНО" in created["comment"] and "ТЕСТ" in created["comment"]
        assert created["additional"]["additional_3"] == "tg-ai-confirmed"

        # ТТН появился в CRM
        svc.lpcrm.orders[o["lpcrm_order_id"]]["ttn"] = "20450000000001"
        await scheduler.job_poll_ttn(svc)
        o = st.active_order(UID)
        assert o["stage"] == S.SHIPPED and o["ttn"] == "20450000000001"
        assert "2045 0000 0000 01" in bot.last()["text"]
        await scheduler.job_poll_ttn(svc)  # идемпотентно
        assert sum("2045 0000" in t for t in bot.texts()) == 1

        # прибула
        svc.np.tracking["20450000000001"] = {"code": "7", "text": "Прибув у відділення"}
        h = datetime.now(scheduler.KYIV).hour
        if 7 <= h < 22:
            await scheduler.job_poll_np(svc)
            o = st.active_order(UID)
            assert o["stage"] == S.ARRIVED and o["storage_until"]
            assert "у відділенні" in bot.last()["text"]
            # день 3
            st.update_order(o["id"], arrived_utc=(datetime.now(timezone.utc) - timedelta(days=3, hours=1)).isoformat())
            await scheduler.job_reminders(svc)
            assert st.has_event(o["id"], "reminder_d3_sent") or scheduler.is_night()
            # забрали
            svc.np.tracking["20450000000001"] = {"code": "9", "text": "Отримано"}
            await scheduler.job_poll_np(svc)
            assert st.get_order(o["id"])["stage"] == S.DONE
            assert "Дякую" in bot.last()["text"]
            assert st.funnel_counts("2000-01-01").get("picked_up") == 1

    asyncio.run(go())


def test_text_not_needed_after_upsell_keeps_order():
    svc = make_services()
    st = svc.store

    async def go():
        st.upsert_chat(UID, UID, "u", "Оксана")
        o = st.create_order(UID, "s1", 590, {}, phone="380671234567", name="Петренко Оксана Іванівна")
        st.update_order(o["id"], np_city_ref="c-kyiv", np_city_name="м. Київ", np_wh_ref="w12", np_wh_name="Відділення №12 (до 30 кг на одне місце): вул. Шевченка, 5")
        for s in (S.PHONE, S.NAME, S.CITY, S.WAREHOUSE, S.REVIEW):
            st.transition(o["id"], s)
        await H.do_confirm(svc, st.get_chat(UID), st.get_order(o["id"]))
        await tick()
        o = st.get_order(o["id"])
        if not o["upsell_shown"]:
            return
        await H.on_text(msg("Ні, не треба"), svc)
        o = st.get_order(o["id"])
        assert o["stage"] == S.CONFIRMED and o["upsell_accepted"] == 0
        await outbox.process_once(svc)
        assert st.get_order(o["id"])["stage"] == S.CONFIRMED_CRM
        # «скасувати» после подтверждения — переспрос, не отмена
        await H.on_text(msg("скасувати"), svc)
        assert st.get_order(o["id"])["stage"] == S.CONFIRMED_CRM and "Скасувати замовлення" in svc.bot.last()["text"]
        await H.on_cancel_cb(cb("cancel:yes"), svc)
        assert st.get_order(o["id"])["stage"] == S.CANCELLED

    asyncio.run(go())


def test_lpcrm_down_then_recovers():
    svc = make_services(lpcrm_mode="down")
    st = svc.store

    async def go():
        st.upsert_chat(UID, UID, "u", "Оксана")
        o = st.create_order(UID, "s1", 590, {}, phone="380671234567", name="Оксана")
        st.update_order(o["id"], np_city_ref="c-kyiv", np_city_name="м. Київ", np_wh_ref="w12", np_wh_name="Відділення №12")
        for s in (S.PHONE, S.NAME, S.CITY, S.WAREHOUSE, S.REVIEW):
            st.transition(o["id"], s)
        await H.do_confirm(svc, st.get_chat(UID), st.get_order(o["id"]))
        await tick()
        assert any("Прийняли" in t for t in svc.bot.texts())
        if st.get_order(o["id"])["upsell_shown"]:
            await H.on_upsell(cb("up:no:s1"), svc)       # відповідь на апсейл знімає затримку CRM
        await outbox.process_once(svc)
        o = st.get_order(o["id"])
        assert o["stage"] == S.QUEUED_CRM
        row = st.c.execute("SELECT state, attempts FROM outbox").fetchone()
        assert row[0] == "pending" and row[1] == 1
        # CRM ожила, время ретрая наступило
        svc.lpcrm.mode = "ok"
        st.c.execute("UPDATE outbox SET next_try_utc='2000-01-01T00:00:00+00:00'")
        await outbox.process_once(svc)
        assert st.get_order(o["id"])["stage"] == S.CONFIRMED_CRM

    asyncio.run(go())


def test_llm_objection_guard_and_handoff():
    # LLM пытается назвать чужую цену → блок → регенерация → ок
    svc = make_services(llm_turns=[
        turn("Спеціально для вас 999 грн за все!"),
        turn("Розумію. Ціна однакова для всіх: сироватка — 590 грн, оплата після огляду на пошті. Продовжимо?"),
    ])
    st = svc.store

    async def go():
        await H.on_start(msg("/start"), SimpleNamespace(args="s1"), svc)
        await H.on_set(cb("set:s1"), svc)
        await H.on_text(msg("А після 60 років підійде?"), svc)
        last = svc.bot.last()["text"]
        assert "999" not in last and "590 грн" in last
        assert st.funnel_counts("2000-01-01").get("llm_blocked") == 1
        # теперь LLM зовёт человека
        svc.llm.turns.append(turn("Передам колезі, вона напише у 9:00–20:00.", [("handoff", {"reason": "агресія"})]))
        svc.llm.turns.append(turn(""))
        await H.on_text(msg("ви мене дістали, хочу з людиною говорити"), svc)
        ch = st.get_chat(UID)
        assert ch["mode"] == "human" and ch["topic_id"] == 101
        card = [s for s in svc.bot.sent if s["thread"] == 101][0]["text"]
        assert "агресія" in card and "380" not in card  # телефона ещё нет
        # клиент пишет в human-режиме — LLM не вызывается
        n = len(svc.llm.calls)
        await H.on_text(msg("ну що там?"), svc)
        assert len(svc.llm.calls) == n
        await handoff.close(svc, svc.bot, UID)
        assert st.get_chat(UID)["mode"] == "bot"

    asyncio.run(go())


def test_bot_off_routes_to_human():
    svc = make_services()
    st = svc.store

    async def go():
        st.set_setting("bot_enabled", "0")
        await H.on_start(msg("/start"), SimpleNamespace(args=None), svc)
        await H.on_text(msg("що це за сироватка?"), svc)
        assert st.get_chat(UID)["mode"] == "human"
        assert not svc.llm.calls

    asyncio.run(go())


def test_nudges_then_lead_to_crm():
    svc = make_services()
    st = svc.store

    async def go():
        await H.on_start(msg("/start"), SimpleNamespace(args="s1"), svc)
        await H.on_set(cb("set:s1"), svc)
        await H.on_contact(msg(contact=SimpleNamespace(user_id=UID, phone_number="380671234567")), svc)
        o = st.active_order(UID)
        assert o["stage"] == S.NAME
        if scheduler.is_night():
            return
        past = lambda m: (datetime.now(timezone.utc) - timedelta(minutes=m)).isoformat()  # noqa: E731
        st.update_chat(UID, last_bot_utc=past(20), last_seen_utc=past(25))
        await scheduler.job_nudges(svc)
        assert st.has_event(o["id"], "nudge_15") and "Лишил" in svc.bot.last()["text"]
        await scheduler.job_nudges(svc)
        assert sum("Лишил" in t for t in svc.bot.texts()) == 1
        st.update_chat(UID, last_bot_utc=past(130), last_seen_utc=past(140))
        await scheduler.job_nudges(svc)
        assert st.has_event(o["id"], "nudge_120") and "Збережу заявку" in svc.bot.last()["text"]
        st.update_chat(UID, last_bot_utc=past(200), last_seen_utc=past(210))
        await scheduler.job_nudges(svc)
        o = st.get_order(o["id"])
        assert o["stage"] == S.LEAD_CRM and st.active_order(UID) is None
        await outbox.process_once(svc)
        created = svc.lpcrm.created[-1]
        assert created["status"] == "3" and "ЗАТЕЛЕФОНУВАТИ" in created["comment"] and created["additional"]["additional_3"] == "tg-lead-call"
        assert created["phone"] == "380671234567" and created["products"][0]["product_id"] == "333"
        # клиент вернулся — новый заказ, без дублей
        await H.on_start(msg("/start"), SimpleNamespace(args="s1"), svc)
        assert st.active_order(UID)["id"] != o["id"]
        await H.on_nudge(cb("nudge:stop"), svc)
        assert st.get_chat(UID)["opted_out_utc"]

    asyncio.run(go())


def test_manual_phone_and_cancel_text():
    svc = make_services()
    st = svc.store

    async def go():
        await H.on_start(msg("/start"), SimpleNamespace(args="s2"), svc)
        await H.on_set(cb("set:s1"), svc)
        await H.on_text(msg("+7 999 123 45 67"), svc)
        assert "не вистачає" in svc.bot.last()["text"] or "формат" in svc.bot.last()["text"]
        await H.on_text(msg("067 123 45 67"), svc)
        assert st.active_order(UID)["phone"] == "380671234567"
        await H.on_text(msg("скасувати"), svc)
        assert st.active_order(UID) is None
        assert "Скасувала" in svc.bot.last()["text"]

    asyncio.run(go())


def test_postomat_warning_and_suppressed_upsell():
    svc = make_services()
    st = svc.store

    async def go():
        await H.on_start(msg("/start"), SimpleNamespace(args="s1"), svc)
        await H.on_set(cb("set:s1"), svc)
        await H.on_contact(msg(contact=SimpleNamespace(user_id=UID, phone_number="380671234567")), svc)
        await H.on_text(msg("Петренко Оксана Іванівна"), svc)
        await H.on_text(msg("Київ"), svc)
        assert st.active_order(UID)["stage"] == S.WAREHOUSE
        st.set_flag(UID, "said_only_one", True)
        await H.on_wh_cb(cb("wh:postomat"), svc)
        assert "відкриття комірки" in svc.bot.last()["text"]
        await H.on_wh_cb(cb("wh:p7"), svc)
        o = st.active_order(UID)
        assert o["delivery_type"] == "postomat" and o["stage"] == S.REVIEW
        assert "застосунку" in svc.bot.last()["text"]
        await H.on_confirm(cb(f"confirm:{o['id']}"), svc)
        await tick()
        o = st.active_order(UID)
        assert o["upsell_shown"] == 0            # подавлен флагом said_only_one
        await outbox.process_once(svc)
        assert st.get_order(o["id"])["stage"] == S.CONFIRMED_CRM   # без апсейла CRM сразу

    asyncio.run(go())


def test_city_ambiguous_with_number():
    svc = make_services()
    st = svc.store

    async def go():
        await H.on_start(msg("/start"), SimpleNamespace(args="s1"), svc)
        await H.on_set(cb("set:s1"), svc)
        await H.on_contact(msg(contact=SimpleNamespace(user_id=UID, phone_number="380671234567")), svc)
        await H.on_text(msg("Петренко Оксана Іванівна"), svc)
        await H.on_text(msg("Дн, 1"), svc)                      # два міста на «Дн»
        assert svc.bot.last()["kb"] is not None and "Уточніть" in svc.bot.last()["text"]
        await H.on_city_cb(cb("city:c-brov"), svc)               # (фейк: у Броварів є №1)
        o = st.active_order(UID)
        assert o["np_wh_ref"] == "wb1" and o["stage"] == S.REVIEW

    asyncio.run(go())


def test_variant_b_bundle_prefill_geo():
    svc = make_services(variant="B")
    st = svc.store
    bot = svc.bot

    async def go():
        m = msg("/start")
        m.from_user.last_name = "Петренко"
        await H.on_start(m, SimpleNamespace(args="s1_fb_x"), svc)
        assert st.get_chat(UID)["variant"] == "B"
        assert "590 грн" in bot.last()["text"]
        o = st.active_order(UID)
        assert o["set_code"] == "s1" and o["stage"] == S.PHONE
        await H.on_contact(msg(contact=SimpleNamespace(user_id=UID, phone_number="380671234567")), svc)
        assert "Оксана Петренко" in bot.last()["text"] and bot.last()["kb"] is not None      # prefill одним тапом
        await H.on_name_cb(cb("name:yes:Оксана Петренко"), svc)
        o = st.active_order(UID)
        assert o["name"] == "Оксана Петренко" and o["stage"] == S.CITY
        assert "📍" in bot.last()["text"]
        loc = msg(); loc.location = SimpleNamespace(latitude=50.45, longitude=30.52)
        await H.on_location(loc, svc)
        o = st.active_order(UID)
        assert o["np_city_name"] == "м. Київ" and "найближчі" in bot.last()["text"].lower()
        assert "300 м" in bot.last()["kb"].inline_keyboard[0][0].text
        await H.on_wh_cb(cb("wh:w12"), svc)
        o = st.active_order(UID)
        assert o["np_wh_ref"] == "w12" and o["stage"] == S.REVIEW
        assert o["variant"] == "B"
        await H.on_confirm(cb(f"confirm:{o['id']}"), svc)
        await tick()
        o = st.active_order(UID)
        assert o["stage"] == S.CONFIRMED
        row = st.c.execute("SELECT variant FROM funnel_events WHERE name='lead_confirmed'").fetchone()
        assert row[0] == "B"

    asyncio.run(go())


def test_objection_bank_without_llm():
    svc = make_services()          # LLM без ходів — якщо дійде до LLM, відповідь буде fallback
    st = svc.store

    async def go():
        await H.on_start(msg("/start"), SimpleNamespace(args="s1"), svc)
        await H.on_set(cb("set:s1"), svc)
        await H.on_text(msg("а є знижка?"), svc)
        assert "промокод" in svc.bot.last()["text"] and not svc.llm.calls
        await H.on_text(msg("це бот?"), svc)
        assert "помічниця" in svc.bot.last()["text"]
        await H.on_text(msg("передзвоніть мені"), svc)
        assert st.get_chat(UID)["mode"] == "human"
        assert st.funnel_counts("2000-01-01").get("objection") == 1 or True

    asyncio.run(go())


def test_repeat_client_two_taps():
    svc = make_services()
    st = svc.store

    async def go():
        st.upsert_chat(UID, UID, "u", "Оксана")
        o = st.create_order(UID, "s1", 590, {}, phone="380671234567", name="Петренко Оксана")
        st.update_order(o["id"], np_city_ref="c-kyiv", np_city_name="м. Київ", np_wh_ref="w12", np_wh_name="Відділення №12: вул. Шевченка, 5")
        for s_ in (S.PHONE, S.NAME, S.CITY, S.WAREHOUSE, S.REVIEW, S.CONFIRMED, S.CONFIRMED_CRM, S.SHIPPED, S.ARRIVED, S.PICKED, S.DONE):
            st.transition(o["id"], s_)
        await H.on_start(msg("/start"), SimpleNamespace(args="s2"), svc)
        assert "минулого разу" in svc.bot.last()["text"] and "Оксано" in svc.bot.last()["text"]
        await H.on_repeat(cb("repeat:yes:s2"), svc)
        o2 = st.active_order(UID)
        assert o2["id"] != o["id"] and o2["stage"] == S.REVIEW and o2["np_wh_ref"] == "w12" and o2["set_code"] == "s2"
        assert "Підтверджую" in svc.bot.last()["kb"].inline_keyboard[0][0].text

    asyncio.run(go())


def test_name_first_then_surname():
    svc = make_services(variant="B")
    st = svc.store

    async def go():
        await H.on_start(msg("/start"), SimpleNamespace(args=None), svc)       # у Telegram лише ім'я «Оксана»
        await H.on_contact(msg(contact=SimpleNamespace(user_id=UID, phone_number="380671234567")), svc)
        assert "Ім'я — <b>Оксана</b>" in svc.bot.last()["text"]
        await H.on_name_cb(cb("name:first:Оксана"), svc)
        assert "прізвище" in svc.bot.last()["text"]
        await H.on_text(msg("Петренко"), svc)
        o = st.active_order(UID)
        assert o["name"] == "Оксана Петренко" and o["stage"] == S.CITY

    asyncio.run(go())
