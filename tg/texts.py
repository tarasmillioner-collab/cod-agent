"""Детерминированные тексты (не LLM). HTML parse mode: динамические значения экранируются через e().
Правила: коротко, одна мысль, один вопрос; звертання — лише ім'я в кличному; суми — з offer.yaml."""
from __future__ import annotations

from datetime import date
from html import escape as e

from core.names import address, clean_np, plural_steps, steps_left_phrase, vocative
from core import experiments as X
from core.offer import Offer


def _addr(name: str | None) -> str:
    return address(name)


def _hi(name: str | None, fallback: str = "") -> str:
    a = _addr(name)
    return f"{a}, " if a else fallback


def _wh(order: dict) -> str:
    return e(clean_np(order.get("np_wh_name")))


def _city(order: dict) -> str:
    c = (order.get("np_city_name") or "").replace("м. ", "")
    return e(c)


def _ttn_fmt(t: str) -> str:
    t = (t or "").strip()
    return " ".join(t[i:i + 4] for i in range(0, len(t), 4))


UA_WEEKDAYS = ["понеділка", "вівторка", "середи", "четверга", "п'ятниці", "суботи", "неділі"]


def _until(until: date | None) -> str:
    return f" до {UA_WEEKDAYS[until.weekday()]} {until.strftime('%d.%m')}" if until else ""


def cash(o: Offer, s: dict) -> str:
    return e(s["full_cash_text"])


# ---------- вхід ----------
def greet_with_set(o: Offer, s: dict, variant: str | None = None) -> str:
    return (f"{e(X.tone(o, variant, 'greet', 'Вітаю! Я Оля з Olavita.'))}\n\n"
            f"{e(X.tone(o, variant, 'chosen', 'Ви обрали'))}: <b>{e(s['label'])} — {o.fmt_price(int(s['price']))}</b>\n"
            f"Платите на пошті, коли побачите й оглянете.\n\n"
            f"<b>Крок 1 з 3</b> — натисніть кнопку, і номер підставиться сам 👇")


def greet_choose(o: Offer) -> str:
    return ("Вітаю 💛 Це Оля з Olavita.\n"
            "Оберіть набір — платите на пошті після огляду, без дзвінків 👇")


def choose_sets(o: Offer) -> str:
    return "Оберіть набір 👇"


def greet_bundle(o: Offer, bundle: dict, single: dict) -> str:
    gift = (o.raw.get("bundle") or {}).get("gift_text") or ""
    delta = int(bundle["price"]) - int(single["price"])
    return (f"Вітаю! 💛 Я Оля з Olavita.\n\n"
            f"Більшість наших клієнток беруть не одну сироватку, а набір <b>1 + 1 = 3</b>:\n\n"
            f"✨ <b>Сироватка</b> — розгладжує обличчя і шию\n"
            f"👁 <b>Крем для очей</b> — гусячі лапки, набряки, темні кола (сироватка для цієї тонкої зони не розрахована)\n"
            f"🎁 <b>Третій засіб — {e(gift) if gift else 'у подарунок'}</b>\n\n"
            f"Разом — <b>{o.fmt_price(int(bundle['price']))}</b>, подарунок вартістю 299 грн уже в посилці. "
            f"Платите на пошті після огляду. Не підійде — просто не забираєте.\n\n"
            f"Що обираєте? 👇")


def ask_name_prefill(full: str) -> str:
    return (f"Номер є ✅\n\n"
            f"<b>Крок 2 з 3</b> — як записати в накладній?\n"
            f"У Telegram ви — <b>{e(full)}</b>. Так і записати?")


def ask_name_first(fn: str) -> str:
    return (f"Номер є ✅\n\n"
            f"<b>Крок 2 з 3</b> — як записати в накладній?\n"
            f"Ім'я — <b>{e(fn)}</b>, правильно? Далі попрошу лише прізвище.")


def ask_surname(fn: str) -> str:
    return f"{e(fn)} ✅ Тепер напишіть прізвище — одним словом."


def ask_city_geo(name: str | None) -> str:
    a = _addr(name)
    return (f"Дякую{', ' + a if a else ''} ✅ Останнє — куди відправити?\n\n"
            f"Натисніть «📍 Надіслати моє місто» внизу — покажу відділення поруч. Або напишіть місто.")


def nearest_found(city: str) -> str:
    return f"📍 {e(city.replace('м. ', ''))} — найближчі до вас 👇"


# ---------- кроки ----------
def ask_phone(o: Offer | None = None, variant: str | None = None) -> str:
    if o:
        return e(X.tone(o, variant, "phone", "")) + " 👇" if X.tone(o, variant, "phone") else _ask_phone_default()
    return _ask_phone_default()


