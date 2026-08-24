"""Персональний баннер апсейлу з ім'ям клієнтки — генерується у фоні (kie.ai nano-banana-2)
по реальних упаковках, поки клієнтка проходить кроки. Кеш var/cards/<ім'я>.jpg.
Якщо не встигли або помилка — хендлер бере загальний assets/cards/upsell.jpg."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger("pcard")

KIE_CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_INFO = "https://api.kie.ai/api/v1/jobs/recordInfo"
KIE_UPLOAD = "https://kieai.redpandaai.co/api/file-stream-upload"

PROMPT = ("Ultra-modern 2027 premium skincare ad, 4:3, minimalist: soft gradient background (ivory → pale sand), generous negative space, "
          "products floating with soft realistic shadows, one thin gold accent line, premium editorial feel. Typography: one clean modern geometric "
          "sans-serif, very large headline, tiny secondary line. Render ONLY these exact Ukrainian strings, nothing else: "
          "headline \"{name}, курс 60 днів\" ; price tag \"1 180 грн\" ; small line \"крем для очей — у подарунок\". "
          "Products: TWO identical serum bottles from reference 1 (labels exactly as reference) standing together on the right, and the eye cream jar "
          "from reference 2 slightly behind with a small elegant gold tag hanging from it.")


class PersonalCards:
    def __init__(self, cache_dir: str | Path, kie_key: str, ref_urls: list[str] | None = None, enabled: bool = True,
                 client: httpx.AsyncClient | None = None):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.key = kie_key
        self.refs = ref_urls or []
        self.enabled = enabled
        self.http = client or httpx.AsyncClient(timeout=60)
        self._inflight: dict[str, asyncio.Task] = {}

    def path_for(self, addr: str) -> Path:
        return self.dir / (hashlib.sha1(addr.encode()).hexdigest()[:12] + ".jpg")

    def cached(self, addr: str) -> Path | None:
        p = self.path_for(addr)
        return p if p.exists() and p.stat().st_size > 20_000 else None

    def prewarm(self, addr: str) -> None:
        """Локальний рендер (Pillow) — миттєво, без API. kie-генерація лишена як резерв (_generate)."""
        if not addr or self.cached(addr):
            return
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from assets.build_upsell import main as render
            render(name=addr, out=self.path_for(addr))
        except Exception as e:  # noqa: BLE001
            log.warning("personal card render failed: %s", e)

    async def _generate(self, addr: str) -> Path:
        h = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        body = {"model": "nano-banana-2", "input": {"prompt": PROMPT.format(name=addr), "image_input": self.refs,
                                                   "aspect_ratio": "4:3", "resolution": "1K", "output_format": "jpg"}}
        r = await self.http.post(KIE_CREATE, headers=h, json=body)
        r.raise_for_status()
        tid = (r.json().get("data") or {}).get("taskId")
        if not tid:
            raise RuntimeError(f"kie createTask: {r.text[:150]}")
        for _ in range(30):
            await asyncio.sleep(5)
            d = (await self.http.get(f"{KIE_INFO}?taskId={tid}", headers=h)).json().get("data") or {}
            st = d.get("state")
            if st == "success":
                res = d.get("resultJson") or {}
                if isinstance(res, str):
                    res = json.loads(res)
                url = (res.get("resultUrls") or [None])[0]
                if not url:
                    raise RuntimeError("no url")
                img = await self.http.get(url, headers={"User-Agent": "Mozilla/5.0"})
                img.raise_for_status()
                p = self.path_for(addr)
                p.write_bytes(img.content)
                log.info("personal card ready for %s", addr)
                return p
            if st == "fail":
                raise RuntimeError(f"kie fail: {d.get('failMsg')}")
        raise TimeoutError("kie timeout")
