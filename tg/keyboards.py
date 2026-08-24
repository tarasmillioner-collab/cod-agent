"""Клавиатуры. Текст кнопки ≤ 24 символа; кнопка подтверждения содержит сумму."""
from __future__ import annotations

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardMarkup, ReplyKeyboardRemove)

from core.offer import Offer


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поділитися номером", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def geo_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Надіслати моє місто", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def name_prefill_kb(full: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Так, це я: {full}"[:60], callback_data="name:yes")],
                                                 [InlineKeyboardButton(text="Інше ім'я", callback_data="name:no")]])


def name_first_kb(fn: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"Так, я {fn}"[:60], callback_data=f"name:first:{fn}"[:64])],
                                                 [InlineKeyboardButton(text="Інше ім'я", callback_data="name:no")]])


def bundle_entry_kb(o: Offer, bundle: dict, single: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Так, набір — {o.fmt_price(int(bundle['price']))}", callback_data=f"set:{bundle['code']}")],
        [InlineKeyboardButton(text=f"Лише сироватка — {o.fmt_price(int(single['price']))}", callback_data=f"set:{single['code']}")],
    ])


def nearest_kb(whs: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for w in whs[:3]:
        d = w.get("dist_m") or 0
        dist = f"{d} м" if d < 1000 else f"{d / 1000:.1f} км"
        txt = w["desc"].replace("Відділення", "Відд.").split(":")[0][:40] + f" · {dist}"
        rows.append([InlineKeyboardButton(text=txt[:60], callback_data=f"wh:{w['ref']}")])
    rows.append([InlineKeyboardButton(text="Моє звичне відділення — інше", callback_data="wh:other")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def repeat_kb(set_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Так, як минулого разу", callback_data=f"repeat:yes:{set_code}")],
        [InlineKeyboardButton(text="Змінити дані", callback_data=f"repeat:no:{set_code}")],
    ])


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def sets_kb(o: Offer) -> InlineKeyboardMarkup:
    rows = []
    for s in o.sets:
        label = f"{'★ ' if s.get('badge') else ''}{s['label']} — {o.fmt_price(int(s['price']))}"
        rows.append([InlineKeyboardButton(text=label[:60], callback_data=f"set:{s['code']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def set_echo_kb(o: Offer, s: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📦 Так, оформити — {o.fmt_price(int(s['price']))}", callback_data=f"set:{s['code']}")],
        [InlineKeyboardButton(text="Змінити набір", callback_data="set:choose")],
    ])


def yes_no_kb(yes: str, no: str, yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=yes, callback_data=yes_cb),
        InlineKeyboardButton(text=no, callback_data=no_cb),
    ]])


def cities_kb(cities: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=(c["present"] or c["name"])[:60], callback_data=f"city:{c['ref']}")] for c in cities[:5]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def warehouses_kb(whs: list[dict], postomat_allowed: bool, show_postomat: bool = True) -> InlineKeyboardMarkup:
    rows = []
    for w in whs[:6]:
        txt = w["desc"]
        txt = txt.replace("Відділення", "Відд.").replace("Поштомат", "Поштомат")
        rows.append([InlineKeyboardButton(text=txt[:60], callback_data=f"wh:{w['ref']}")])
    tail = [InlineKeyboardButton(text="🔎 Інше відділення", callback_data="wh:other")]
    if postomat_allowed and show_postomat:
        tail.append(InlineKeyboardButton(text="Поштомат", callback_data="wh:postomat"))
    rows.append(tail)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def postomat_confirm_kb() -> InlineKeyboardMarkup:
    return yes_no_kb("Обрати відділення", "Так, поштомат", "wh:other", "wh:postomat_ok")


def upsell_kb(o: Offer) -> InlineKeyboardMarkup:
    up = o.upsell
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Так, курс 60 днів — {o.fmt_price(int(o.set(up['to'])['price']))}", callback_data=f"up:yes:{up['to']}")],
        [InlineKeyboardButton(text=up["decline_button"][:60], callback_data=f"up:no:{up['from']}")],
    ])


def summary_kb(o: Offer, order: dict) -> InlineKeyboardMarkup:
    s = o.set(order["set_code"])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Підтверджую — {o.fmt_price(int(s['price']))}", callback_data=f"confirm:{order['id']}")],
        [InlineKeyboardButton(text="Змінити", callback_data="edit:menu")],
    ])


def edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Набір", callback_data="edit:set"), InlineKeyboardButton(text="Ім'я", callback_data="edit:name")],
        [InlineKeyboardButton(text="Місто / відділення", callback_data="edit:city")],
        [InlineKeyboardButton(text="Скасувати замовлення", callback_data="edit:cancel")],
    ])


def arrived_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Заберу сьогодні", callback_data=f"pick:today:{order_id}"),
         InlineKeyboardButton(text="Завтра", callback_data=f"pick:tomorrow:{order_id}")],
        [InlineKeyboardButton(text="На вихідних", callback_data=f"pick:weekend:{order_id}"),
         InlineKeyboardButton(text="Не зможу", callback_data=f"pick:no:{order_id}")],
    ])


def reminder_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Заберу завтра", callback_data=f"pick:tomorrow:{order_id}"),
         InlineKeyboardButton(text="Продовжити зберігання", callback_data=f"pick:extend:{order_id}")],
        [InlineKeyboardButton(text="Передумала", callback_data=f"pick:no:{order_id}")],
    ])


def nudge_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Продовжити", callback_data="nudge:continue"),
         InlineKeyboardButton(text="Не цікаво", callback_data="nudge:stop")],
    ])


def manager_card_kb(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Повернути боту", callback_data=f"mgr:close:{chat_id}")],
    ])
