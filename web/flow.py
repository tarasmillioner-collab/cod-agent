"""Сценарій бота: усі кроки по порядку з реальними текстами + правки з дашборда.

build(offer, variant) → список кроків: що бот пише, коли саме, які рядки можна редагувати.
Правки живуть у settings.copy_overrides (ключ "A.greet" / "obj.price") і читаються
через core.experiments.tone() та core.objections.load() — offer.yaml не переписуємо.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from core import experiments as X
from core.offer import Offer
from tg import texts as T

# у шаблонах допустимі лише ці підстановки — інші зламають .format()
ALLOWED_PH = {"addr", "left", "steps"}
_PH_RX = re.compile(r"\{([a-zA-Z_]*)\}")
_TAG_RX = re.compile(r"</?([a-zA-Z0-9]+)[^>]*>")
ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a", "br"}


def validate(key: str, text: str) -> str | None:
    """None = ок, інакше — текст помилки для дашборда."""
    if not text.strip():
        return "порожній текст"
    if len(text) > 1500:
        return "занадто довго (максимум 1500 символів)"
    for ph in _PH_RX.findall(text):
        if ph not in ALLOWED_PH:
            return f"невідома підстановка {{{ph}}} — можна лише {{addr}}"
    for tag in _TAG_RX.findall(text):
        if tag.lower() not in ALLOWED_TAGS:
            return f"тег <{tag}> не можна — лише <b>, <i>, <u>, <code>"
    if text.count("<") != text.count(">"):
        return "незакриті кутові дужки"
    return None


def _sample(offer: Offer, variant: str, set_code: str | None = None) -> dict:
    s = offer.set(set_code or offer.default_set["code"])
    return {"id": 1041, "set_code": s["code"], "price_uah": int(s["price"]),
            "name": "Петренко Оксана Іванівна", "phone": "380671234567",
            "np_city_name": "м. Київ", "np_wh_name": "Відділення №12 (до 30 кг на одне місце): вул. Шевченка, 5",
            "delivery_type": "warehouse", "variant": variant, "ttn": "20450912345678"}


def _f(variant: str, key: str, label: str, offer: Offer) -> dict:
    return {"key": f"{variant}.{key}", "label": label, "value": X.tone(offer, variant, key, "")}


def build(offer: Offer, variant: str) -> list[dict]:
    o, v = offer, variant
    ord1 = _sample(o, v)
    s1, s2 = o.default_set, o.set(o.upsell.get("to") or o.default_set["code"])
    ord2 = dict(ord1, set_code=s2["code"], price_uah=int(s2["price"]))
    until = date.today() + timedelta(days=5)
    F = lambda k, lab: _f(v, k, lab, o)  # noqa: E731

    def step(n, ico, title, when, text, fields=(), note=""):
        return {"n": n, "ico": ico, "title": title, "when": when, "text": text,
                "fields": list(fields), "note": note}

    steps = [
        step(1, "👋", "Привітання + товар", "щойно людина натиснула «Почати»",
             T.greet_with_set(o, s1, v),
             [F("greet", "Перша фраза"), F("chosen", "Підпис до товару")],
             "Разом із фото товару з лендингу. Одразу кнопка «Поділитись номером»."),
        step(2, "📱", "Крок 1 — телефон", "якщо номер не прийшов одразу",
             T.ask_phone(o, v), [F("phone", "Прохання дати номер")],
             "Номер підставляється кнопкою Telegram — клієнт не друкує."),
        step(3, "✍️", "Крок 2 — ім'я", "після номера",
             T.ask_name_prefill("Оксана Петренко"), [],
             "Якщо в Telegram є ім'я і прізвище — пропонуємо в один тап."),
        step(4, "📍", "Крок 3 — місто", "після імені",
             T.ask_city_geo("Петренко Оксана Іванівна"), [],
             "Кнопка «Надіслати моє місто» → показуємо 3 найближчі відділення."),
        step(5, "🏤", "Відділення", "після міста",
             T.ask_warehouse("м. Київ"), [],
             "Список кнопками; поштомат — з попередженням, що оглянути до оплати не вийде."),
        step(6, "🧾", "Підсумок перед підтвердженням", "коли всі дані зібрані",
             T.summary(o, ord1), [F("summary_close", "Заклик підтвердити")],
             "Кнопка з сумою. Тут людина ще нічого не платить."),
        step(7, "✅", "Квитанція + тепле слово", "одразу після «Підтверджую»",
             T.receipt(o, ord1), [F("receipt", "Шапка квитанції"), F("after_confirm", "Тепле повідомлення")],
             "Одне повідомлення: підтвердження, склад замовлення, що буде далі."),
        step(8, "💛", "Апсейл на курс 60 днів", "через 3 секунди після квитанції",
             T.upsell(o, "Петренко Оксана Іванівна", v),
             [F("upsell_lead", "Підводка"), F("upsell_why", "Аргумент"), F("upsell_cta", "Заклик")],
             "З персональним банером (ім'я на картинці). Тільки ПІСЛЯ підтвердження."),
        step(9, "🛒", "Якщо погодилась на курс", "після «Так, курс 60 днів»",
             T.upsell_accepted(o, ord2), [], "Замовлення оновлюється, у CRM їде вже курс."),
        step(10, "⏳", "Тиша 15 хвилин", "клієнт мовчить на кроці збору даних",
             T.nudge15(o, v, "Петренко Оксана Іванівна", 2), [F("nudge15", "Нагадування")],
             "Далі — 60 хв, 2 год; через 3 год лід іде в CRM на прозвон."),
        step(11, "📦", "Посилка поїхала", "щойно в CRM з'явився ТТН",
             T.shipped(o, ord1), [F("shipped", "Шапка")], "Номер накладної приходить сюди ж."),
        step(12, "🏤", "Посилка у відділенні", "коли Нова пошта каже «прибула»",
             T.arrived(o, ord1, until), [F("arrived_head", "Шапка")],
             "Інструкція: оглянути до оплати, і лише тоді платити."),
        step(13, "🔔", "Нагадування на 3-й день", "посилка лежить 3 дні",
             T.reminder_d3(o, ord1, until), [], "П'ятий день — «сьогодні останній день зберігання»."),
        step(14, "🌅", "Догляд, день 1", "через добу після викупу",
             T.care_day1(o, "Петренко Оксана Іванівна", v), [F("care_day1", "Шапка")],
             "Щоб почала користуватись — і був результат."),
        step(15, "⭐️", "Відгук", "через 7 днів після викупу",
             T.review_request(ord1), [], "Питаємо враження — це і соцдоказ, і привід повернутись."),
        step(16, "🔄", "Новий флакон", "через 25 днів після викупу",
             T.care_day25(o, s1, "Петренко Оксана Іванівна"), [],
             "Повторний продаж у два тапи — головний LTV-крок."),
    ]
    obj = [{"key": "obj." + x["key"], "label": x["key"],
            "match": x.get("match", ""), "value": X.overrides().get("obj." + x["key"]) or x.get("answer", "")}
           for x in (o.raw.get("objections") or [])]
    return [steps, obj]
