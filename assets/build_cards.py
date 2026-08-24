"""Карточки наборов из РЕАЛЬНЫХ фото с сайта (assets/src) → assets/cards/*.jpg.
Запуск: python assets/build_cards.py. Цены берутся из offer.yaml — карточки не расходятся с офером."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets/src"
OUT = ROOT / "assets/cards"
OUT.mkdir(exist_ok=True)

W, H = 1200, 900
NAVY = (18, 28, 58)
GOLD = (214, 178, 94)
CREAM = (246, 241, 232)
INK = (30, 30, 34)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    cands = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for c in cands:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def fit(im: Image.Image, box: tuple[int, int]) -> Image.Image:
    im = im.convert("RGB")
    r = min(box[0] / im.width, box[1] / im.height)
    return im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)


def cover(im: Image.Image, box: tuple[int, int]) -> Image.Image:
    im = im.convert("RGB")
    r = max(box[0] / im.width, box[1] / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    x = (im.width - box[0]) // 2
    y = (im.height - box[1]) // 2
    return im.crop((x, y, x + box[0], y + box[1]))


def price(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " грн"


def strip(draw: ImageDraw.ImageDraw, y: int, title: str, sub: str, badge: str | None = None) -> None:
    draw.rectangle((0, y, W, H), fill=CREAM)
    draw.text((48, y + 26), title, font=font(44, True), fill=INK)
    draw.text((48, y + 90), sub, font=font(30), fill=(90, 90, 96))
    if badge:
        pill(draw, W - 48, 40, badge, right=True)


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, right: bool = False) -> None:
    f = font(26, True)
    tw = draw.textlength(text, font=f)
    bx = x - tw - 40 if right else x
    draw.rounded_rectangle((bx, y, bx + tw + 40, y + 54), radius=27, fill=GOLD)
    draw.text((bx + 20, y + 11), text, font=f, fill=NAVY)


def card_single(src: str, out: str, title: str, sub: str, badge: str | None = None) -> None:
    im = Image.new("RGB", (W, H), NAVY)
    photo = cover(Image.open(SRC / src), (W, 720))
    im.paste(photo, (0, 0))
    strip(ImageDraw.Draw(im), 720, title, sub, badge)
    im.save(OUT / out, quality=88)


def card_pair(src_a: str, src_b: str, out: str, title: str, sub: str, badge: str | None = None) -> None:
    im = Image.new("RGB", (W, H), NAVY)
    a = cover(Image.open(SRC / src_a), (W // 2, 720))
    b = cover(Image.open(SRC / src_b), (W // 2, 720))
    im.paste(a, (0, 0))
    im.paste(b, (W // 2, 0))
    d = ImageDraw.Draw(im)
    # «+» между фото
    d.ellipse((W // 2 - 44, 316, W // 2 + 44, 404), fill=GOLD)
    d.text((W // 2 - 19, 318), "+", font=font(64, True), fill=NAVY)
    strip(d, 720, title, sub, badge)
    im.save(OUT / out, quality=88)


def card(src: str, out: str, title: str, sub: str, badge: str | None = None) -> None:
    """Фото 1200×800 + світла смуга: назва, ціна, плашка «оплата на пошті · огляд до оплати»."""
    im = Image.new("RGB", (W, H), CREAM)
    photo = cover(Image.open(SRC / src), (W, 700))
    im.paste(photo, (0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 700, W, H), fill=CREAM)
    d.text((48, 722), title, font=font(46, True), fill=INK)
    d.text((48, 790), sub, font=font(30), fill=(90, 90, 96))
    pill(d, 48, 840, "оплата на пошті · огляд до оплати")
    if badge:
        pill(d, W - 48, 40, badge, right=True)
    im.save(OUT / out, quality=90)


def main() -> None:
    global H
    H = 900
    offer = yaml.safe_load((ROOT / "offer.yaml").read_text(encoding="utf-8"))
    sets = {s["code"]: s for s in offer["sets"]}
    s1, s2 = sets["s1"], sets["s2"]
    card("gen_serum_hand.png", "s1.jpg", f"Сироватка Olavita — {price(s1['price'])}", "30 мл · на місяць догляду за обличчям і шиєю")
    card("gen_pair.png", "s2.jpg", f"Сироватка + крем для очей — {price(s2['price'])}",
         "обличчя, шия і зона навколо очей", badge="Найчастіше беруть")
    card("gen_pair.png", "sets.jpg", "Olavita: сироватка або набір з кремом", "оберіть нижче — платите лише на пошті")
    card("gen_cream_hand.png", "upsell.jpg", f"+ крем для очей — разом {price(s2['price'])}",
         "гусячі лапки й набряки · тією ж посилкою")
    print("ok:", sorted(p.name for p in OUT.glob("*.jpg")))


if __name__ == "__main__":
    sys.exit(main())
