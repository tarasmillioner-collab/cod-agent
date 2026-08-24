"""Конфиг cod-agent: config.env + переменные окружения (env главнее файла).

Секреты только здесь, никогда в коде. Относительные пути резолвятся от
каталога config.env — одинаково локально и под systemd (EnvironmentFile=).
Fail-fast: плейсхолдеры и пустые обязательные значения валят старт с
человекочитаемой ошибкой.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_PLACEHOLDERS = {"", "PLACEHOLDER", "CHANGEME", "YOUR_TOKEN", "XXX"}


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    env: str                      # prod | test
    bot_token: str
    admin_ids: tuple[int, ...]    # кто может /bot, /stats
    managers_chat_id: int         # супергруппа-форум менеджеров (0 = handoff выключен)
    anthropic_api_key: str
    claude_oauth_token: str
    claude_model: str
    lpcrm_subdomain: str
    lpcrm_api_key: str
    lpcrm_api_key_in: str
    lpcrm_dry_run: bool
    lpcrm_site: str               # поле `site` в addNewOrder
    lpcrm_office: str             # поле `office`
    lpcrm_status_confirmed: str   # id статуса «Прийнято»
    np_api_key: str
    db_path: str
    offer_path: str
    prompt_path: str
    blacklist_path: str
    llm_daily_usd_cap: float
    voice_enabled: bool
    elevenlabs_api_key: str
    kie_api_key: str
    manager_name: str
    admin_api_key: str
    admin_keys: dict
    api_port: int
    base_dir: Path = field(default_factory=Path)


def _parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{lineno}: ожидалась KEY=VALUE, получено {line!r}")
        k, _, v = line.partition("=")
        v = re.split(r"\s+#", v, 1)[0]
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def _parse_keys(raw: str, fallback: str) -> dict:
    """ADMIN_KEYS=тарас:код1,саша:код2 → {'код1': 'Тарас', 'код2': 'Саша'}; ADMIN_API_KEY лишається як «Власник»."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        name, _, key = part.partition(":")
        name, key = name.strip(), key.strip()
        if name and key:
            out[key] = name[:1].upper() + name[1:]
    if fallback:
        out.setdefault(fallback, "Власник")
    return out


def load_config(env_path: str | Path = "config.env") -> Config:
    env_path = Path(env_path)
    base = env_path.resolve().parent
    vals = _parse_env_file(env_path)

    def get(key: str, default: str = "") -> str:
        v = os.environ.get(key)
        if v is None or v == "":
            v = vals.get(key, default)
        return (v or "").strip()

    def req(key: str, hint: str) -> str:
        v = get(key)
        if v.upper() in _PLACEHOLDERS:
            raise ConfigError(f"{key} не задан. {hint}")
        return v

    def resolve(p: str) -> str:
        pp = Path(p)
        return str(pp if pp.is_absolute() else (base / pp).resolve())

    env = get("ENV", "test").lower()
    if env not in ("prod", "test"):
        raise ConfigError("ENV должен быть prod или test")

    dry = get("LPCRM_DRY_RUN", "1") not in ("0", "false", "no")
    admin_ids = tuple(int(x) for x in get("ADMIN_IDS", "").replace(";", ",").split(",") if x.strip())

    return Config(
        env=env,
        bot_token=req("BOT_TOKEN", "Токен от @BotFather: BOT_TOKEN=123:AA..."),
        admin_ids=admin_ids,
        managers_chat_id=int(get("MANAGERS_CHAT_ID", "0") or 0),
        anthropic_api_key=get("ANTHROPIC_API_KEY", ""),
        claude_oauth_token=get("CLAUDE_CODE_OAUTH_TOKEN", ""),
        claude_model=get("CLAUDE_MODEL", "claude-sonnet-5"),
        lpcrm_subdomain=get("LPCRM_SUBDOMAIN", ""),
        lpcrm_api_key=get("LPCRM_API_KEY", ""),
        lpcrm_api_key_in=get("LPCRM_API_KEY_IN", ""),
        lpcrm_dry_run=dry,
        lpcrm_site=get("LPCRM_SITE", ""),
        lpcrm_office=get("LPCRM_OFFICE", "13"),
        lpcrm_status_confirmed=get("LPCRM_STATUS_CONFIRMED", "11"),
        np_api_key=get("NP_API_KEY", ""),
        db_path=resolve(get("DB_PATH", "var/cod.db")),
        offer_path=resolve(get("OFFER_PATH", "offer.yaml")),
        prompt_path=resolve(get("PROMPT_PATH", "prompts/system.md")),
        blacklist_path=resolve(get("BLACKLIST_PATH", "ua_blacklist.txt")),
        llm_daily_usd_cap=float(get("LLM_DAILY_USD_CAP", "15")),
        voice_enabled=get("VOICE_ENABLED", "0") in ("1", "true", "yes"),
        elevenlabs_api_key=get("ELEVENLABS_API_KEY", ""),
        kie_api_key=get("KIE_API_KEY", ""),
        manager_name=get("MANAGER_NAME", ""),
        admin_api_key=get("ADMIN_API_KEY", ""),
        admin_keys=_parse_keys(get("ADMIN_KEYS", ""), get("ADMIN_API_KEY", "")),
        api_port=int(get("API_PORT", "7810") or 0),
        base_dir=base,
    )
