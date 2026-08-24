"""Гибрид: визуал без текста (nano-banana по реальным упаковкам) + типографика Pillow.
Текст всегда чистый. Запуск: python assets/build_ads.py → assets/cards/{s1,s2,sets,upsell}.jpg"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets/src"
OUT = ROOT / "assets/cards"
W, H = 1600, 1200
INK = (24, 24, 30)
GOLD = (176, 136, 48)
GOLD_L = (214, 178, 94)
GREEN = (46, 110, 70)
MUTED = (95, 92, 86)


def font(size: int, kind: str = "body") -> ImageFont.FreeTypeFont:
    cands = {
        "display": ["/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
        "bold": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
        "body": ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    }[kind]
    for c in cands:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def price(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " грн"


def pill(d: ImageDraw.ImageDraw, x: int, y: int, text: str, fill, color, f: ImageFont.FreeTypeFont, pad=(34, 16)) -> int:
    tw = d.textlength(text, font=f)
    h = f.size + pad[1] * 2
    d.rounded_rectangle((x, y, x + tw + pad[0] * 2, y + h), radius=h // 2, fill=fill)
    d.text((x + pad[0], y + pad[1] - 2), text, font=f, fill=color)
    return y + h


def shadow_text(d, xy, text, f, fill):
    x, y = xy
    d.text((x + 2, y + 3), text, font=f, fill=(0, 0, 0, 40))
    d.text((x, y), text, font=f, fill=fill)


def base(src: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.open(SRC / src).convert("RGB")
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    x = (im.width - W) // 2
    y = (im.height - H) // 2
    im = im.crop((x, y, x + W, y + H))
    # лёгкая вуаль слева под текст
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil)
    for i in range(760):
        a = int(150 * (1 - i / 760))
        vd.line((i, 0, i, H), fill=(246, 241, 232, a))
    im = Image.alpha_composite(im.convert("RGBA"), veil).convert("RGB")
    return im, ImageDraw.Draw(im)


def card_course(offer: dict) -> None:
    s2 = next(s for s in offer["sets"] if s["code"] == "s2")
    n = sum(int(it.get("qty", 1)) for it in s2["items"])
    per = int(round(int(s2["price"]) / n))
    gift = int(s2.get("gift_value") or 0)
    im, d = base("vis_course.png")
    x = 70
    shadow_text(d, (x, 90), "КУРС 60 ДНІВ", font(150, "display"), INK)
    d.text((x, 270), "2 сироватки", font=font(58, "bold"), fill=INK)
    d.text((x, 340), "+ крем для очей", font=font(58, "bold"), fill=INK)
    d.text((x, 410), "у подарунок", font=font(58, "bold"), fill=GOLD)
    d.text((x, 520), f"{n} засоби по {price(per)} за кожен", font=font(40, "body"), fill=INK)
    y = pill(d, x, 600, f"Разом {price(int(s2['price']))}", GOLD_L, INK, font(52, "bold"), pad=(40, 18))
    pill(d, x, y + 22, f"Економія {price(gift)}", (235, 243, 236), GREEN, font(34, "bold"), pad=(28, 12))
    d.text((x, 1110), "оплата на пошті  ·  огляд до оплати", font=font(30, "body"), fill=MUTED)
    im.save(OUT / "upsell.jpg", quality=92)
    im.save(OUT / "s2.jpg", quality=92)
    im.save(OUT / "sets.jpg", quality=92)


def card_serum(offer: dict) -> None:
    s1 = next(s for s in offer["sets"] if s["code"] == "s1")
    im, d = base("vis_serum.png")
    x = 70
    shadow_text(d, (x, 110), "СИРОВАТКА", font(150, "display"), INK)
    shadow_text(d, (x, 250), "OLAVITA", font(150, "display"), GOLD)
    d.text((x, 430), "гладкість і сяйво", font=font(52, "bold"), fill=INK)
    d.text((x, 495), "вже за 7 днів", font=font(52, "bold"), fill=INK)
    d.text((x, 590), "30 мл · на місяць догляду", font=font(36, "body"), fill=MUTED)
    pill(d, x, 680, price(int(s1["price"])), GOLD_L, INK, font(60, "bold"), pad=(44, 20))
    d.text((x, 1110), "оплата на пошті  ·  огляд до оплати", font=font(30, "body"), fill=MUTED)
    im.save(OUT / "s1.jpg", quality=92)


def main() -> None:
    offer = yaml.safe_load((ROOT / "offer.yaml").read_text(encoding="utf-8"))
    OUT.mkdir(exist_ok=True)
    card_course(offer)
    card_serum(offer)
    print("ok:", sorted(p.name for p in OUT.glob("*.jpg")))


if __name__ == "__main__":
    sys.exit(main())
