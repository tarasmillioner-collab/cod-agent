"""HTTP API для дашборда: живі метрики, відповіді менеджера, масові розсилки.

Слухає 127.0.0.1:<api_port>; назовні дивиться через Caddy (reverse_proxy /api/*).
Читання (/api/stats) — публічне, як і сам дашборд. Дії (reply/close/broadcast/segments) — за ADMIN_API_KEY.
"""
from __future__ import annotations

import asyncio
import hmac
import html
import json
import logging
from datetime import datetime, timedelta, timezone

from aiohttp import web
from aiogram.exceptions import TelegramForbiddenError

from db import now_utc

log = logging.getLogger("webapi")

import re as _re
_re_field = _re.compile(r"^(?:[A-Z]\.[a-z0-9_]+|obj\.[a-z0-9_]+)$")

_TAGS_RX = _re.compile(r"<[^>]+>")


def _plain_txt(t: str) -> str:
    return _TAGS_RX.sub("", t or "").strip()


SEND_PAUSE = 0.06          # ~16 msg/s — нижче ліміту Telegram (30/s)


# ---------- сегменти розсилок ----------
def _cut(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


SEGMENTS: dict[str, str] = {
    "all": "Всі, хто стартував бота",
    "buyers": "Викупили хоч раз",
    "s1_no_course": "Купили сироватку, без курсу",
    "refill25": "Викупили 25+ днів тому (час нового флакона)",
    "lost": "Заходили, але не оформили / скасували",
}

_BASE = "c.blocked_utc IS NULL AND c.opted_out_utc IS NULL"


def segment_ids(store, seg: str) -> list[int]:
    q = {
        "all": f"SELECT c.tg_user_id FROM chats c WHERE {_BASE}",
        "buyers": f"SELECT DISTINCT c.tg_user_id FROM chats c JOIN orders o ON o.chat_id=c.tg_user_id "
                  f"WHERE {_BASE} AND o.picked_utc IS NOT NULL",
        "s1_no_course": f"SELECT DISTINCT c.tg_user_id FROM chats c JOIN orders o ON o.chat_id=c.tg_user_id "
                        f"WHERE {_BASE} AND o.picked_utc IS NOT NULL AND o.set_code='s1' "
                        f"AND c.tg_user_id NOT IN (SELECT chat_id FROM orders WHERE set_code!='s1' AND confirmed_utc IS NOT NULL)",
        "refill25": f"SELECT c.tg_user_id FROM chats c JOIN orders o ON o.chat_id=c.tg_user_id "
                    f"WHERE {_BASE} GROUP BY c.tg_user_id HAVING MAX(o.picked_utc) IS NOT NULL AND MAX(o.picked_utc) <= ?",
        "lost": f"SELECT c.tg_user_id FROM chats c WHERE {_BASE} "
                f"AND EXISTS(SELECT 1 FROM orders o WHERE o.chat_id=c.tg_user_id) "
                f"AND NOT EXISTS(SELECT 1 FROM orders o WHERE o.chat_id=c.tg_user_id AND o.confirmed_utc IS NOT NULL)",
    }.get(seg)
    if not q:
        return []
    args = (_cut(25),) if seg == "refill25" else ()
    return [r[0] for r in store.c.execute(q, args).fetchall()]


# ---------- app ----------
def _ok(data: dict) -> web.Response:
    return web.json_response({"ok": True, **data})


def _err(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": msg}, status=status)


def make_app(svc) -> web.Application:
    app = web.Application(client_max_size=12 * 1024 * 1024)

    def actor_of(body: dict) -> str | None:
        """Ім'я того, хто діє (за його персональним кодом). None — код невірний."""
        got = str(body.get("key") or "")
        for key, name in (svc.cfg.admin_keys or {}).items():
            if key and hmac.compare_digest(got, key):
                return name
        return None

    def authed(body: dict) -> bool:
        return actor_of(body) is not None

    def logit(actor: str, action: str, target: str = "", detail: str = "") -> None:
        svc.store.c.execute(
            "INSERT INTO dash_log(ts_utc, actor, action, target, detail) VALUES(?,?,?,?,?)",
            (now_utc(), actor, action, target, detail[:200]))

    # --- живі метрики (публічні, як і сам дашборд) ---
    async def stats(req: web.Request) -> web.Response:
        from core import experiments as X
        from obs.stats import ab, metrics
        days = max(1, min(int(req.query.get("days", "1") or 1), 90))
        variants = X.variants_of(svc.offer)
        m = metrics(svc.store, days, None, svc.offer.default_set["code"])
        per = ab(svc.store, days, variants, svc.offer.default_set["code"])
        labels = {v: X.label(svc.offer, v) for v in variants}
        prev = metrics(svc.store, days, None, svc.offer.default_set["code"], shift=days)
        lc = svc.store.c.execute(
            "SELECT id, price_uah, np_city_name, name, confirmed_utc FROM orders "
            "WHERE confirmed_utc IS NOT NULL AND stage!='cancelled' ORDER BY confirmed_utc DESC LIMIT 1").fetchone()
        last_c = dict(lc) if lc else None
        # пульс: 14 днів — підтверджені та виручка по днях
        cut = _cut(13)[:10]
        conf = dict(svc.store.c.execute(
            "SELECT substr(confirmed_utc,1,10), COUNT(*) FROM orders "
            "WHERE confirmed_utc>=? AND stage!='cancelled' GROUP BY 1", (cut,)).fetchall())
        rev = dict(svc.store.c.execute(
            "SELECT substr(picked_utc,1,10), SUM(price_uah) FROM orders WHERE picked_utc>=? GROUP BY 1", (cut,)).fetchall())
        daily = []
        d0 = datetime.now(timezone.utc)
        for i in range(13, -1, -1):
            k = (d0 - timedelta(days=i)).strftime("%Y-%m-%d")
            daily.append({"d": k[5:], "c": int(conf.get(k, 0) or 0), "r": int(rev.get(k, 0) or 0)})
        # жива стрічка подій
        feed = [dict(r) for r in svc.store.c.execute(
            "SELECT f.name, f.ts_utc, f.order_id, c.first_name, o.price_uah, o.set_code "
            "FROM funnel_events f LEFT JOIN chats c ON c.tg_user_id=f.chat_id LEFT JOIN orders o ON o.id=f.order_id "
            "WHERE f.name IN ('bot_start','lead_confirmed','upsell_accepted','ttn_sent','picked_up','cancelled_before_ship','arrived_notified') "
            "ORDER BY f.id DESC LIMIT 14").fetchall()]
        return _ok({"days": days, "m": m, "ab": per, "labels": labels, "prev": prev,
                    "daily": daily, "feed": feed, "last_confirmed": last_c, "now": now_utc(),
                    "settings": {"push_orders": svc.store.get_setting("push_orders", "1"),
                                 "bot_enabled": "1" if svc.store.bot_enabled() else "0"}})

    # --- сегменти (лічильники) ---
    async def segments(req: web.Request) -> web.Response:
        body = await req.json()
        if not authed(body):
            return _err("bad key", 403)
        return _ok({"segments": {s: {"label": lab, "count": len(segment_ids(svc.store, s))}
                                 for s, lab in SEGMENTS.items()}})

    # --- відповідь менеджера в чат ---
    async def reply(req: web.Request) -> web.Response:
        body = await req.json()
        if not authed(body):
            return _err("bad key", 403)
        who = actor_of(body) or "Менеджер"
        uid, text = int(body.get("chat_id") or 0), (body.get("text") or "").strip()
        if not uid or not text or len(text) > 3500:
            return _err("chat_id/text")
        ch = svc.store.get_chat(uid)
        if not ch:
            return _err("чат не знайдено", 404)
        busy = (ch.get("assignee") or "")
        if busy and busy != who and not body.get("take"):
            return _err(f"чат веде {busy} — натисніть «перехопити», щоб відповідати", 409)
        try:
            await svc.bot.send_message(ch["chat_id"], html.escape(text))
        except TelegramForbiddenError:
            svc.store.update_chat(uid, blocked_utc=now_utc())
            return _err("клієнт заблокував бота", 410)
        if ch.get("mode") != "human":
            svc.store.open_handoff(uid, None, None, "dashboard_reply")
        svc.store.update_chat(uid, mode="human", assignee=who)
        svc.store.add_message(uid, "assistant", f"[{who}] {text}")
        logit(who, "reply", str(uid), text)
        return _ok({"mode": "human", "assignee": who})

    # --- повернути чат боту ---
    async def close(req: web.Request) -> web.Response:
        body = await req.json()
        if not authed(body):
            return _err("bad key", 403)
        who = actor_of(body) or "Менеджер"
        uid = int(body.get("chat_id") or 0)
        svc.store.update_chat(uid, mode="bot", assignee=None)
        svc.store.close_handoff(uid)
        logit(who, "back_to_bot", str(uid))
        return _ok({"mode": "bot"})

    # --- розсилка ---
    async def broadcast(req: web.Request) -> web.Response:
        body = await req.json()
        if not authed(body):
            return _err("bad key", 403)
        seg, text = str(body.get("segment") or ""), (body.get("text") or "").strip()
        photo = (body.get("photo_url") or "").strip()
        if photo and not photo.startswith("https://"):
            return _err("фото — лише https-URL")
        if seg not in SEGMENTS:
            return _err("невідомий сегмент")
        if not text or len(text) > 3500:
            return _err("текст 1..3500 символів")
        who = actor_of(body) or "Менеджер"
        ids = segment_ids(svc.store, seg)
        if body.get("dry"):
            return _ok({"total": len(ids), "segment": SEGMENTS[seg]})
        if not ids:
            return _err("сегмент порожній")
        recent = svc.store.c.execute(
            "SELECT actor, ts_utc FROM broadcasts WHERE segment=? AND ts_utc>? ORDER BY id DESC LIMIT 1",
            (seg, _cut(0) if False else (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())).fetchone()
        if recent and not body.get("force"):
            return _err(f"{recent[0] or 'хтось'} щойно надіслав на цей сегмент ({recent[1][11:16]}). "
                        f"Якщо це навмисно — натисніть ще раз протягом хвилини", 409)
        cur = svc.store.c.execute(
            "INSERT INTO broadcasts(ts_utc, segment, text, photo, total, state, actor) VALUES(?,?,?,?,?, 'running', ?)",
            (now_utc(), seg, text[:500], photo or None, len(ids), who))
        bid = cur.lastrowid
        logit(who, "broadcast", seg, text)
        asyncio.create_task(_run_broadcast(svc, bid, ids, text, photo))
        return _ok({"broadcast_id": bid, "total": len(ids)})

    async def broadcasts_list(req: web.Request) -> web.Response:
        body = await req.json()
        if not authed(body):
            return _err("bad key", 403)
        rows = svc.store.c.execute(
            "SELECT id, ts_utc, segment, text, total, sent, blocked, state, actor FROM broadcasts ORDER BY id DESC LIMIT 10").fetchall()
        return _ok({"items": [dict(r) for r in rows]})

    # --- сценарій бота: перегляд і правки текстів ---
    async def flow(req: web.Request) -> web.Response:
        from core import experiments as X
        from web import flow as FL
        variant = req.query.get("variant") or (X.variants_of(svc.offer) or ["A"])[0]
        steps, obj = FL.build(svc.offer, variant)
        return _ok({"variant": variant, "variants": X.variants_of(svc.offer),
                    "labels": {v: X.label(svc.offer, v) for v in X.variants_of(svc.offer)},
                    "steps": steps, "objections": obj, "overrides": list(X.overrides().keys())})

    SETTINGS_OK = {"push_orders": {"0", "1"}, "bot_enabled": {"0", "1"}}

    async def setting(req: web.Request) -> web.Response:
        body = await req.json()
        if not authed(body):
            return _err("bad key", 403)
        k, v = str(body.get("name") or ""), str(body.get("value") or "")
        if k not in SETTINGS_OK or v not in SETTINGS_OK[k]:
            return _err("не можна змінювати це поле")
        svc.store.set_setting(k, v)
        _who = actor_of(body) or "Менеджер"
        logit(_who, "setting", k, v)
        from web import state_sync
        state_sync.fire(svc, _who, f"змінив налаштування {k}={v}")
        return _ok({"key": k, "value": v})

    async def flow_save(req: web.Request) -> web.Response:
        import json as _json
        from core import experiments as X
        from core import objections as OBJ
        from web import flow as FL
        body = await req.json()
        if not authed(body):
            return _err("bad key", 403)
        k, text = str(body.get("field") or ""), str(body.get("text") or "")
        if not _re_field.match(k):
            return _err("невідоме поле")
        reset = bool(body.get("reset"))
        ov = X.overrides()
        if reset:
            ov.pop(k, None)
        else:
            bad = FL.validate(k, text)
            if bad:
                return _err(bad)
            ov[k] = text.strip()
        X.set_overrides(ov)
        svc.store.set_setting("copy_overrides", _json.dumps(ov, ensure_ascii=False))
        if k.startswith("obj."):
            svc.objections = OBJ.load(svc.offer)
        svc.store.funnel("copy_edited", 0, None, {"field": k, "reset": reset})
        _who = actor_of(body) or "Менеджер"
        logit(_who, "reset_text" if reset else "edit_text", k, text)
        from web import state_sync
        state_sync.fire(svc, _who, ("повернув стандартний текст " if reset else "змінив текст ") + k)
        return _ok({"field": k, "reset": reset})

    # --- живий стан діалогів: хто веде, хто чекає, нові повідомлення ---
    async def dialogs(req: web.Request) -> web.Response:
        rows = svc.store.c.execute(
            """SELECT c.tg_user_id AS id, c.mode, c.assignee,
                      (SELECT content FROM messages m WHERE m.chat_id=c.tg_user_id ORDER BY m.id DESC LIMIT 1) AS last_t,
                      (SELECT role FROM messages m WHERE m.chat_id=c.tg_user_id ORDER BY m.id DESC LIMIT 1) AS last_r,
                      (SELECT ts_utc FROM messages m WHERE m.chat_id=c.tg_user_id ORDER BY m.id DESC LIMIT 1) AS last_ts
               FROM chats c WHERE EXISTS(SELECT 1 FROM messages m WHERE m.chat_id=c.tg_user_id)
               ORDER BY last_ts DESC LIMIT 40""").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["last_t"] = _plain_txt(d.get("last_t") or "")[:120]
            out.append(d)
        res = {"chats": out}
        cid = req.query.get("chat_id")
        since = req.query.get("since") or ""
        if cid:
            msgs = svc.store.c.execute(
                "SELECT role, content, ts_utc FROM messages WHERE chat_id=? AND ts_utc>? ORDER BY id LIMIT 40",
                (int(cid), since)).fetchall()
            res["msgs"] = [{"r": "u" if m["role"] == "user" else "a",
                            "t": _plain_txt(m["content"])[:900], "ts": m["ts_utc"][:19]} for m in msgs]
        return _ok(res)

    async def dash_log(req: web.Request) -> web.Response:
        rows = svc.store.c.execute(
            "SELECT ts_utc, actor, action, target, detail FROM dash_log ORDER BY id DESC LIMIT 15").fetchall()
        return _ok({"items": [dict(r) for r in rows]})

    async def whoami(req: web.Request) -> web.Response:
        body = await req.json()
        who = actor_of(body)
        if not who:
            return _err("Такого коду немає. Перевірте, чи скопіювали повністю", 403)
        return _ok({"name": who})

    app.router.add_post("/api/whoami", whoami)
    app.router.add_get("/api/dialogs", dialogs)
    app.router.add_get("/api/log", dash_log)
    app.router.add_post("/api/setting", setting)
    app.router.add_get("/api/flow", flow)
    app.router.add_post("/api/flow_save", flow_save)
    app.router.add_get("/api/stats", stats)
    app.router.add_post("/api/segments", segments)
    app.router.add_post("/api/reply", reply)
    app.router.add_post("/api/close", close)
    app.router.add_post("/api/broadcast", broadcast)
    app.router.add_post("/api/broadcasts", broadcasts_list)
    return app


async def _run_broadcast(svc, bid: int, ids: list[int], text: str, photo: str = "") -> None:
    sent = blocked = 0
    safe = html.escape(text)
    for uid in ids:
        ch = svc.store.get_chat(uid)
        if not ch or ch.get("blocked_utc") or ch.get("opted_out_utc"):
            continue
        try:
            if photo:
                await svc.bot.send_photo(ch["chat_id"], photo, caption=safe[:1024])
            else:
                await svc.bot.send_message(ch["chat_id"], safe)
            sent += 1
            svc.store.add_message(uid, "assistant", "[розсилка] " + text[:300])
            svc.store.funnel("broadcast_sent", uid, None, {"bid": bid})
        except TelegramForbiddenError:
            blocked += 1
            svc.store.update_chat(uid, blocked_utc=now_utc())
        except Exception as e:  # noqa: BLE001
            log.warning("broadcast %s to %s failed: %s", bid, uid, e)
        if sent % 25 == 0:
            svc.store.c.execute("UPDATE broadcasts SET sent=?, blocked=? WHERE id=?", (sent, blocked, bid))
        await asyncio.sleep(SEND_PAUSE)
    svc.store.c.execute("UPDATE broadcasts SET sent=?, blocked=?, state='done' WHERE id=?", (sent, blocked, bid))
    log.info("broadcast %s done: sent=%s blocked=%s of %s", bid, sent, blocked, len(ids))


async def run_api(svc) -> None:
    if not svc.cfg.api_port:
        log.info("web api disabled (API_PORT=0)")
        await asyncio.Event().wait()
        return
    app = make_app(svc)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", svc.cfg.api_port)
    await site.start()
    log.info("web api on 127.0.0.1:%s", svc.cfg.api_port)
    await asyncio.Event().wait()
