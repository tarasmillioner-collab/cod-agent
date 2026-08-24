"""Резервні копії того, що ви правите з пульта — у git.

Кожна правка (текст бота, налаштування) робить окремий коміт з іменем того, хто її зробив,
і летить у приватний GitHub-репозиторій. Історія = хто, що і коли змінив, з можливістю відкату.

У git НЕ потрапляє база з клієнтами (телефони, переписки) — вона бекапиться окремо на сервері.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger("state")

README = """# cod-agent — стан агента

Тут лежить усе, що команда править з пульта. Кожен коміт — одна правка, автор коміта — той,
хто її зробив.

| файл | що це |
|---|---|
| `offer.yaml` | товар, ціни, набори, тексти трьох шкіл, банк заперечень |
| `texts.json` | фрази, змінені з пульта (вкладка «Сценарій») — перекривають offer.yaml |
| `settings.json` | налаштування: пуші, стан бота, собівартість із CRM |
| `log.csv` | журнал дій: хто, що і коли робив у пульті |

Бази з клієнтами тут немає навмисно — вона бекапиться на сервері (`/srv/backups/cod_agent`).

Відкотити правку: знайти коміт, скопіювати старий текст із `texts.json` і вставити в пульті.
"""


def _write(state_dir: Path, svc) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "README.md").write_text(README, encoding="utf-8")

    # offer.yaml — бойова копія
    try:
        shutil.copyfile(svc.cfg.offer_path, state_dir / "offer.yaml")
    except Exception as e:  # noqa: BLE001
        log.warning("offer copy failed: %s", e)

    # тексти, змінені з пульта
    from core import experiments as X
    (state_dir / "texts.json").write_text(
        json.dumps(X.overrides(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # налаштування (без секретів)
    keep = ("push_orders", "bot_enabled", "set_netcost")
    st = {k: svc.store.get_setting(k, "") for k in keep}
    (state_dir / "settings.json").write_text(
        json.dumps(st, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # журнал дій — без текстів листування (там можуть бути дані клієнтів)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["коли", "хто", "дія", "об'єкт"])
    for r in svc.store.c.execute(
            "SELECT ts_utc, actor, action, target FROM dash_log ORDER BY id DESC LIMIT 500").fetchall():
        w.writerow([r[0][:19].replace("T", " "), r[1], r[2], r[3] or ""])
    (state_dir / "log.csv").write_text(buf.getvalue(), encoding="utf-8")


async def _git(state_dir: Path, *args: str) -> tuple[int, str]:
    p = await asyncio.create_subprocess_exec(
        "git", "-C", str(state_dir), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await p.communicate()
    return p.returncode, (out or b"").decode()[:400]


async def snapshot(svc, actor: str = "Система", note: str = "щоденний зріз") -> bool:
    """Зібрати стан, закомітити від імені actor і запушити. Помилка не ламає роботу бота."""
    state_dir = Path(svc.cfg.base_dir) / "state"
    try:
        await asyncio.to_thread(_write, state_dir, svc)
        if not (state_dir / ".git").exists():
            log.info("state: git не налаштований (%s) — лише файли", state_dir)
            return False
        await _git(state_dir, "add", "-A")
        code, out = await _git(state_dir, "diff", "--cached", "--quiet")
        if code == 0:                                   # нічого не змінилось
            return True
        email = "bot@cod-agent.local"
        code, out = await _git(state_dir, "-c", f"user.name={actor}", "-c", f"user.email={email}",
                               "commit", "-m", note)
        if code != 0:
            log.warning("state commit failed: %s", out)
            return False
        code, out = await _git(state_dir, "push", "-q", "origin", "HEAD")
        if code != 0:
            log.warning("state push failed: %s", out)
            return False
        log.info("state: %s — %s", actor, note)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("state snapshot failed: %s", e)
        return False


def fire(svc, actor: str, note: str) -> None:
    """Не блокуємо відповідь пульта — комітимо у фоні."""
    try:
        asyncio.create_task(snapshot(svc, actor, note))
    except RuntimeError:
        pass
