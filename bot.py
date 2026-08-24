"""cod-agent entrypoint: config → db → services → polling + scheduler в одном процессе."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

import db
from clients.claude import ClaudeClient
from clients.lpcrm import LPCRM
from clients.novaposhta import NovaPoshta
from config import ConfigError, load_config
from core import scheduler
from core.agent import Agent
from core.guards import Blacklist, Guards
from core.offer import load_offer
from core.services import Services
from core.store import Store
from obs import logging as jlog
from tg import handlers_admin, handlers_client

log = logging.getLogger("bot")


def build_services(env_path: str = "config.env") -> Services:
    cfg = load_config(env_path)
    if cfg.env == "prod" and not os.environ.get("COD_AGENT_PROD_OK"):
        # защита «один токен — один поллер»: прод запускается только под systemd (ставит переменную)
        raise ConfigError("ENV=prod: запуск вне systemd запрещён (COD_AGENT_PROD_OK не задан)")
    conn = db.connect(cfg.db_path)
    db.migrate(conn)
    store = Store(conn)
    offer = load_offer(cfg.offer_path)
    import json as _json
    from core import experiments as _X
    try:
        _X.set_overrides(_json.loads(store.get_setting("copy_overrides") or "{}"))
    except Exception:  # noqa: BLE001
        pass
    guards = Guards(offer, Blacklist.load(cfg.blacklist_path))
    np = NovaPoshta(cfg.np_api_key, store)
    lpcrm = LPCRM(cfg.lpcrm_subdomain, cfg.lpcrm_api_key, dry_run=cfg.lpcrm_dry_run, api_key_in=cfg.lpcrm_api_key_in)
    if cfg.claude_oauth_token:
        from clients.claude_sdk import ClaudeSdkClient
        llm = ClaudeSdkClient(cfg.claude_oauth_token, cfg.claude_model, cwd=str(cfg.base_dir / "var"))
    elif cfg.anthropic_api_key and cfg.anthropic_api_key.upper() not in ("PLACEHOLDER", "PENDING-NO-KEY-YET"):
        llm = ClaudeClient(cfg.anthropic_api_key, cfg.claude_model)
    else:
        raise ConfigError("Потрібен CLAUDE_CODE_OAUTH_TOKEN (підписка) або ANTHROPIC_API_KEY")
    agent = Agent(llm, store, offer, guards, np, cfg.prompt_path)
    from core import objections as OBJ
    from voice import Voice
    svc = Services(cfg=cfg, store=store, offer=offer, guards=guards, np=np, lpcrm=lpcrm, agent=agent)
    svc.objections = OBJ.load(offer)
    from core.personal_card import PersonalCards
    svc.pcards = PersonalCards(cfg.base_dir / "var" / "pcards", cfg.kie_api_key,
                               ref_urls=["https://olavita.skinactivelab.com/lp/assets/packshot.jpg",
                                         "https://olavita.skinactivelab.com/upsell/images/product-blue.png"],
                               enabled=True)
    svc.voice = Voice(cfg.base_dir / "var" / "voice", kie_key=cfg.kie_api_key, eleven_key=cfg.elevenlabs_api_key,
                      enabled=cfg.voice_enabled)
    return svc


async def main() -> None:
    jlog.setup(os.environ.get("LOG_LEVEL", "INFO"))
    svc = build_services(os.environ.get("CONFIG_ENV", "config.env"))
    bot = Bot(svc.cfg.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    svc.bot = bot
    dp = Dispatcher()
    dp["svc"] = svc
    from tg.middleware import ChatLockMiddleware
    dp.message.middleware(ChatLockMiddleware())
    dp.callback_query.middleware(ChatLockMiddleware())
    dp.include_router(handlers_admin.router)
    dp.include_router(handlers_client.router)
    me = await bot.get_me()
    log.info("cod-agent up as @%s env=%s dry_run=%s", me.username, svc.cfg.env, svc.lpcrm.dry_run)
    await bot.delete_webhook(drop_pending_updates=False)
    try:
        from web.api import run_api
        tasks = [asyncio.create_task(dp.start_polling(bot, allowed_updates=["message", "callback_query"])),
                 asyncio.create_task(scheduler.run(svc)),
                 asyncio.create_task(run_api(svc))]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in pending:
            t.cancel()
        for t in done:
            if t.exception():
                log.error("fatal: %s", t.exception())
                raise SystemExit(1)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigError as e:
        print(f"CONFIG ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        pass