def _ask_phone_default() -> str:
    return ("<b>Крок 1 з 3</b> — номер телефону.\n"
            "Натисніть кнопку нижче — номер підставиться сам. На нього Нова пошта надішле SMS, коли посилка приїде.\n\n"
            "Передоплат і даних картки не просимо 👇")


def phone_invalid() -> str:
    return "Здається, у номері не вистачає цифри. Формат: 067 123 45 67 — або натисніть кнопку нижче 📱"


def ask_name() -> str:
    return "Номер є ✅ Тепер ім'я та прізвище для посилки, наприклад: <i>Оксана Петренко</i>"


def name_need_surname() -> str:
    return "Напишіть, будь ласка, ім'я та прізвище разом — так потрібно для накладної. Наприклад: Оксана Петренко"


def name_invalid() -> str:
    return "Напишіть, будь ласка, українськими літерами — так буде в накладній. Наприклад: Петренко Оксана Іванівна"


def ask_city(name: str | None) -> str:
    a = _addr(name)
    return f"Дякую{', ' + a if a else ''} ✅\nКрок 3 з 3 — у яке місто відправити?"


def city_not_found() -> str:
    return "Не знайшла такого населеного пункту. Напишіть ще раз — можна з областю, наприклад: Бровари Київська"


def ask_warehouse(city: str) -> str:
    return f"📍 {e(city.replace('м. ', ''))}. Яке відділення Нової пошти зручне? Напишіть номер або оберіть 👇"


def warehouse_not_found() -> str:
    return "Такого відділення не знайшла. Напишіть номер (наприклад, 12) або вулицю."


def postomat_warning() -> str:
    return ("У поштоматі оплата проходить у застосунку Нової пошти <b>до</b> відкриття комірки — оглянути до оплати не вийде. "
            "Лишаємо поштомат чи підберемо відділення?")


# ---------- підсумок / квитанція ----------
def summary(o: Offer, order: dict) -> str:
    s = o.set(order["set_code"])
    items = " + ".join(e(it["name"].replace(" (UA)", "").replace("Liquid Solution ", "")) for it in s["items"])
    ph = order.get("phone") or ""
    ph_fmt = f"+{ph[:3]} {ph[3:5]} {ph[5:8]} {ph[8:10]} {ph[10:]}" if len(ph) == 12 else ph
    insp = ("Оглянете до оплати. Не підійшло — просто не забираєте." if order.get("delivery_type") != "postomat"
            else "Оплата в застосунку Нової пошти при отриманні.")
    return (f"Перевірте ✅\n\n"
            f"📦 {items}\n"
            f"👤 {e(order.get('name') or '')} · {ph_fmt}\n"
            f"📍 {_city(order)}, {_wh(order)}\n\n"
            f"💰 На пошті: <b>{cash(o, s)}</b>\n"
            f"{insp}\n\n"
            f"<i>Зараз нічого не платите.</i> {e(X.tone(o, order.get('variant'), 'summary_close', 'Все правильно — тисніть кнопку.'))}")


import re as _re


def _warm_paragraphs(t: str) -> str:
    """Тепле «після підтвердження» одним блоком зливається — ріжемо на 2 абзаци по першому реченню."""
    m = _re.search(r"(💛 |[.!] )", t)
    if m and m.end() < len(t) - 10:
        cut = m.end()
        return t[:cut].rstrip() + "\n\n" + t[cut:].lstrip()
    return t


def receipt(o: Offer, order: dict) -> str:
    """ОДНЕ повідомлення після підтвердження: шапка + структурована квитанція + тепле «що далі» по школі."""
    s = o.set(order["set_code"])
    a = _addr(order.get("name"))
    head = X.tone(o, order.get("variant"), "receipt", "✅ Прийняли{addr}!").format(addr=(", " + a) if a else "")
    warm = X.tone(o, order.get("variant"), "after_confirm",
                  "{addr}чудовий вибір 💛 Постараюся відправити сьогодні або завтра — щойно посилка поїде, одразу напишу сюди номер накладної. "
                  "Нова пошта зазвичай доставляє за 1–2 дні. На пошті спершу огляньте, потім платите.").format(addr="")
    warm = _warm_paragraphs(warm[:1].upper() + warm[1:])
    return (f"{e(head)}\n\n"
            f"🧾 Замовлення №{order['id']}\n"
            f"📦 {e(s['label'])} — <b>{o.fmt_price(int(s['price']))}</b> + доставка НП\n"
            f"📍 {_city(order)}, {_wh(order)}\n"
            f"💳 Оплата на пошті, після огляду\n\n"
            f"{e(warm)}")


