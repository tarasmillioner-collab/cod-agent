"""Пост-фильтры ответа LLM. Код решает, что можно отправить клиенту.

check(text) -> GuardResult: ok / fixed (автозамена) / blocked (с причиной).
Правила:
  price     — любое число рядом с «грн» обязано быть из offer.prices
  date      — дни недели / «завтра буде» / конкретные даты — запрещены
  claims    — offer.forbidden_claims
  scam      — таймеры, «залишилось N», промокоды, предоплата, картка
  blacklist — ua_blacklist.txt: RU-термины автозаменяются, MT → блок, regex [ыэёъ] / +7 / ₽ → блок
  length    — > max_chars → блок (LLM перепишет короче)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from core.offer import Offer

_WEEKDAYS = r"(понеділ|вівтор|серед[аиу]\b|четвер|п['’]ятниц|субот|неділ[яюі])"
_DATE_PROMISE = re.compile(
    rf"(\b{_WEEKDAYS}|завтра\s+(буде|прийде|отримаєте|приїде)|післязавтра|\b\d{{1,2}}[./]\d{{1,2}}(\.\d{{2,4}})?\b)",
    re.IGNORECASE,
)
_SCAM = re.compile(
    r"(залишил[оа]с[ья]\s+\d+|останн[ійя]{1,2}\s+шанс|таймер|промокод|промо-код|передоплат|передплат|"
    r"номер\s+карт|реквізит|бронюванн|забронюв|акція\s+діє\s+до|знижка\s+згора|до кінця дня|лише сьогодні)",
    re.IGNORECASE,
)
_PRICE = re.compile(r"(\d[\d\s ]{0,6}\d|\d)(?:[,.]\d{2})?\s*(грн|₴|гривень|гривні|uah|грив)", re.IGNORECASE)
_PRICE_CTX = re.compile(r"(ціна|кошту|всього|разом|сума|до сплати)\D{0,15}?(\d[\d\s ]{1,5}\d)", re.IGNORECASE)
_RU_CHARS = re.compile(r"[ыэёъЫЭЁЪ]")
_RU_PHONE = re.compile(r"\+7\b|₽")


@dataclass
class GuardResult:
    ok: bool
    text: str
    reasons: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)


@dataclass
class Blacklist:
    ru: dict[str, str]      # термин -> замена
    mt: list[str]
    pur: list[str]

    @classmethod
    def load(cls, path: str | Path) -> "Blacklist":
        ru: dict[str, str] = {}
        mt: list[str] = []
        pur: list[str] = []
        p = Path(path)
        if not p.is_file():
            return cls(ru, mt, pur)
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "|" not in line:
                continue
            parts = [x.strip() for x in line.split("|")]
            if len(parts) < 3:
                continue
            term, repl, cls_ = parts[0], parts[1], parts[2].upper()
            term = re.sub(r"\s*\(.*?\)\s*", "", term).strip()   # «любий (у знач. будь-який)» → «любий»
            if term.startswith("REGEX") or not term:
                continue
            if cls_ == "RU":
                ru[term.lower()] = repl
            elif cls_ == "MT":
                mt.append(term.lower())
            elif cls_ == "PUR":
                pur.append(term.lower())
        return cls(ru, mt, pur)


def _norm_num(s: str) -> int:
    return int(re.sub(r"[\s ]", "", s))


class Guards:
    def __init__(self, offer: Offer, blacklist: Blacklist):
        self.offer = offer
        self.bl = blacklist
        self.max_chars = int(offer.voice.get("max_chars", 350))
        self._claims = [re.compile(re.escape(c), re.IGNORECASE) for c in offer.forbidden_claims]

    def allowed_amounts(self, extra: set[int] | None = None) -> set[int]:
        return self.offer.prices | (extra or set())

    def check(self, text: str, extra_amounts: set[int] | None = None, allow_long: bool = False) -> GuardResult:
        reasons: list[str] = []
        fixed: list[str] = []
        out = text

        # 1. цены
        allowed = self.allowed_amounts(extra_amounts)
        for m in list(_PRICE.finditer(out)) + list(_PRICE_CTX.finditer(out)):
            try:
                n = _norm_num(m.group(1) if m.re is _PRICE else m.group(2))
            except ValueError:
                continue
            if n not in allowed:
                reasons.append(f"price:{n}")

        # 2. даты/обещания дня
        if _DATE_PROMISE.search(out):
            reasons.append("date_promise")

        # 3. запрещённые клеймы
        for rx in self._claims:
            if rx.search(out):
                reasons.append(f"claim:{rx.pattern}")

        # 4. скам-маркеры
        m = _SCAM.search(out)
        if m:
            reasons.append(f"scam:{m.group(0)}")

        # 5. язык
        if _RU_CHARS.search(out) or _RU_PHONE.search(out):
            reasons.append("ru_chars")
        low = out.lower()
        for term, repl in self.bl.ru.items():
            rx = re.compile(rf"(?<![\w'’]){re.escape(term)}(?![\w'’])", re.IGNORECASE)
            if rx.search(out):
                if repl:
                    out = rx.sub(repl, out)
                    fixed.append(f"{term}->{repl}")
                else:
                    reasons.append(f"ru:{term}")
        for term in self.bl.mt:
            if term in low:
                reasons.append(f"mt:{term}")

        # 6. длина
        if not allow_long and len(out) > self.max_chars:
            reasons.append(f"too_long:{len(out)}")

        return GuardResult(ok=not reasons, text=out, reasons=reasons, fixed=fixed)


def detect_russian(text: str) -> bool:
    """Клиент пишет по-русски? (для lang_hint; отвечаем всё равно украинским)."""
    if _RU_CHARS.search(text):
        return True
    words = re.findall(r"[а-яіїєґ']+", text.lower())
    ru_markers = {"что", "это", "как", "где", "когда", "сколько", "можно", "хочу", "нужно", "если", "или", "есть", "у", "ещё", "еще"}
    return sum(1 for w in words if w in ru_markers) >= 2
