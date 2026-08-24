"""Весь SQL в одном месте. Синхронный sqlite3 — один процесс-писатель, нагрузка
300 лидов/день; вызовы короткие, event loop не блокируют заметно."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from core import state as S
from db import now_utc


class TransitionError(Exception):
    pass


def _j(d: Any) -> str:
    return json.dumps(d, ensure_ascii=False)


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.c = conn

    # ---------- settings ----------
    def get_setting(self, key: str, default: str = "") -> str:
        r = self.c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_setting(self, key: str, value: str) -> None:
        self.c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def bot_enabled(self) -> bool:
        return self.get_setting("bot_enabled", "1") == "1"

    # ---------- chats ----------
    def upsert_chat(self, tg_user_id: int, chat_id: int, username: str | None, first_name: str | None,
                    utm: dict | None = None, start_payload: str | None = None) -> dict:
        now = now_utc()
        self.c.execute(
            """INSERT INTO chats(tg_user_id, chat_id, username, first_name, utm_json, start_payload, created_utc, last_seen_utc)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(tg_user_id) DO UPDATE SET chat_id=excluded.chat_id, username=excluded.username,
                 first_name=excluded.first_name, last_seen_utc=excluded.last_seen_utc,
                 utm_json=CASE WHEN excluded.utm_json!='{}' THEN excluded.utm_json ELSE chats.utm_json END,
                 start_payload=COALESCE(excluded.start_payload, chats.start_payload)""",
            (tg_user_id, chat_id, username, first_name, _j(utm or {}), start_payload, now, now),
        )
        return self.get_chat(tg_user_id)  # type: ignore[return-value]

    def get_chat(self, tg_user_id: int) -> dict | None:
        r = _row(self.c.execute("SELECT * FROM chats WHERE tg_user_id=?", (tg_user_id,)).fetchone())
        if r:
            r["utm"] = json.loads(r["utm_json"] or "{}")
            r["flags"] = json.loads(r["flags_json"] or "{}")
        return r

    def chat_by_topic(self, topic_id: int) -> dict | None:
        r = self.c.execute("SELECT tg_user_id FROM chats WHERE topic_id=?", (topic_id,)).fetchone()
        return self.get_chat(r[0]) if r else None

    def update_chat(self, tg_user_id: int, **fields: Any) -> None:
        if "flags" in fields:
            fields["flags_json"] = _j(fields.pop("flags"))
        cols = ", ".join(f"{k}=?" for k in fields)
        self.c.execute(f"UPDATE chats SET {cols} WHERE tg_user_id=?", (*fields.values(), tg_user_id))

    def touch_chat(self, tg_user_id: int, bot: bool = False) -> None:
        col = "last_bot_utc" if bot else "last_seen_utc"
        self.c.execute(f"UPDATE chats SET {col}=? WHERE tg_user_id=?", (now_utc(), tg_user_id))

    def set_flag(self, tg_user_id: int, key: str, value: Any = True) -> dict:
        ch = self.get_chat(tg_user_id) or {}
        flags = ch.get("flags", {})
        flags[key] = value
        self.update_chat(tg_user_id, flags=flags)
        return flags

    # ---------- orders ----------
    def active_order(self, chat_id: int) -> dict | None:
        r = self.c.execute(
            f"SELECT * FROM orders WHERE chat_id=? AND stage NOT IN {S.in_stages(S.TERMINAL)} ORDER BY id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
        return self._order(r)

    def get_order(self, order_id: int) -> dict | None:
        return self._order(self.c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone())

    def _order(self, r: sqlite3.Row | None) -> dict | None:
        d = _row(r)
        if d:
            d["utm"] = json.loads(d["utm_json"] or "{}")
        return d

    def create_order(self, chat_id: int, set_code: str | None, price_uah: int | None, utm: dict | None,
                     phone: str | None = None, name: str | None = None) -> dict:
        now = now_utc()
        ch = self.get_chat(chat_id) or {}
        cur = self.c.execute(
            """INSERT INTO orders(chat_id, stage, set_code, price_uah, phone, name, utm_json, created_utc, updated_utc, variant, offer_slug)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (chat_id, S.NEW, set_code, price_uah, phone, name, _j(utm or {}), now, now, ch.get("variant"), ch.get("offer_slug")),
        )
        order = self.get_order(cur.lastrowid)  # type: ignore[arg-type]
        self.event(order["id"], "created", meta={"set_code": set_code})
        return order  # type: ignore[return-value]

    def update_order(self, order_id: int, **fields: Any) -> dict:
        fields["updated_utc"] = now_utc()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.c.execute(f"UPDATE orders SET {cols} WHERE id=?", (*fields.values(), order_id))
        return self.get_order(order_id)  # type: ignore[return-value]

    def transition(self, order_id: int, to: str, event: str | None = None, meta: dict | None = None,
                   **fields: Any) -> dict:
        """Единственный способ сменить стадию. Атомарно: UPDATE + order_events."""
        order = self.get_order(order_id)
        if not order:
            raise TransitionError(f"order {order_id} not found")
        frm = order["stage"]
        if frm == to:
            return self.update_order(order_id, **fields) if fields else order
        if not S.allowed(frm, to):
            raise TransitionError(f"order {order_id}: {frm} -> {to} not allowed")
        stamp = {S.CONFIRMED: "confirmed_utc", S.SHIPPED: "shipped_utc", S.ARRIVED: "arrived_utc",
                 S.PICKED: "picked_utc", S.DONE: "closed_utc", S.CANCELLED: "closed_utc", S.RETURNED: "closed_utc"}
        if to in stamp and not order.get(stamp[to]):
            fields[stamp[to]] = now_utc()
        self.c.execute("BEGIN")
        try:
            self.update_order(order_id, stage=to, **fields)
            self.event(order_id, event or f"stage:{to}", meta={"from": frm, "to": to, **(meta or {})})
            self.c.execute("COMMIT")
        except Exception:
            self.c.execute("ROLLBACK")
            raise
        return self.get_order(order_id)  # type: ignore[return-value]

    def orders_in(self, stages: tuple[str, ...] | list[str]) -> list[dict]:
        rows = self.c.execute(f"SELECT * FROM orders WHERE stage IN {S.in_stages(stages)} ORDER BY id").fetchall()
        return [self._order(r) for r in rows]  # type: ignore[misc]

    def last_shipped_order(self, chat_id: int) -> dict | None:
        """Останнє замовлення з адресою (для повтору у 2 тапи)."""
        r = self.c.execute(
            "SELECT * FROM orders WHERE chat_id=? AND np_wh_ref IS NOT NULL AND name IS NOT NULL AND phone IS NOT NULL "
            "AND stage IN ('confirmed_crm','shipped','arrived','picked','done') ORDER BY id DESC LIMIT 1", (chat_id,)).fetchone()
        return self._order(r)

    def recent_order_by_phone(self, phone: str, hours: int = 72) -> dict | None:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        r = self.c.execute(
            f"SELECT * FROM orders WHERE phone=? AND created_utc>=? AND stage NOT IN {S.in_stages((S.CANCELLED,))} ORDER BY id DESC LIMIT 1",
            (phone, since),
        ).fetchone()
        return self._order(r)

    # ---------- events ----------
    def event(self, order_id: int, name: str, dedup_key: str = "", meta: dict | None = None) -> bool:
        """True если событие записано впервые (идемпотентность по (order,name,dedup))."""
        cur = self.c.execute(
            "INSERT OR IGNORE INTO order_events(order_id, name, dedup_key, ts_utc, meta_json) VALUES(?,?,?,?,?)",
            (order_id, name, dedup_key, now_utc(), _j(meta or {})),
        )
        return cur.rowcount == 1

    def has_event(self, order_id: int, name: str, dedup_key: str = "") -> bool:
        return self.c.execute(
            "SELECT 1 FROM order_events WHERE order_id=? AND name=? AND dedup_key=?", (order_id, name, dedup_key)
        ).fetchone() is not None

    # ---------- messages ----------
    def add_message(self, chat_id: int, role: str, content: str, tool: dict | None = None,
                    tg_message_id: int | None = None) -> None:
        self.c.execute(
            "INSERT INTO messages(chat_id, role, content, tool_json, ts_utc, tg_message_id) VALUES(?,?,?,?,?,?)",
            (chat_id, role, content, _j(tool) if tool else None, now_utc(), tg_message_id),
        )

    def history(self, chat_id: int, limit: int = 20) -> list[dict]:
        rows = self.c.execute(
            "SELECT role, content, tool_json, ts_utc FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ---------- handoffs ----------
    def open_handoff(self, chat_id: int, order_id: int | None, topic_id: int | None, reason: str) -> dict:
        self.c.execute(
            "INSERT OR IGNORE INTO handoffs(chat_id, order_id, topic_id, reason, opened_utc) VALUES(?,?,?,?,?)",
            (chat_id, order_id, topic_id, reason, now_utc()),
        )
        return self.open_handoff_for(chat_id)  # type: ignore[return-value]

    def open_handoff_for(self, chat_id: int) -> dict | None:
        return _row(self.c.execute("SELECT * FROM handoffs WHERE chat_id=? AND state='open'", (chat_id,)).fetchone())

    def close_handoff(self, chat_id: int) -> None:
        self.c.execute("UPDATE handoffs SET state='closed', closed_utc=? WHERE chat_id=? AND state='open'",
                       (now_utc(), chat_id))

    # ---------- outbox ----------
    def enqueue(self, kind: str, ref_id: str, payload: dict, delay_sec: int = 0) -> bool:
        nt = (datetime.now(timezone.utc) + timedelta(seconds=delay_sec)).replace(microsecond=0).isoformat()
        cur = self.c.execute(
            "INSERT OR IGNORE INTO outbox(kind, ref_id, payload_json, next_try_utc, created_utc) VALUES(?,?,?,?,?)",
            (kind, ref_id, _j(payload), nt, now_utc()),
        )
        return cur.rowcount == 1

    def due_outbox(self, limit: int = 50) -> list[dict]:
        rows = self.c.execute(
            "SELECT * FROM outbox WHERE state='pending' AND next_try_utc<=? ORDER BY id LIMIT ?", (now_utc(), limit)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload_json"])
            out.append(d)
        return out

    def outbox_done(self, oid: int) -> None:
        self.c.execute("UPDATE outbox SET state='done', done_utc=? WHERE id=?", (now_utc(), oid))

    def outbox_retry(self, oid: int, error: str, backoff_sec: int, give_up_after: int) -> str:
        r = self.c.execute("SELECT attempts FROM outbox WHERE id=?", (oid,)).fetchone()
        attempts = (r[0] if r else 0) + 1
        if attempts >= give_up_after:
            self.c.execute("UPDATE outbox SET state='failed', attempts=?, last_error=? WHERE id=?", (attempts, error[:500], oid))
            return "failed"
        nt = (datetime.now(timezone.utc) + timedelta(seconds=backoff_sec)).replace(microsecond=0).isoformat()
        self.c.execute("UPDATE outbox SET attempts=?, last_error=?, next_try_utc=? WHERE id=?",
                       (attempts, error[:500], nt, oid))
        return "retry"

    def outbox_fail(self, oid: int, error: str) -> None:
        self.c.execute("UPDATE outbox SET state='failed', last_error=? WHERE id=?", (error[:500], oid))

    # ---------- np cache ----------
    def cache_get(self, kind: str, key: str, ttl_sec: int) -> Any | None:
        r = self.c.execute("SELECT json, fetched_utc FROM np_cache WHERE kind=? AND key=?", (kind, key)).fetchone()
        if not r:
            return None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(r[1])
        if age.total_seconds() > ttl_sec:
            return None
        return json.loads(r[0])

    def cache_put(self, kind: str, key: str, value: Any) -> None:
        self.c.execute(
            "INSERT INTO np_cache(kind,key,json,fetched_utc) VALUES(?,?,?,?) ON CONFLICT(kind,key) DO UPDATE SET json=excluded.json, fetched_utc=excluded.fetched_utc",
            (kind, key, _j(value), now_utc()),
        )

    # ---------- usage / funnel ----------
    def log_usage(self, chat_id: int | None, model: str, in_tokens: int, out_tokens: int, usd: float) -> None:
        self.c.execute("INSERT INTO llm_usage(ts_utc, chat_id, model, in_tokens, out_tokens, usd) VALUES(?,?,?,?,?,?)",
                       (now_utc(), chat_id, model, in_tokens, out_tokens, usd))

    def usage_today_usd(self) -> float:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = self.c.execute("SELECT COALESCE(SUM(usd),0) FROM llm_usage WHERE ts_utc LIKE ?", (day + "%",)).fetchone()
        return float(r[0])

    def funnel(self, name: str, chat_id: int | None = None, order_id: int | None = None, meta: dict | None = None) -> None:
        variant = None
        if chat_id is not None:
            r = self.c.execute("SELECT variant FROM chats WHERE tg_user_id=?", (chat_id,)).fetchone()
            variant = r[0] if r else None
        self.c.execute("INSERT INTO funnel_events(ts_utc, chat_id, order_id, name, meta_json, variant) VALUES(?,?,?,?,?,?)",
                       (now_utc(), chat_id, order_id, name, _j(meta or {}), variant))

    def funnel_counts(self, since_utc: str) -> dict[str, int]:
        rows = self.c.execute(
            "SELECT name, COUNT(DISTINCT COALESCE(chat_id, id)) FROM funnel_events WHERE ts_utc>=? GROUP BY name",
            (since_utc,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}