# ---------- апсейл після підтвердження ----------
def upsell(o: Offer, name: str | None, variant: str | None = None) -> str:
    up = o.upsell
    to, frm = o.set(up["to"]), o.set(up["from"])
    delta = int(to["price"]) - int(frm["price"])
    n_items = sum(int(it.get("qty", 1)) for it in to["items"])
    per = int(round(int(to["price"]) / n_items))
    lead = X.tone(o, variant, "upsell_lead", "{addr}поки збираємо посилку — одне питання.").format(addr=_hi(name, ""))
    why = X.tone(o, variant, "upsell_why", "Шкіра навколо очей тонша — для неї потрібен окремий <b>крем для очей</b>.")
    cta = X.tone(o, variant, "upsell_cta", "Додати? 👇")
    gift_value = int(to.get("gift_value") or 0)
    return (f"{e(lead[:1].upper() + lead[1:])}\n\n"
            f"{why}\n\n"
            f"<b>Курс 60 днів</b> = 2 сироватки + крем для очей у подарунок:\n"
            f"• по <b>{o.fmt_price(per)}</b> за засіб замість {o.fmt_price(int(frm['price']))}\n"
            f"• економія <b>{o.fmt_price(gift_value)}</b> (крем безкоштовно)\n"
            f"• одна посилка, огляд до оплати\n\n"
            f"Доплата до вашого замовлення — <b>{o.fmt_price(delta)}</b>. На пошті буде {o.fmt_price(int(to['price']))}.\n\n"
            f"{e(cta)}")


def upsell_accepted(o: Offer, order: dict) -> str:
    s = o.set(order["set_code"])
    return f"✅ Оновила замовлення №{order['id']}: {e(s['label'])}.\nНа пошті: <b>{cash(o, s)}</b>. Їде однією посилкою."


def upsell_declined(o: Offer, order: dict) -> str:
    s = o.set(order["set_code"])
    return f"Добре, лишаємо: {e(s['label'])} — <b>{cash(o, s)}</b> ✅"


# ---------- доставка ----------
def shipped(o: Offer, order: dict) -> str:
    s = o.set(order["set_code"])
    head = X.tone(o, order.get("variant"), "shipped", "{addr}посилка вже їде до вас!").format(addr=_hi(order.get("name"), ""))
    return (f"📦 {e(head[:1].upper() + head[1:])}\n\n"
            f"Накладна: <code>{e(_ttn_fmt(order['ttn']))}</code> — можна відстежити в застосунку Нової пошти.\n"
            f"На пошті: <b>{cash(o, s)}</b>.\n\n"
            f"Напишу, щойно прибуде 💛")


def arrived(o: Offer, order: dict, until: date | None) -> str:
    s = o.set(order["set_code"])
    until_txt = _until(until)
    if order.get("delivery_type") != "postomat":
        how = ("Як забрати: назвіть номер телефону на касі (або покажіть застосунок НП), попросіть відкрити посилку, "
               f"огляньте — і лише тоді платите <b>{cash(o, s)}</b>. Не підійшло — кажете «не забираю», з вас 0 грн.")
    else:
        how = f"Оплата в застосунку Нової пошти: <b>{cash(o, s)}</b>."
    head = X.tone(o, order.get("variant"), "arrived_head", "{addr}посилка вже у відділенні").format(addr=_hi(order.get("name"), ""))
    return (f"📍 {e(head[:1].upper() + head[1:])}\n{_wh(order)}\n\n{how}\n"
            f"Зберігається {o.storage['days']} робочих днів{until_txt}.")


def reminder_d3(o: Offer, order: dict, until: date | None) -> str:
    until_txt = _until(until) or " ще кілька днів"
    return (f"{_hi(order.get('name'), '')}посилка чекає у відділенні{until_txt} 💛 Зайдіть, огляньте — платите лише якщо підійшло. "
            f"Не встигаєте — напишіть, продовжу зберігання.")


def reminder_d5(order: dict) -> str:
    return (f"Сьогодні останній день зберігання посилки ({_wh(order)}). "
            f"Не встигаєте — напишіть, продовжимо зберігання (Нова пошта бере за це за тарифом).")


def picked(o: Offer, order: dict) -> str:
    a = _addr(order.get("name"))
    return f"Дякую{', ' + a if a else ''}! 💛 Питання щодо застосування — пишіть сюди. Через тиждень запитаю, як вам."


def review_request(order: dict) -> str:
    return f"{_hi(order.get('name'), '')}минув тиждень — як вам сироватка? Кілька слів або фото дуже допоможуть 💛"


def returned(order: dict) -> str:
    return "Бачу, посилку не забрали — нічого страшного, повертаємо. Захочете замовити знову — просто напишіть сюди."


