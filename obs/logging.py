"""JSON-логи в stdout → journald."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "lvl": record.levelname,
            "log": record.name,
            "msg": record.getMessage(),
        }
        for k in ("chat_id", "order_id", "stage", "tool", "latency_ms"):
            if hasattr(record, k):
                d[k] = getattr(record, k)
        if record.exc_info:
            d["exc"] = self.formatException(record.exc_info)[-1500:]
        return json.dumps(d, ensure_ascii=False)


def setup(level: str = "INFO") -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel("WARNING")
    logging.getLogger("aiogram").setLevel("WARNING")
