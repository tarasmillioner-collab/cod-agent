"""Нова Пошта API v2 — тонкий клиент (один POST) + кэш в SQLite.

Методы: search_cities(q), warehouses(city_ref, q), track(ttns).
Без apiKey работают только справочники (searchSettlements/getWarehouses
публичные); трекинг чужих ТТН тоже публичный, но с ключом лимиты выше.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import logging

log_np = logging.getLogger("np")
_NOMINATIM_LOCK = asyncio.Lock()

NP_URL = "https://api.novaposhta.ua/v2.0/json/"
CITY_TTL = 24 * 3600
WH_TTL = 24 * 3600

# TypeOfWarehouseRef: поштомати
POSTOMAT_MARK = ("поштомат", "postomat")


class NPError(Exception):
    pass


class NovaPoshta:
    def __init__(self, api_key: str, store, client: httpx.AsyncClient | None = None):
        self.key = api_key
        self.store = store
        self.http = client or httpx.AsyncClient(timeout=15)

    async def _call(self, model: str, method: str, props: dict[str, Any]) -> list[dict]:
        body = {"apiKey": self.key, "modelName": model, "calledMethod": method, "methodProperties": props}
        last: Exception | None = None
        for attempt in range(3):
            try:
                r = await self.http.post(NP_URL, json=body)
                r.raise_for_status()
                data = r.json()
                if not data.get("success"):
                    raise NPError("; ".join(data.get("errors") or ["unknown NP error"]))
                return data.get("data") or []
            except (httpx.HTTPError, NPError) as e:  # noqa: PERF203
                last = e
                await asyncio.sleep(0.5 * (attempt + 1))
        raise NPError(str(last))

    # ---------- cities ----------
    async def search_cities(self, q: str, limit: int = 5) -> list[dict]:
        q = q.strip()
        key = q.lower()
        cached = self.store.cache_get("city", key, CITY_TTL)
        if cached is not None:
            return cached[:limit]
        data = await self._call("Address", "searchSettlements", {"CityName": q, "Limit": "10", "Page": "1"})
        addrs = (data[0].get("Addresses") if data else []) or []
        out = []
        for a in addrs:
            ref = a.get("DeliveryCity") or a.get("Ref")
            if not ref:
                continue
            out.append({
                "ref": ref,
                "name": a.get("MainDescription", ""),
                "area": a.get("Area", ""),
                "region": a.get("Region", ""),
                "present": a.get("Present", ""),
                "warehouses": int(a.get("Warehouses") or 0),
            })
        self.store.cache_put("city", key, out)
        return out[:limit]

    async def city_by_ref(self, ref: str) -> dict | None:
        """Ищем ref среди закэшированных результатов поиска (set_city принимает только их)."""
        import json as _json
        for row in self.store.c.execute("SELECT json FROM np_cache WHERE kind='city'").fetchall():
            for c in _json.loads(row[0]):
                if c.get("ref") == ref:
                    return c
        return None

    # ---------- warehouses ----------
    async def warehouses(self, city_ref: str, q: str = "", limit: int = 6, postomat: bool | None = None) -> list[dict]:
        all_wh = self.store.cache_get("warehouse", city_ref, WH_TTL)
        if all_wh is None:
            data: list[dict] = []
            for page in range(1, 8):
                chunk = await self._call("Address", "getWarehouses", {"CityRef": city_ref, "Limit": "1000", "Page": str(page)})
                data += chunk
                if len(chunk) < 1000:
                    break
            all_wh = []
            for w in data:
                desc = w.get("Description", "")
                is_post = any(m in desc.lower() for m in POSTOMAT_MARK) or (w.get("CategoryOfWarehouse") == "Postomat")
                all_wh.append({
                    "ref": w.get("Ref"),
                    "number": str(w.get("Number", "")),
                    "desc": desc,
                    "short": w.get("ShortAddress", ""),
                    "postomat": is_post,
                    "max_kg": w.get("TotalMaxWeightAllowed") or w.get("PlaceMaxWeightAllowed") or "",
                    "lat": float(w.get("Latitude") or 0) or None,
                    "lon": float(w.get("Longitude") or 0) or None,
                })
            self.store.cache_put("warehouse", city_ref, all_wh)
        items = all_wh
        if postomat is not None:
            items = [w for w in items if w["postomat"] == postomat]
        q = q.strip().lower()
        if q:
            num = re.sub(r"\D", "", q)
            if num and num == q.replace("№", "").strip():
                return [w for w in items if w["number"] == num][:limit]
            items = [w for w in items if q in w["desc"].lower()]
        # поштомати «тільки для мешканців» — в конец списка
        items = sorted(items, key=lambda w: "мешканц" in w["desc"].lower())
        return items[:limit]

    async def nearest(self, city_ref: str, lat: float, lon: float, limit: int = 3, postomat: bool = False) -> list[dict]:
        """Найближчі відділення до точки (гаверсин), з відстанню у метрах."""
        import math
        out = []
        for w in await self.warehouses(city_ref, "", limit=10_000, postomat=postomat):
            if not (w.get("lat") and w.get("lon")):
                continue
            p1, p2 = math.radians(lat), math.radians(w["lat"])
            dphi, dl = math.radians(w["lat"] - lat), math.radians(w["lon"] - lon)
            a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
            d = 2 * 6371000 * math.asin(math.sqrt(a))
            out.append({**w, "dist_m": int(d)})
        out.sort(key=lambda w: w["dist_m"])
        return out[:limit]

    async def reverse_city(self, lat: float, lon: float) -> str | None:
        """Координати → назва населеного пункту (OSM Nominatim, безкоштовно, ≤1 rps)."""
        try:
            async with _NOMINATIM_LOCK:
                r = await self.http.get("https://nominatim.openstreetmap.org/reverse",
                                        params={"lat": lat, "lon": lon, "format": "json", "accept-language": "uk", "zoom": 10},
                                        headers={"User-Agent": "cod-agent/1.0 (olavita telegram bot)"}, timeout=6)
                await asyncio.sleep(1.0)   # політика Nominatim: ≤1 запит/с
            a = (r.json() or {}).get("address") or {}
            return a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("county")
        except Exception as e:  # noqa: BLE001
            log_np.warning("reverse geocode failed: %s", e)
            return None

    async def warehouse_by_ref(self, city_ref: str, ref: str) -> dict | None:
        for w in await self.warehouses(city_ref, limit=10_000, postomat=None):
            if w["ref"] == ref:
                return w
        return None

    # ---------- tracking ----------
    async def track(self, ttns: list[str]) -> dict[str, dict]:
        """{ttn: {code, text, warehouse, date}} батчами ≤100."""
        out: dict[str, dict] = {}
        for i in range(0, len(ttns), 100):
            chunk = ttns[i:i + 100]
            data = await self._call("TrackingDocument", "getStatusDocuments",
                                    {"Documents": [{"DocumentNumber": t, "Phone": ""} for t in chunk]})
            for d in data:
                out[d.get("Number", "")] = {
                    "code": str(d.get("StatusCode", "")),
                    "text": d.get("Status", ""),
                    "warehouse": d.get("WarehouseRecipient", ""),
                    "recipient_date": d.get("RecipientDateTime", ""),
                    "scheduled": d.get("ScheduledDeliveryDate", ""),
                    "actual_date": d.get("ActualDeliveryDate", ""),
                    "days_storage": d.get("DaysStorageCargo", ""),
                }
        return out
