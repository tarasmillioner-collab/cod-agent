"""Метрики воронки для /stats, ежедневного отчёта и дашборда. Всё — из funnel_events + orders.

metrics(store, days, variant=None) -> dict; ab(store, days) -> {variant: metrics}; z-test на долях.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from core import state as S
from core.store import Store

FUNNEL = [
    ("bot_start", "зайшли"),
    ("phone_received", "телефон"),
    ("name_received", "ім'я"),
    ("warehouse_received", "відділення"),
    ("summary_shown", "підсумок"),
    ("lead_confirmed", "підтвердили"),
    ("crm_created", "в CRM"),
    ("ttn_sent", "ТТН"),
    ("arrived_notified", "прибули"),
    ("picked_up", "забрали"),
]


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _win(days: int, shift: int = 0) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=days + shift)).isoformat(), (now - timedelta(days=shift)).isoformat()


def pct(a: float, b: float) -> float:
    return (a / b * 100) if b else 0.0


def fmt_pct(a: float, b: float) -> str:
    return f"{pct(a, b):.0f}%" if b else "–"


def counts(store: Store, days: int, variant: str | None = None, shift: int = 0) -> dict[str, int]:
    a, b = _win(days, shift)
    q = "SELECT name, COUNT(DISTINCT COALESCE(chat_id, id)) FROM funnel_events WHERE ts_utc>=? AND ts_utc<?"
    args: list = [a, b]
    if variant:
        q += " AND variant=?"
        args.append(variant)
    rows = store.c.execute(q + " GROUP BY name", args).fetchall()
    return {r[0]: r[1] for r in rows}


def metrics(store: Store, days: int, variant: str | None = None, default_set: str = "s1", shift: int = 0) -> dict:
    c = counts(store, days, variant, shift)
    vq, vargs = ("", []) if not variant else (" AND variant=?", [variant])
    since, until = _win(days, shift)
    entered = c.get("bot_start", 0)
    confirmed_rows = store.c.execute(
        f"SELECT set_code, price_uah, created_utc, confirmed_utc, stage FROM orders WHERE created_utc>=? AND created_utc<? AND confirmed_utc IS NOT NULL AND stage NOT IN {S.in_stages((S.CANCELLED,))}{vq}",
        [since, until, *vargs]).fetchall()
    confirmed = len(confirmed_rows)
    import json as _json
    try:
        _costs = _json.loads(store.get_setting("set_netcost") or "{}")
    except Exception:  # noqa: BLE001
        _costs = {}
    _margins = [int(r[1] or 0) - float(_costs[r[0]]) for r in confirmed_rows if r[0] in _costs]
    avg_margin = (sum(_margins) / len(_margins)) if _margins else None
    bundle = sum(1 for r in confirmed_rows if r[0] and r[0] != default_set)
    avg_check = (sum(int(r[1] or 0) for r in confirmed_rows) / confirmed) if confirmed else 0
    ttc = []
    for r in confirmed_rows:
        try:
            ttc.append((datetime.fromisoformat(r[3]) - datetime.fromisoformat(r[2])).total_seconds() / 60)
        except Exception:  # noqa: BLE001
            pass
    ttc.sort()
    median_min = ttc[len(ttc) // 2] if ttc else 0
    fast5 = sum(1 for t in ttc if t <= 5)
    urow = store.c.execute(
        f"SELECT COALESCE(SUM(upsell_shown),0), COALESCE(SUM(upsell_accepted),0) FROM orders "
        f"WHERE created_utc>=? AND created_utc<? AND stage NOT IN {S.in_stages((S.CANCELLED,))}{vq}", [since, until, *vargs]).fetchone()
    up_shown, up_acc = int(urow[0]), int(urow[1])
    # гроші періоду = замовлення, ВИКУПЛЕНІ в цьому вікні
    picked_rows = store.c.execute(
        f"SELECT price_uah, set_code FROM orders WHERE picked_utc>=? AND picked_utc<?{vq}", [since, until, *vargs]).fetchall()
    # викуп — когортно: скільки з відправлених у вікні вже забрали
    shipped = store.c.execute(
        f"SELECT COUNT(*) FROM orders WHERE shipped_utc>=? AND shipped_utc<?{vq}", [since, until, *vargs]).fetchone()[0]
    picked_of_shipped = store.c.execute(
        f"SELECT COUNT(*) FROM orders WHERE shipped_utc>=? AND shipped_utc<? AND picked_utc IS NOT NULL{vq}",
        [since, until, *vargs]).fetchone()[0]
    picked = len(picked_rows)
    revenue = sum(int(r[0] or 0) for r in picked_rows)
    margin_total = sum(int(r[0] or 0) - float(_costs[r[1]]) for r in picked_rows if r[1] in _costs)
    returned = store.c.execute(f"SELECT COUNT(*) FROM orders WHERE stage='returned' AND closed_utc>=? AND closed_utc<?{vq}", [since, until, *vargs]).fetchone()[0]
    # ── когорта періоду: що сталося із замовленнями, які прийшли в ці дні (шт + гроші + маржа) ──
    coh = store.c.execute(
        f"SELECT price_uah, set_code, shipped_utc, picked_utc, stage FROM orders "
        f"WHERE created_utc>=? AND created_utc<? AND confirmed_utc IS NOT NULL "
        f"AND stage NOT IN {S.in_stages((S.CANCELLED,))}{vq}", [since, until, *vargs]).fetchall()

    def _agg(rows_) -> dict:
        n = len(rows_)
        total = sum(int(r[0] or 0) for r in rows_)
        marg = sum(int(r[0] or 0) - float(_costs[r[1]]) for r in rows_ if r[1] in _costs)
        known = sum(1 for r in rows_ if r[1] in _costs)
        return {"n": n, "sum": total, "avg": (total / n) if n else 0,
                "margin": marg if known else None,
                "margin_avg": (marg / known) if known else None}

    money = {"entered": {"n": entered}, "confirmed": _agg(coh),
             "shipped": _agg([r for r in coh if r[2]]),
             "picked": _agg([r for r in coh if r[3]]),
             "returned": _agg([r for r in coh if r[4] == "returned"])}

    by_set: dict[str, dict] = {}
    for r in store.c.execute(
            f"SELECT set_code, COUNT(*), SUM(CASE WHEN picked_utc IS NOT NULL THEN 1 ELSE 0 END), SUM(CASE WHEN shipped_utc IS NOT NULL THEN 1 ELSE 0 END) FROM orders WHERE created_utc>=? AND created_utc<? AND confirmed_utc IS NOT NULL AND stage NOT IN {S.in_stages((S.CANCELLED,))}{vq} GROUP BY set_code",
            [since, until, *vargs]).fetchall():
        by_set[r[0] or "?"] = {"confirmed": r[1], "picked": r[2] or 0, "shipped": r[3] or 0}
    return {
        "days": days, "variant": variant, "funnel": c, "entered": entered, "confirmed": confirmed,
        "approve": pct(confirmed, entered), "bundle": bundle, "bundle_share": pct(bundle, confirmed),
        "avg_check": avg_check, "avg_margin": avg_margin, "shipped": shipped, "picked": picked, "picked_of_shipped": picked_of_shipped,
        "buyout": pct(picked_of_shipped, shipped), "returned": returned,
        "money": money, "revenue": revenue, "margin_total": margin_total, "rpe": (revenue / entered) if entered else 0.0,
        "median_min": median_min, "fast5_share": pct(fast5, confirmed), "by_set": by_set,
        "handoff": c.get("handoff", 0), "lead_to_crm": c.get("lead_to_crm", 0), "llm_limited": c.get("llm_limited", 0),
        "llm_blocked": c.get("llm_blocked", 0), "upsell_shown": up_shown, "upsell_accepted": up_acc,
        "upsell_cvr": pct(up_acc, up_shown),
        "cancelled": c.get("cancelled_before_ship", 0),
    }


def z_test(p1_num: int, p1_den: int, p2_num: int, p2_den: int) -> float | None:
    """z-статистика различия долей; |z|>1.96 ≈ 95%."""
    if not p1_den or not p2_den:
        return None
    p1, p2 = p1_num / p1_den, p2_num / p2_den
    p = (p1_num + p2_num) / (p1_den + p2_den)
    se = math.sqrt(p * (1 - p) * (1 / p1_den + 1 / p2_den)) if 0 < p < 1 else 0
    return (p1 - p2) / se if se else None


def ab(store: Store, days: int, variants: list[str], default_set: str = "s1") -> dict[str, dict]:
    return {v: metrics(store, days, v, default_set) for v in variants}


def health(store: Store) -> dict:
    failed = store.c.execute("SELECT COUNT(*) FROM outbox WHERE state='failed' AND last_error NOT IN ('reset','cancelled')").fetchone()[0]
    pending = store.c.execute("SELECT COUNT(*) FROM outbox WHERE state='pending'").fetchone()[0]
    usd = store.usage_today_usd()
    reasons = store.c.execute(
        "SELECT json_extract(meta_json,'$.reason'), COUNT(*) FROM funnel_events WHERE name='handoff' AND ts_utc>=? GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
        (_since(7),)).fetchall()
    return {"outbox_failed": failed, "outbox_pending": pending, "llm_usd_today": usd,
            "handoff_reasons": [(r[0] or "?", r[1]) for r in reasons], "bot_enabled": store.bot_enabled()}


def grn(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", " ") + " грн"


def stats_text(store: Store, days: int = 1, variants: list[str] | None = None, labels: dict | None = None,
               default_set: str = "s1") -> str:
    m = metrics(store, days, None, default_set)
    c = m["funnel"]
    lines = [f"📊 За {days} дн.: зайшли {m['entered']} → підтвердили {m['confirmed']} ({m['approve']:.0f}%) → "
             f"в CRM {c.get('crm_created', 0)} → ТТН {c.get('ttn_sent', 0)} → забрали {m['picked']} ({m['buyout']:.0f}% від відправлених)",
             f"💰 чек {grn(m['avg_check'])} · маржа/замовлення {grn(m['avg_margin']) if m['avg_margin'] is not None else '—'} · "
             f"виручка/зайшлого {grn(m['rpe'])} · бандл {m['bundle_share']:.0f}% · "
             f"медіана до підтвердження {m['median_min']:.0f} хв"]
    if variants and len(variants) > 1:
        per = ab(store, days, variants, default_set)
        best = max(per, key=lambda v: per[v]["rpe"])
        for v in variants:
            x = per[v]
            lab = (labels or {}).get(v, v)
            lines.append(f"{v} «{lab}»: зайшли {x['entered']} · approve {x['approve']:.0f}% · "
                         f"апсейл {x['upsell_cvr']:.0f}% ({x['upsell_accepted']}/{x['upsell_shown']}) · бандл {x['bundle_share']:.0f}% · "
                         f"чек {grn(x['avg_check'])} · викуп {x['buyout']:.0f}% · на зайшлого {grn(x['rpe'])}" + ("  ← лідер" if v == best and x["entered"] else ""))
        if len(variants) == 2:
            a, b = per[variants[0]], per[variants[1]]
            z = z_test(a["confirmed"], a["entered"], b["confirmed"], b["entered"])
            if z is not None:
                lines.append(f"approve A vs B: z={z:.2f} ({'достовірно' if abs(z) > 1.96 else 'ще шум — чекаємо даних'})")
    h = health(store)
    lines.append(f"⚠️ тиша→CRM: {m['lead_to_crm']} · handoff: {m['handoff']} · LLM-ліміт: {m['llm_limited']} · "
                 f"скасували: {m['cancelled']} · outbox failed: {h['outbox_failed']} · бот {'🟢' if h['bot_enabled'] else '🔴'}")
    return "\n".join(lines)
