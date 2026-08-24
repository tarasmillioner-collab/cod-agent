"""LP-CRM API (tallside.lp-crm.biz). POST form-data на /api/<method>.html, поле key.

Подтверждено 2026-08-23 против реальной CRM: getStatuses, getOrdersIdByStatus,
getOrdersByID (multi-id через запятую; возвращает ttn/ttn_status/status),
getCategories, getProductsByCategory. addNewOrder — поля из чужих интеграций
(order_id, country, office, products[], bayer_name, phone, delivery, delivery_adress,
payment, comment, utm_*, additional_1..4, site). `status` в addNewOrder ИГНОРИРУЕТСЯ (проверено 2026-08-23: заказ приходит «Новий»);
products — urlencode(serialize()) как в PHP SDK, иначе total=0. editOrder существует (422 без нужных
параметров, документация только в кабинете).

Лимит 429 у nginx — между запросами держим паузу (min_gap).
DRY_RUN: addNewOrder логируется и возвращает фиктивный id.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import urllib.parse

import httpx

log = logging.getLogger("lpcrm")


def php_serialize(v) -> str:
    """LP-CRM приймає products як urlencode(serialize($arr)) — як у офіційному PHP SDK."""
    if isinstance(v, (list, tuple)):
        return "a:%d:{%s}" % (len(v), "".join("i:%d;%s" % (i, php_serialize(x)) for i, x in enumerate(v)))
    if isinstance(v, dict):
        return "a:%d:{%s}" % (len(v), "".join(php_serialize(str(k)) + php_serialize(x) for k, x in v.items()))
    if isinstance(v, bool):
        return "b:%d;" % v
    if isinstance(v, int):
        return "i:%d;" % v
    b = str(v).encode("utf-8")
    return 's:%d:"%s";' % (len(b), str(v))


class LPCRMError(Exception):
    pass


class LPCRM:
    def __init__(self, subdomain: str, api_key: str, dry_run: bool = True,
                 client: httpx.AsyncClient | None = None, min_gap: float = 3.0, api_key_in: str = ""):
        """api_key — «вихідний» ключ (читання: getOrdersByID...), api_key_in — «вхідний» (addNewOrder)."""
        self.base = f"https://{subdomain}.lp-crm.biz/api" if subdomain else ""
        self.key = api_key
        self.key_in = api_key_in or api_key
        self.dry_run = dry_run or not (subdomain and api_key)
        self.http = client or httpx.AsyncClient(timeout=25)
        self.min_gap = min_gap
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def _post(self, method: str, data: list[tuple[str, str]], key: str | None = None,
                    retry_after_send: bool = True) -> dict:
        key = key or self.key
        async with self._lock:
            wait = self.min_gap - (time.monotonic() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            last_err: Exception | None = None
            for attempt, delay in enumerate((0.5, 2.0, 8.0)):
                try:
                    r = await self.http.post(f"{self.base}/{method}.html", data=dict([("key", key), *data]))
                    self._last = time.monotonic()
                    if r.status_code == 429:
                        raise LPCRMError("429 rate limited")
                    r.raise_for_status()
                    txt = r.text.strip()
                    if not txt:
                        raise LPCRMError(f"{method}: empty response")
                    try:
                        js = r.json()
                    except json.JSONDecodeError as e:
                        raise LPCRMError(f"{method}: non-JSON: {txt[:120]}") from e
                    if js.get("status") != "ok":
                        raise LPCRMError(f"{method}: {js.get('message')}")
                    return js
                except (httpx.HTTPError, LPCRMError) as e:  # noqa: PERF203
                    last_err = e
                    log.warning("lpcrm %s attempt %d failed: %s", method, attempt + 1, e)
                    # для addNewOrder: после отправки тела (таймаут/5xx) НЕ повторяем — иначе дубли в CRM
                    if not retry_after_send and not isinstance(e, httpx.ConnectError) and "429" not in str(e):
                        break
                    await asyncio.sleep(delay)
            raise LPCRMError(str(last_err))

    async def get_statuses(self) -> dict[str, str]:
        js = await self._post("getStatuses", [])
        return js.get("data") or {}

    async def orders_by_status(self, status: str, date_start: str, date_end: str) -> list[str]:
        js = await self._post("getOrdersIdByStatus", [("status", status), ("date_start", date_start), ("date_end", date_end)])
        return list(js.get("data") or [])

    async def orders_by_ids(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        js = await self._post("getOrdersByID", [("order_id", ",".join(ids))])
        data = js.get("data") or {}
        if len(ids) == 1 and "order_id" in data:
            return {str(data["order_id"]): data}
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}

    async def products_netcost(self, category_id: str = "8") -> dict[str, float]:
        """{product_id: собівартість (price_enter)} з довідника товарів CRM."""
        js = await self._post("getProductsByCategory", [("category_id", category_id)])
        out: dict[str, float] = {}
        for p in js.get("data") or []:
            try:
                out[str(p["id"])] = float(p.get("price_enter") or 0)
            except (TypeError, ValueError):
                continue
        return out

    async def add_order(self, *, order_id: str, site: str, office: str, bayer_name: str, phone: str,
                        products: list[dict], delivery_id: str, delivery_adress: str, payment: str,
                        comment: str, utm: dict, status: str | None, additional: dict | None = None,
                        country: str = "UA") -> dict:
        """products: [{product_id, price, count}]. Возвращает {'status':'ok','order_id': ...}."""
        form: list[tuple[str, str]] = [
            ("order_id", order_id), ("country", country), ("office", office), ("site", site),
            ("bayer_name", bayer_name), ("phone", phone), ("delivery", delivery_id),
            ("delivery_adress", delivery_adress), ("payment", payment), ("comment", comment),
        ]
        prods = [{"product_id": str(p["product_id"]), "price": str(p["price"]), "count": str(p.get("count", 1))} for p in products]
        # перевірено 2026-08-23: лише так товари потрапляють у замовлення (total/products)
        form.append(("products", urllib.parse.quote(php_serialize(prods))))
        for k in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
            if utm.get(k):
                form.append((k, str(utm[k])[:250]))
        for k, v in (additional or {}).items():
            if v:
                form.append((k, str(v)[:250]))
        if status:
            form.append(("status", status))   # CRM ігнорує при створенні (перевірено) — лишаємо на випадок оновлення API
        if self.dry_run:
            log.info("LPCRM DRY_RUN addNewOrder %s", json.dumps(dict(form), ensure_ascii=False))
            return {"status": "ok", "order_id": order_id, "dry_run": True}
        js = await self._post("addNewOrder", form, key=self.key_in, retry_after_send=False)
        return js
