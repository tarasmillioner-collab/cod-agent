"""Фейки для тестов: NP, LP-CRM, Telegram-бот, конфиг, сборка Services."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import db
from clients.claude import FakeClaude, LLMTurn
from config import Config
from core.agent import Agent
from core.guards import Blacklist, Guards
from core.offer import load_offer
from core.services import Services
from core.store import Store

ROOT = Path(__file__).resolve().parent.parent

CITIES = {
    "київ": [{"ref": "c-kyiv", "name": "Київ", "area": "Київська", "region": "", "present": "м. Київ", "warehouses": 500}],
    "бровари": [{"ref": "c-brov", "name": "Бровари", "area": "Київська", "region": "", "present": "м. Бровари, Київська обл.", "warehouses": 30}],
    "дн": [{"ref": "c-dnipro", "name": "Дніпро", "area": "", "region": "", "present": "м. Дніпро", "warehouses": 200},
           {"ref": "c-dnipror", "name": "Дніпрорудне", "area": "", "region": "", "present": "м. Дніпрорудне", "warehouses": 3}],
}
WAREHOUSES = {
    "c-kyiv": [
        {"ref": "w1", "number": "1", "desc": "Відділення №1: вул. Пирогівський шлях, 135", "short": "", "postomat": False, "max_kg": "30"},
        {"ref": "w12", "number": "12", "desc": "Відділення №12: вул. Шевченка, 5", "short": "", "postomat": False, "max_kg": "30"},
        {"ref": "p7", "number": "7", "desc": "Поштомат №7: вул. Хрещатик, 1", "short": "", "postomat": True, "max_kg": "20"},
    ],
    "c-brov": [{"ref": "wb1", "number": "1", "desc": "Відділення №1: вул. Київська, 10", "short": "", "postomat": False, "max_kg": "30"}],
}


class FakeNP:
    def __init__(self, store=None):
        self.tracking: dict[str, dict] = {}
        self.fail = False

    async def search_cities(self, q, limit=5):
        if self.fail:
            raise RuntimeError("NP down")
        q = q.strip().lower()
        for k, v in CITIES.items():
            if q.startswith(k) or k.startswith(q):
                return v[:limit]
        return []

    async def city_by_ref(self, ref):
        for v in CITIES.values():
            for c in v:
                if c["ref"] == ref:
                    return c
        return None

    async def warehouses(self, city_ref, q="", limit=6, postomat=None):
        items = WAREHOUSES.get(city_ref, [])
        if postomat is not None:
            items = [w for w in items if w["postomat"] == postomat]
        q = q.strip().lower().replace("№", "")
        if q:
            if q.isdigit():
                exact = [w for w in items if w["number"] == q]
                if exact:
                    return exact[:limit]
            items = [w for w in items if q in w["desc"].lower()]
        return items[:limit]

    async def reverse_city(self, lat, lon):
        return "Київ" if abs(lat - 50.45) < 1 else None

    async def nearest(self, city_ref, lat, lon, limit=3, postomat=False):
        ws = [w for w in WAREHOUSES.get(city_ref, []) if not w["postomat"]]
        return [{**w, "dist_m": 300 * (i + 1)} for i, w in enumerate(ws[:limit])]

    async def warehouse_by_ref(self, city_ref, ref):
        for w in WAREHOUSES.get(city_ref, []):
            if w["ref"] == ref:
                return w
        return None

    async def track(self, ttns):
        return {t: self.tracking[t] for t in ttns if t in self.tracking}


class FakeLPCRM:
    def __init__(self, mode="ok"):
        self.mode = mode          # ok | down
        self.dry_run = False
        self.created: list[dict] = []
        self.orders: dict[str, dict] = {}

    async def add_order(self, **kw):
        if self.mode == "down":
            raise RuntimeError("LP-CRM 500")
        self.created.append(kw)
        self.orders[kw["order_id"]] = {"order_id": kw["order_id"], "status": kw.get("status") or "3", "ttn": ""}
        return {"status": "ok", "order_id": kw["order_id"]}

    async def orders_by_ids(self, ids):
        return {i: self.orders[i] for i in ids if i in self.orders}


class FakeBot:
    def __init__(self):
        self.sent: list[dict] = []
        self.topics = 0

    async def send_message(self, chat_id, text, reply_markup=None, message_thread_id=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, "kb": reply_markup, "thread": message_thread_id})
        return SimpleNamespace(message_id=len(self.sent))

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": caption or "", "kb": reply_markup, "thread": None, "photo": True})
        return SimpleNamespace(message_id=len(self.sent), photo=[SimpleNamespace(file_id="fid1")])

    async def create_forum_topic(self, chat_id, name):
        self.topics += 1
        return SimpleNamespace(message_thread_id=100 + self.topics)

    def texts(self, chat_id=None):
        return [s["text"] for s in self.sent if chat_id is None or s["chat_id"] == chat_id]

    def last(self):
        return self.sent[-1] if self.sent else None


def make_cfg(**over) -> Config:
    base = dict(env="test", bot_token="t", admin_ids=(1,), managers_chat_id=-100, anthropic_api_key="k", claude_oauth_token="",
                claude_model="fake", lpcrm_subdomain="x", lpcrm_api_key="y", lpcrm_api_key_in="z", lpcrm_dry_run=False,
                lpcrm_site="example.com", lpcrm_office="13", lpcrm_status_confirmed="11",
                np_api_key="", db_path=":memory:", offer_path=str(ROOT / "offer.yaml"),
                prompt_path=str(ROOT / "prompts/system.md"), blacklist_path=str(ROOT / "ua_blacklist.txt"),
                llm_daily_usd_cap=15.0, voice_enabled=False, elevenlabs_api_key="", kie_api_key="", manager_name="Наталя",
                admin_api_key="testkey", api_port=0, base_dir=ROOT)
    base.update(over)
    return Config(**base)


def make_services(llm_turns: list[LLMTurn] | None = None, lpcrm_mode="ok", variant: str = "A", **cfg_over) -> Services:
    cfg = make_cfg(**cfg_over)
    conn = db.connect(":memory:")
    db.migrate(conn)
    store = Store(conn)
    offer = load_offer(cfg.offer_path)
    for k in list(offer.raw.get("variants", {})):      # тест детерміновано живе в одному варіанті
        if k != "_default":
            offer.raw["variants"][k]["enabled"] = (k == variant)
    guards = Guards(offer, Blacklist.load(cfg.blacklist_path))
    np = FakeNP()
    lpcrm = FakeLPCRM(lpcrm_mode)
    llm = FakeClaude(llm_turns or [])
    agent = Agent(llm, store, offer, guards, np, cfg.prompt_path)
    svc = Services(cfg=cfg, store=store, offer=offer, guards=guards, np=np, lpcrm=lpcrm, agent=agent, bot=FakeBot())
    from core import objections as OBJ
    svc.objections = OBJ.load(offer)
    svc.voice = None
    svc.llm = llm  # type: ignore[attr-defined]
    return svc


def turn(text: str = "", calls: list[tuple[str, dict]] | None = None) -> LLMTurn:
    tc = [{"id": f"t{i}", "name": n, "input": a} for i, (n, a) in enumerate(calls or [])]
    blocks = ([{"type": "text", "text": text}] if text else []) + [{"type": "tool_use", **c} for c in tc]
    return LLMTurn(text=text, tool_calls=tc, raw_content=[], stop_reason="tool_use" if tc else "end_turn",
                   in_tokens=10, out_tokens=5, usd=0.0001, blocks=blocks)


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)
