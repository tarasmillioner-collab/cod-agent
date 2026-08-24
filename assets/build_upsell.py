"""Баннер апсейла с CRO-триггерами поверх чистого визуала (vis_course.png, без текста).
Триггеры: что даёт каждый продукт · цена за штуку · экономия · итог · огляд до оплати.
Шрифт — Helvetica Neue (modern), воздух, один золотой акцент."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "assets/src", ROOT / "assets/cards"
W, H = 1600, 1200
INK, MUTED, GOLD, GREEN, WHITE = (28, 28, 34), (110, 106, 98), (168, 130, 48), (34, 110, 72), (255, 255, 255)


def font(size, weight="regular"):
    inter = {"light": "Inter-Regular.ttf", "regular": "Inter-Regular.ttf", "medium": "Inter-Medium.ttf", "bold": "Inter-SemiBold.ttf"}[weight]
    idx = {"light": 7, "regular": 0, "medium": 10, "bold": 1}.get(weight, 0)
    for p, i in ((str(ROOT / "assets/fonts" / inter), 0), ("/System/Library/Fonts/HelveticaNeue.ttc", idx), ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0)):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size, index=i)
            except Exception:  # noqa: BLE001
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def price(n): return f"{n:,}".replace(",", " ") + " грн"


def pill(d, x, y, text, fill, color, f, pad=(30, 14)):
    tw = d.textlength(text, font=f); h = f.size + pad[1] * 2
    d.rounded_rectangle((x, y, x + tw + pad[0] * 2, y + h), radius=h // 2, fill=fill)
    d.text((x + pad[0], y + pad[1] - 1), text, font=f, fill=color)
    return x + tw + pad[0] * 2, y + h


def main(name: str | None = None, out: Path | None = None):
    offer = yaml.safe_load((ROOT / "offer.yaml").read_text(encoding="utf-8"))
    s1 = next(s for s in offer["sets"] if s["code"] == "s1"); s2 = next(s for s in offer["sets"] if s["code"] == "s2")
    n = sum(int(i.get("qty", 1)) for i in s2["items"]); per = round(s2["price"] / n); gift = int(s2.get("gift_value") or 0)
    full = s2["price"] + gift
    im = Image.open(SRC / "vis_course.png").convert("RGB")
    r = max(W / im.width, H / im.height); im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    # мягкая вуаль слева
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 0)); vd = ImageDraw.Draw(veil)
    for i in range(820):
        vd.line((i, 0, i, H), fill=(248, 244, 236, int(200 * (1 - i / 820))))
    im = Image.alpha_composite(im.convert("RGBA"), veil).convert("RGB"); d = ImageDraw.Draw(im)
    x = 80
    head = f"{name}, курс 60 днів" if name else "Курс 60 днів"
    d.text((x, 96), head, font=font(92, "medium"), fill=INK)
    d.text((x, 210), f"3 засоби · по {price(per)} за кожен", font=font(40, "regular"), fill=MUTED)
    d.line((x, 290, x + 520, 290), fill=GOLD, width=2)
    rows = [("✨", "2 × сироватка", "зморшки на обличчі та шиї"),
            ("👁", "крем для очей — у подарунок", "гусячі лапки, набряки, темні кола")]
    y = 330
    for ico, t, sub in rows:
        d.text((x, y), t, font=font(44, "medium"), fill=INK)
        d.text((x, y + 54), sub, font=font(30, "regular"), fill=MUTED)
        y += 130
    y += 10
    x2, y2 = pill(d, x, y, f"Разом {price(s2['price'])}", GOLD, WHITE, font(48, "medium"), pad=(34, 16))
    d.text((x, y2 + 16), f"замість {price(full)} окремо", font=font(30, "regular"), fill=MUTED)
    tw = d.textlength(f"замість {price(full)}", font=font(30, "regular"))
    d.line((x + d.textlength("замість ", font=font(30, "regular")), y2 + 34, x + tw, y2 + 34), fill=MUTED, width=2)
    pill(d, x, y2 + 66, f"Економія {price(gift)}", (226, 240, 230), GREEN, font(34, "medium"), pad=(26, 12))
    d.text((x, 1110), "оплата на пошті · огляд до оплати · одна посилка", font=font(28, "regular"), fill=MUTED)
    out = out or OUT / "upsell.jpg"
    im.save(out, quality=92)
    return out


if __name__ == "__main__":
    main()
    print("ok")
