"""State machine заказа. Единственное место, где описаны стадии и допустимые переходы.

Код решает, LLM — нет: переход выполняется только через store.transition(),
который проверяет allowed() и guards.
"""
from __future__ import annotations

from typing import Iterable

# Сбор данных
NEW, PHONE, NAME, CITY, WAREHOUSE, UPSELL, REVIEW = (
    "new", "phone", "name", "city", "warehouse", "upsell", "review",
)
# После подтверждения
CONFIRMED, QUEUED_CRM, CONFIRMED_CRM = "confirmed", "queued_crm", "confirmed_crm"
SHIPPED, ARRIVED, PICKED, RETURNED, DONE, CANCELLED = (
    "shipped", "arrived", "picked", "returned", "done", "cancelled",
)
LEAD_CRM = "lead_crm"   # недооформлений лід переданий у CRM на прозвон (термінальна для бота)

COLLECT_STAGES: tuple[str, ...] = (NEW, PHONE, NAME, CITY, WAREHOUSE, UPSELL, REVIEW)
PRE_SHIP_STAGES: tuple[str, ...] = COLLECT_STAGES + (CONFIRMED, QUEUED_CRM, CONFIRMED_CRM)
ACTIVE_STAGES: tuple[str, ...] = PRE_SHIP_STAGES + (SHIPPED, ARRIVED)
TERMINAL: tuple[str, ...] = (DONE, CANCELLED, RETURNED, LEAD_CRM)

_ORDER = [NEW, PHONE, NAME, CITY, WAREHOUSE, UPSELL, REVIEW]

TRANSITIONS: dict[str, set[str]] = {
    NEW: {PHONE, CANCELLED},
    PHONE: {NAME, CANCELLED},
    NAME: {CITY, CANCELLED, LEAD_CRM},
    CITY: {WAREHOUSE, CANCELLED, LEAD_CRM},
    WAREHOUSE: {UPSELL, REVIEW, CANCELLED, LEAD_CRM},
    UPSELL: {REVIEW, CANCELLED, LEAD_CRM},
    REVIEW: {CONFIRMED, CANCELLED, WAREHOUSE, CITY, NAME, PHONE, LEAD_CRM},  # «Змінити»
    LEAD_CRM: set(),
    CONFIRMED: {QUEUED_CRM, CONFIRMED_CRM, CANCELLED},
    QUEUED_CRM: {CONFIRMED_CRM, CANCELLED},
    CONFIRMED_CRM: {SHIPPED, CANCELLED},
    SHIPPED: {ARRIVED, PICKED, RETURNED, CANCELLED},
    ARRIVED: {PICKED, RETURNED},
    PICKED: {DONE},
    RETURNED: set(),
    DONE: set(),
    CANCELLED: set(),
}

# Маппинг статусов Нової Пошти (StatusCode из getStatusDocuments) → стадия
NP_ARRIVED_CODES = {"7", "8"}                 # прибув у відділення / поштомат
NP_PICKED_CODES = {"9", "10", "11"}           # отримано
NP_RETURN_CODES = {"102", "103", "104", "105", "106", "108"}  # відмова / повернення
NP_IN_TRANSIT_CODES = {"4", "5", "6", "41", "101"}


def allowed(frm: str, to: str) -> bool:
    return to in TRANSITIONS.get(frm, set())


def next_collect_stage(order: dict) -> str:
    """Первая незаполненная стадия сбора — чтобы «Змінити» возвращал ровно туда."""
    if not order.get("phone"):
        return PHONE
    if not order.get("name"):
        return NAME
    if not order.get("np_city_ref"):
        return CITY
    if not order.get("np_wh_ref") and order.get("delivery_type") != "courier":
        return WAREHOUSE
    return REVIEW


def ready_to_confirm(order: dict) -> list[str]:
    """Список недостающих полей; пустой список = можно подтверждать."""
    missing = []
    if not order.get("set_code"):
        missing.append("set_code")
    if not order.get("phone"):
        missing.append("phone")
    if not order.get("name"):
        missing.append("name")
    if not order.get("np_city_ref"):
        missing.append("city")
    if order.get("delivery_type") == "courier":
        if not order.get("np_wh_name"):
            missing.append("address")
    elif not order.get("np_wh_ref"):
        missing.append("warehouse")
    return missing


def steps_left(order: dict) -> int:
    return len([m for m in ready_to_confirm(order) if m != "set_code"])


def is_collecting(stage: str) -> bool:
    return stage in COLLECT_STAGES


def stage_from_np(code: str) -> str | None:
    if code in NP_ARRIVED_CODES:
        return ARRIVED
    if code in NP_PICKED_CODES:
        return PICKED
    if code in NP_RETURN_CODES:
        return RETURNED
    return None


def in_stages(stages: Iterable[str]) -> str:
    """SQL-фрагмент IN (...) для запросов по стадиям."""
    return "(" + ",".join("'" + s + "'" for s in stages) + ")"