def not_pick_ack() -> str:
    return "Зрозуміло, дякую, що попередили — так чесно і нам простіше. Повернемо посилку."


# ---------- тиша ----------
def nudge(stage: str, minutes: int, name: str | None, steps: int) -> str:
    if minutes <= 15:
        return f"{_hi(name, '')}я тут. {steps_left_phrase(steps)} — продовжимо?"
    if minutes <= 60:
        return f"{_hi(name, '')}нагадаю: платити наперед нічого не треба — оглянете на пошті, не підійде — не забираєте. Допишемо? 💛"
    return "Збережу заявку на добу. Допишемо будь-коли — просто натисніть «Продовжити». Якщо зручніше голосом — напишіть «подзвоніть»."


def nudge_review(o: Offer, order: dict, minutes: int) -> str:
    s = o.set(order["set_code"])
    if minutes <= 15:
        return f"Замовлення зібране: {e(s['label'])} — <b>{cash(o, s)}</b>, {_wh(order)}. Підтвердити?"
    if minutes <= 120:
        return f"Підтвердження — один тап, і відправимо сьогодні, якщо до {o.delivery['same_day_cutoff']}."
    return "Востаннє нагадаю і більше не турбуватиму: платити наперед нічого не треба. Підтвердити замовлення?"


def handoff_to_client(hours: str, manager: str = "") -> str:
    who = f"{e(manager)}, нашій менеджерці" if manager else "колезі"
    return f"Передаю {who} — вона напише сюди у {e(hours)}, дзвонити не буде. Усе, що ви написали, вона бачить."


def bot_off_to_client() -> str:
    return "Дякую! Менеджер відповість вам тут найближчим часом."


def cancelled() -> str:
    return "Скасувала. Захочете повернутися — просто напишіть, оформимо за хвилину."


def opted_out() -> str:
    return "Добре, більше не турбуватиму. Передумаєте — просто напишіть."


def reminder_fire(o: Offer, order: dict | None) -> str:
    if order and order.get("set_code"):
        s = o.set(order["set_code"])
        return f"Нагадую, як домовлялися 💛 {e(s['label'])} — <b>{cash(o, s)}</b>, оплата на пошті. Продовжимо?"
    return "Нагадую, як домовлялися 💛 Продовжимо оформлення? Платити наперед нічого не треба."


def repeat_offer(o: Offer, s: dict, last: dict, name: str | None) -> str:
    return (f"{_hi(name, 'Вітаю! ')}рада бачити знову 💛 <b>{e(s['label'])} — {o.fmt_price(int(s['price']))}</b>.\n"
            f"Відправити як минулого разу — {_city(last)}, {_wh(last)}?")


def care_day1(o: Offer, name: str | None, variant: str | None = None) -> str:
    head = X.tone(o, variant, "care_day1", "{addr}підказка на перший день:").format(addr=_hi(name, ""))
    return (f"{e(head[:1].upper() + head[1:])}\n\n"
            f"🌅 Вранці: 3 краплі на чисту шкіру, зверху свій крем або макіяж.\n"
            f"🌙 Ввечері: 5 крапель на обличчя і шию, потім крем.\n\n"
            f"Перші 7 днів — щодня, не пропускайте. Питання — пишіть сюди.")


def care_day25(o: Offer, s: dict, name: str | None) -> str:
    return (f"{_hi(name, '')}флакон зазвичай закінчується через місяць. Відправити новий — {e(s['label'])}, "
            f"{o.fmt_price(int(s['price']))}, як минулого разу? Оплата на пошті.")


def cancel_confirm(order: dict) -> str:
    return f"Скасувати замовлення №{order['id']}?"


def nudge15(o: Offer, variant: str | None, name: str | None, steps: int) -> str:
    t = X.tone(o, variant, "nudge15", "{addr}я тут. {left} — продовжимо?")
    a = _hi(name, "")
    left = steps_left_phrase(steps)
    out = t.format(addr=a, left=(left[:1].lower() + left[1:]) if a else left, steps=plural_steps(steps))
    return e(out[:1].upper() + out[1:])


def help_text(o: Offer) -> str:
    s = o.default_set
    return ("Я Оля — оформлюю замовлення тут, у чаті 💛\n\n"
            f"• {e(s['label'])} — <b>{o.fmt_price(int(s['price']))}</b>, оплата на пошті після огляду\n"
            "• Передоплат і даних картки не просимо\n"
            "• Дзвонити не будемо — усе листуванням\n"
            "• Щоб почати спочатку — напишіть /start\n"
            "• Щоб я більше не писала — /stop\n\n"
            "Потрібна жива людина?")
