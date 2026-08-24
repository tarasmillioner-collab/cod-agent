"""State machine, offer, guards, tools, store."""
from __future__ import annotations

import asyncio

import pytest

from core import state as S
from core.offer import OfferError, load_offer
from core.store import TransitionError
from core.tools import ToolCtx, exec_tool
from tests.fakes import ROOT, make_services


def test_offer_loads_and_validates():
    o = load_offer(ROOT / "offer.yaml")
    assert [s["code"] for s in o.sets] == ["s1", "s2"]
    assert o.prices >= {590, 1180, 393}
    assert o.fmt_price(1089) == "1 089 грн"
    assert o.upsell["from"] == "s1" and o.upsell["to"] == "s2"


def test_offer_rejects_bad_ladder(tmp_path):
    bad = (ROOT / "offer.yaml").read_text(encoding="utf-8").replace("price: 1180", "price: 500", 1)
    p = tmp_path / "o.yaml"
    p.write_text(bad, encoding="utf-8")
    with pytest.raises(OfferError):
        load_offer(p)


def test_transitions():
    svc = make_services()
    st = svc.store
    st.upsert_chat(1, 1, "u", "Оксана")
    o = st.create_order(1, "s1", 590, {})
    assert o["stage"] == S.NEW
    o = st.transition(o["id"], S.PHONE)
    with pytest.raises(TransitionError):
        st.transition(o["id"], S.CONFIRMED)
    o = st.transition(o["id"], S.NAME, phone="380671234567")
    assert st.has_event(o["id"], "stage:name")
    # второй активный заказ на чат запрещён
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        st.create_order(1, "s1", 590, {})
    st.transition(o["id"], S.CANCELLED)
    assert st.active_order(1) is None
    st.create_order(1, "s2", 1089, {})


def test_ready_to_confirm():
    o = {"set_code": "s1", "phone": "380", "name": "A", "np_city_ref": "c", "np_wh_ref": None, "delivery_type": "warehouse"}
    assert S.ready_to_confirm(o) == ["warehouse"]
    o["np_wh_ref"] = "w"
    assert S.ready_to_confirm(o) == []
    assert S.next_collect_stage({"phone": None}) == S.PHONE


def test_guards_price_date_claims_blacklist():
    g = make_services().guards
    assert g.check("Набір коштує 1 180 грн, оплата при отриманні.").ok
    r = g.check("Спеціально для вас 999 грн!")
    assert not r.ok and any(x.startswith("price:999") for x in r.reasons)
    assert "date_promise" in g.check("Посилка буде у четвер.").reasons
    assert any(x.startswith("claim") for x in g.check("Сироватка лікує зморшки.").reasons)
    assert any(x.startswith("scam") for x in g.check("Залишилось 3 штуки, встигніть!").reasons)
    r = g.check("Ваш заказ прийнято, скидка вже врахована.")
    assert "заказ" not in r.text and "замовлення" in r.text and "знижка" in r.text
    assert "ru_chars" in g.check("Привет, это ваш заказ").reasons
    assert any(x.startswith("too_long") for x in g.check("а" * 400).reasons)
    assert g.check("Сума 590 грн", extra_amounts={590}).ok


def test_event_idempotent():
    st = make_services().store
    st.upsert_chat(1, 1, None, None)
    o = st.create_order(1, "s1", 590, {})
    assert st.event(o["id"], "shipped_sent")
    assert not st.event(o["id"], "shipped_sent")


def test_tools_flow():
    svc = make_services()
    st = svc.store
    chat = st.upsert_chat(5, 5, "u", "Оксана")
    o = st.create_order(5, "s1", 590, {})
    st.transition(o["id"], S.PHONE)
    st.transition(o["id"], S.NAME, phone="380671234567")
    ctx = ToolCtx(st, svc.offer, svc.np, chat, st.get_order(o["id"]))

    async def go():
        assert (await exec_tool(ctx, "get_offer", {}))["sets"][1]["price_uah"] == 1180
        assert "error" in await exec_tool(ctx, "set_bundle", {"code": "s9"})
        assert "error" in await exec_tool(ctx, "set_name", {"name": "John"})
        r = await exec_tool(ctx, "set_name", {"name": "Оксана Петренко"})
        assert r["ok"] and ctx.order["stage"] == S.CITY
        r = await exec_tool(ctx, "np_search_city", {"query": "Київ"})
        assert r["results"][0]["ref"] == "c-kyiv"
        assert "error" in await exec_tool(ctx, "set_city", {"ref": "nope"})
        # set_city ищет ref в кэше — положим туда результат поиска
        st.cache_put("city", "київ", [{"ref": "c-kyiv", "name": "Київ", "present": "м. Київ"}])
        r = await exec_tool(ctx, "set_city", {"ref": "c-kyiv"})
        assert r["ok"] and ctx.order["stage"] == S.WAREHOUSE
        r = await exec_tool(ctx, "np_search_warehouse", {"query": "12"})
        assert r["results"][0]["ref"] == "w12"
        assert "error" in await exec_tool(ctx, "request_confirm", {})
        r = await exec_tool(ctx, "set_warehouse", {"ref": "w12"})
        assert r["ok"] and ctx.order["stage"] == S.UPSELL
        r = await exec_tool(ctx, "request_confirm", {})
        assert r["ok"] and ctx.order["stage"] == S.REVIEW and "summary" in ctx.ui
        # даунсейл ставит флаг
        r = await exec_tool(ctx, "set_bundle", {"code": "s2"})
        r = await exec_tool(ctx, "set_bundle", {"code": "s1"})
        assert st.get_chat(5)["flags"].get("downgraded")
        r = await exec_tool(ctx, "handoff", {"reason": "call me"})
        assert any(u.startswith("handoff:call me") for u in ctx.ui)

    asyncio.run(go())
