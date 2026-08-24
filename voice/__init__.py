"""Голосові Олі. Текст → mp3 (ElevenLabs напряму, якщо є sk_-ключ; інакше kie.ai проксі) → ogg/opus (ffmpeg) → кеш.

Тільки шаблонні фрази з ім'ям у кличному — без LLM. Генерується один раз на (фраза, ім'я), далі з кешу.
Ніколи не озвучуємо через відеомоделі (правило користувача).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
from pathlib import Path

import httpx

log = logging.getLogger("voice")

KIE_CREATE = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_INFO = "https://api.kie.ai/api/v1/jobs/recordInfo"
KIE_MODEL = "elevenlabs/text-to-speech-multilingual-v2"
DEFAULT_VOICE = "EkK5I93UQWFDigLMpZcX"   # жіночий, multilingual — перевірено на UA через kie

ELEVEN_TTS = "https://api.elevenlabs.io/v1/text-to-speech/{voice}"


class VoiceError(Exception):
    pass


class Voice:
    def __init__(self, cache_dir: str | Path, kie_key: str = "", eleven_key: str = "", voice_id: str = DEFAULT_VOICE,
                 enabled: bool = False, client: httpx.AsyncClient | None = None):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.kie_key = kie_key
        self.eleven_key = eleven_key if eleven_key.startswith("sk_") else ""
        self.voice_id = voice_id
        self.enabled = enabled and bool(self.kie_key or self.eleven_key) and shutil.which("ffmpeg") is not None
        self.http = client or httpx.AsyncClient(timeout=60)
        self._inflight: dict[str, asyncio.Task] = {}

    def key(self, text: str) -> str:
        return hashlib.sha1((self.voice_id + "|" + text).encode("utf-8")).hexdigest()[:20]

    def cached(self, text: str) -> Path | None:
        p = self.dir / f"{self.key(text)}.ogg"
        return p if p.exists() and p.stat().st_size > 1000 else None

    async def get(self, text: str, wait: bool = True) -> Path | None:
        """Готовий ogg або None. wait=False — запустити генерацію у фоні й не чекати."""
        if not self.enabled:
            return None
        p = self.cached(text)
        if p:
            return p
        k = self.key(text)
        task = self._inflight.get(k)
        if task is None:
            task = asyncio.create_task(self._generate(text))
            self._inflight[k] = task
            task.add_done_callback(lambda _t: self._inflight.pop(k, None))
        if not wait:
            return None
        try:
            return await task
        except Exception as e:  # noqa: BLE001
            log.warning("voice gen failed: %s", e)
            return None

    def prewarm(self, text: str) -> None:
        if self.enabled and not self.cached(text):
            asyncio.ensure_future(self.get(text, wait=False))

    async def _generate(self, text: str) -> Path:
        mp3 = self.dir / f"{self.key(text)}.mp3"
        ogg = self.dir / f"{self.key(text)}.ogg"
        if self.eleven_key:
            r = await self.http.post(ELEVEN_TTS.format(voice=self.voice_id), headers={"xi-api-key": self.eleven_key},
                                     json={"text": text, "model_id": "eleven_multilingual_v2",
                                           "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35}})
            r.raise_for_status()
            mp3.write_bytes(r.content)
        else:
            await self._kie(text, mp3)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-c:a", "libopus", "-b:a", "48k", "-vbr", "on",
            "-application", "voip", str(ogg))
        await proc.wait()
        if proc.returncode != 0 or not ogg.exists():
            raise VoiceError("ffmpeg failed")
        mp3.unlink(missing_ok=True)
        return ogg

    async def _kie(self, text: str, out: Path) -> None:
        h = {"Authorization": f"Bearer {self.kie_key}", "Content-Type": "application/json"}
        body = {"model": KIE_MODEL, "input": {"text": text, "voice": self.voice_id, "stability": 0.45,
                                               "similarity_boost": 0.8, "style": 0.35}}
        r = await self.http.post(KIE_CREATE, headers=h, json=body)
        r.raise_for_status()
        tid = ((r.json().get("data") or {}).get("taskId"))
        if not tid:
            raise VoiceError(f"kie createTask: {r.text[:200]}")
        for _ in range(40):
            await asyncio.sleep(4)
            info = await self.http.get(f"{KIE_INFO}?taskId={tid}", headers=h)
            d = (info.json().get("data") or {})
            state = d.get("state") or d.get("status")
            if state in ("success", "SUCCESS", "completed"):
                import json as _json
                res = d.get("resultJson") or d.get("response") or {}
                if isinstance(res, str):
                    res = _json.loads(res)
                urls = res.get("resultUrls") or res.get("result_urls") or []
                url = urls[0] if urls else res.get("url")
                if not url:
                    raise VoiceError("kie: no url")
                audio = await self.http.get(url, headers={"User-Agent": "Mozilla/5.0"})
                audio.raise_for_status()
                out.write_bytes(audio.content)
                return
            if state in ("fail", "FAIL", "failed"):
                raise VoiceError(f"kie failed: {d.get('failMsg')}")
        raise VoiceError("kie timeout")


# ---------- фрази (тільки шаблони) ----------
def phrase_greeting() -> str:
    return ("Вітаю! Це Оля з Олавіти. Зараз оформимо замовлення за хвилину — платити наперед нічого не треба, "
            "оглянете на пошті і тільки тоді заплатите. Натисніть кнопочку, щоб надіслати номер.")


def phrase_thanks(addr: str) -> str:
    a = f", {addr}" if addr else ""
    return f"Дякую{a}! Замовлення прийняла, збираємо посилку. Щойно поїде — напишу сюди номер накладної. Гарного дня!"


def phrase_arrived(addr: str) -> str:
    a = f"{addr}, " if addr else ""
    return f"{a}посилка вже у відділенні! Назвіть на касі номер телефону, попросіть відкрити, огляньте — і тільки тоді платіть. Чекаю на ваші враження!"


def phrase_week(addr: str) -> str:
    a = f"{addr}, " if addr else ""
    return f"{a}минув тиждень — як вам сироватка? Якщо шкіра сухувата, наносьте її під свій крем. Напишіть, як враження, мені дуже цікаво!"


def phrase_nudge(addr: str) -> str:
    a = f"{addr}, " if addr else ""
    return f"{a}це Оля. Бачу, ви не дооформили замовлення — нічого страшного. Платити наперед не треба, оглянете на пошті. Якщо зручно, допишемо зараз, це одна хвилина."
