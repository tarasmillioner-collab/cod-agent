"""Дашборд: PNG для Telegram (щоденно) + статичний HTML (щогодини).

Показники — ті, на які спираємось: воронка з відвалом по кроках, A vs B, гроші, час, здоров'я, останні діалоги.
"""
from __future__ import annotations

from datetime import datetime
from html import escape as e
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.store import Store
from obs.stats import FUNNEL, ab, grn, health, metrics, pct, z_test

NAVY = (18, 28, 58)
GOLD = (214, 178, 94)
CREAM = (246, 241, 232)
INK = (30, 30, 34)
GREY = (120, 120, 128)
A_COL = (90, 120, 200)
B_COL = (214, 150, 60)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for c in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def render_png(store: Store, out: Path, days: int, variants: list[str], labels: dict, title: str, default_set: str = "s1") -> Path:
    W, H = 1200, 900
    im = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(im)
    m = metrics(store, days, None, default_set)
    d.rectangle((0, 0, W, 110), fill=NAVY)
    d.text((40, 28), title, font=_font(40, True), fill=CREAM)
    d.text((40, 74), f"за {days} дн. · {datetime.now().strftime('%d.%m.%Y %H:%M')}", font=_font(22), fill=GOLD)

    # KPI плитки
    marg = grn(m["avg_margin"]) if m["avg_margin"] is not None else "—"
    tiles = [("approve", f"{m['approve']:.0f}%"), ("апсейл", f"{m['upsell_cvr']:.0f}%"),
             ("чек", grn(m["avg_check"])), ("маржа/зам.", marg), ("викуп", f"{m['buyout']:.0f}%")]
    x = 40
    for lab, val in tiles:
        d.rounded_rectangle((x, 130, x + 208, 230), radius=14, fill="white")
        d.text((x + 16, 142), lab, font=_font(20), fill=GREY)
        d.text((x + 16, 170), val, font=_font(34, True), fill=INK)
        x += 226

    # воронка
    c = m["funnel"]
    base = c.get("bot_start", 0) or 1
    d.text((40, 256), "Воронка (відвал по кроках)", font=_font(24, True), fill=INK)
    y = 296
    for key, lab in FUNNEL:
        v = c.get(key, 0)
        w = int(520 * v / base)
        d.rectangle((40, y, 40 + 520, y + 26), fill="white")
        d.rectangle((40, y, 40 + w, y + 26), fill=GOLD)
        d.text((48, y + 4), f"{lab}: {v} ({pct(v, base):.0f}%)", font=_font(18), fill=INK)
        y += 32

    # A vs B
    d.text((620, 256), "A vs B", font=_font(24, True), fill=INK)
    per = ab(store, days, variants, default_set) if len(variants) > 1 else {}
    if per:
        cats = [("approve", "approve"), ("апсейл", "upsell_cvr"), ("бандл", "bundle_share"), ("викуп", "buyout")]
        VCOLS = [A_COL, B_COL, (110, 170, 120)]
        gx = 620
        for lab, key in cats:
            d.text((gx, 296), lab, font=_font(18), fill=GREY)
            for i, v in enumerate(variants[:3]):
                val = per[v][key]
                h = int(160 * min(val, 100) / 100)
                bx = gx + i * 44
                d.rectangle((bx, 500 - h, bx + 36, 500), fill=VCOLS[i % 3])
                d.text((bx, 506), f"{val:.0f}", font=_font(14), fill=INK)
            gx += 145
        ya = 560
        for i, v in enumerate(variants[:3]):
            x_ = per[v]
            col = VCOLS[i % 3]
            d.rectangle((620, ya + 6, 636, ya + 22), fill=col)
            d.text((646, ya), f"{v} «{labels.get(v, v)}»: n={x_['entered']} · апсейл {x_['upsell_cvr']:.0f}% · "
                              f"чек {grn(x_['avg_check'])} · на зайшлого {grn(x_['rpe'])}",
                   font=_font(18), fill=INK)
            ya += 30
        if len(variants) >= 2:
            a, b = per[variants[0]], per[variants[1]]
            z = z_test(a["confirmed"], a["entered"], b["confirmed"], b["entered"])
            d.text((620, ya + 4), "approve: " + (f"z={z:.2f} — {'достовірно' if abs(z) > 1.96 else 'ще шум'}" if z is not None else "мало даних"),
                   font=_font(18), fill=GREY)

    # здоров'я
    hh = health(store)
    d.text((40, 640), "Здоров'я", font=_font(24, True), fill=INK)
    lines = [f"тиша→CRM на прозвон: {m['lead_to_crm']} · handoff: {m['handoff']} · скасували: {m['cancelled']}",
             f"LLM-ліміт: {m['llm_limited']} · заблоковано відповідей: {m['llm_blocked']} · LLM сьогодні ${hh['llm_usd_today']:.2f}",
             f"outbox failed: {hh['outbox_failed']} · pending: {hh['outbox_pending']} · бот {'увімкнено' if hh['bot_enabled'] else 'ВИМКНЕНО'}",
             f"медіана до підтвердження {m['median_min']:.0f} хв · ≤5 хв: {m['fast5_share']:.0f}%"]
    y = 680
    for ln in lines:
        d.text((40, y), ln, font=_font(19), fill=INK)
        y += 28
    if m["by_set"]:
        d.text((620, 700), "Викуп по наборах", font=_font(24, True), fill=INK)
        y = 740
        for code, v in sorted(m["by_set"].items()):
            d.text((620, y), f"{code}: підтв. {v['confirmed']} · відпр. {v['shipped']} · забрали {v['picked']} ({pct(v['picked'], v['shipped']):.0f}%)",
                   font=_font(19), fill=INK)
            y += 28
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=90)
    return out


def render_html(store: Store, out: Path, variants: list[str], labels: dict, title: str, default_set: str = "s1") -> Path:
    """Один екран: перемикач періоду 1/7/30, KPI, воронка-бари, школи A/B/C, гроші, здоров\'я."""
    def z_verdict(per: dict) -> str:
        if len(variants) < 2:
            return ""
        a, b = per[variants[0]], per[variants[1]]
        z = z_test(a["confirmed"], a["entered"], b["confirmed"], b["entered"])
        if z is None:
            return "мало даних для порівняння"
        return f"A vs B approve: z={z:.2f} — " + ("<b>достовірно</b>" if abs(z) > 1.96 else "ще шум, чекаємо даних")

    def period(days: int, active: bool) -> str:
        m = metrics(store, days, None, default_set)
        c = m["funnel"]
        base = c.get("bot_start", 0) or 1
        # воронка як бари
        frows = ""
        prev = base
        for k, lab in FUNNEL:
            v = c.get(k, 0)
            drop = prev - v if prev > v and prev else 0
            frows += (f'<div class="frow"><span class="flab">{lab}</span>'
                      f'<span class="fbar"><i style="width:{pct(v, base):.0f}%"></i></span>'
                      f'<span class="fval">{v}</span><span class="fpct">{pct(v, base):.0f}%</span>'
                      f'<span class="fdrop">{"−" + str(drop) if drop else ""}</span></div>')
            prev = v if v else prev
        abrows = ""
        per = {}
        if len(variants) > 1:
            per = ab(store, days, variants, default_set)
            best = max(per, key=lambda v: per[v]["rpe"])
            for v in variants:
                x = per[v]
                crown = " 👑" if v == best and x["entered"] else ""
                abrows += (f"<tr><td><b>{v}</b> {e(labels.get(v, v))}{crown}</td><td>{x['entered']}</td><td>{x['approve']:.0f}%</td>"
                           f"<td>{x['upsell_cvr']:.0f}% <small>({x['upsell_accepted']}/{x['upsell_shown']})</small></td>"
                           f"<td>{x['bundle_share']:.0f}%</td><td>{grn(x['avg_check'])}</td><td>{x['buyout']:.0f}%</td><td><b>{grn(x['rpe'])}</b></td></tr>")
        sets_rows = "".join(
            f"<tr><td>{code}</td><td>{v['confirmed']}</td><td>{v['shipped']}</td><td>{v['picked']} ({pct(v['picked'], v['shipped']):.0f}%)</td></tr>"
            for code, v in sorted(m["by_set"].items()))
        marg = grn(m["avg_margin"]) if m["avg_margin"] is not None else "—"
        kpis = [("approve", f"{m['approve']:.0f}%", "підтвердили від зайшлих"),
                ("апсейл на бандл", f"{m['upsell_cvr']:.0f}%", f"{m['upsell_accepted']} з {m['upsell_shown']} показів"),
                ("середній чек", grn(m["avg_check"]), "по підтверджених"),
                ("маржа / замовлення", marg, "чек мінус собівартість (CRM)"),
                ("викуп", f"{m['buyout']:.0f}%", "забрали від відправлених")]
        kpi = "".join(f'<div class="kpi"><span>{lab}</span><b>{val}</b><small>{sub}</small></div>' for lab, val, sub in kpis)
        return f"""<div class="period{' on' if active else ''}" id="p{days}">
<div class="kpis">{kpi}</div>
<div class="grid">
<section><h2>Воронка</h2>{frows}
<p class="foot">зайшли: {m['entered']} · виручка: {grn(m['revenue'])} · на зайшлого: {grn(m['rpe'])} · медіана до підтвердження {m['median_min']:.0f} хв · скасували: {m['cancelled']} · тиша→CRM: {m['lead_to_crm']}</p></section>
<section><h2>Школи продажу</h2>
<table><tr><th>школа</th><th>n</th><th>approve</th><th>апсейл</th><th>бандл</th><th>чек</th><th>викуп</th><th>на зайшлого</th></tr>
{abrows or '<tr><td colspan="8">один варіант</td></tr>'}</table>
<p class="foot">{z_verdict(per) if per else ""} · рішення — по «на зайшлого», не по одній метриці</p>
<h2 style="margin-top:18px">Викуп по наборах</h2>
<table><tr><th>набір</th><th>підтв.</th><th>відпр.</th><th>забрали</th></tr>{sets_rows or '<tr><td colspan="4">—</td></tr>'}</table></section>
</div></div>"""

    hh = health(store)
    orders = store.c.execute(
        "SELECT o.id, o.chat_id, o.variant, o.set_code, o.price_uah, o.stage, COALESCE(o.name, c.first_name), o.updated_utc "
        "FROM orders o JOIN chats c ON c.tg_user_id=o.chat_id ORDER BY o.updated_utc DESC LIMIT 20").fetchall()
    stage_ico = {"confirmed_crm": "🟢", "queued_crm": "🟡", "confirmed": "🟡", "shipped": "📦", "arrived": "📍",
                 "picked": "✅", "done": "✅", "returned": "↩️", "cancelled": "✖️", "lead_crm": "📞"}
    drows = "".join(
        f'<tr><td>#{r[0]}</td><td>{r[2] or ""}</td><td>{r[3] or ""}</td><td class="num">{grn(r[4]) if r[4] else "—"}</td>'
        f'<td>{stage_ico.get(r[5], "·")} {r[5]}</td><td><a href="/dialogs.html#u{r[1]}">{e(r[6] or "?")}</a></td>'
        f"<td>{r[7][5:16].replace('T', ' ')}</td></tr>" for r in orders)
    reasons = ", ".join(f"{e(str(k))}: {v}" for k, v in hh["handoff_reasons"]) or "—"
    ok = hh["outbox_failed"] == 0 and hh["bot_enabled"]
    html = f"""<!doctype html><html lang="uk"><head><meta charset="utf-8"><title>{e(title)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="900">
<style>
:root{{--navy:#121c3a;--gold:#d6b25e;--cream:#f6f1e8;--ink:#1e1e22;--mut:#8a8a92;--ok:#2e7d4f;--bad:#b04a4a}}
*{{box-sizing:border-box}} body{{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--cream);color:var(--ink);margin:0}}
header{{background:var(--navy);color:var(--cream);padding:18px 28px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;position:sticky;top:0;z-index:5}}
header h1{{font-size:22px;margin:0}} header small{{color:var(--gold)}}
.tabs{{display:flex;gap:6px;margin-left:auto}} .tabs button{{border:0;background:#2a3a6a;color:var(--cream);padding:8px 16px;border-radius:10px;cursor:pointer;font-size:14px}}
.tabs button.on{{background:var(--gold);color:var(--navy);font-weight:600}}
a.nav{{color:var(--cream);text-decoration:none;background:#2a3a6a;padding:8px 14px;border-radius:10px;font-size:14px}}
main{{padding:20px 28px;max-width:1280px;margin:0 auto}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:16px}}
.kpi{{background:#fff;border-radius:12px;padding:12px 14px}} .kpi span{{display:block;color:var(--mut);font-size:12px}}
.kpi b{{font-size:24px;font-variant-numeric:tabular-nums}} .kpi small{{display:block;color:var(--mut);font-size:11px;margin-top:2px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} @media(max-width:900px){{.grid{{grid-template-columns:1fr}}}}
section{{background:#fff;border-radius:14px;padding:16px 20px}} h2{{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:0 0 12px}}
.frow{{display:grid;grid-template-columns:96px 1fr 44px 44px 44px;gap:8px;align-items:center;margin:5px 0;font-size:14px}}
.flab{{color:var(--ink)}} .fbar{{background:var(--cream);border-radius:6px;height:18px;overflow:hidden}}
.fbar i{{display:block;height:100%;background:linear-gradient(90deg,var(--gold),#c69b3f);border-radius:6px}}
.fval{{text-align:right;font-variant-numeric:tabular-nums}} .fpct{{text-align:right;color:var(--mut);font-variant-numeric:tabular-nums}}
.fdrop{{text-align:right;color:var(--bad);font-size:12px;font-variant-numeric:tabular-nums}}
table{{border-collapse:collapse;font-size:14px;width:100%}} td,th{{padding:6px 8px;border-bottom:1px solid #f0ebe0;text-align:left}}
th{{color:var(--mut);font-weight:500;font-size:12px}} td.num{{font-variant-numeric:tabular-nums}} td small{{color:var(--mut)}}
.foot{{color:var(--mut);font-size:12.5px;margin:10px 0 0}}
.period{{display:none}} .period.on{{display:block}}
.health{{display:flex;gap:10px;flex-wrap:wrap;font-size:13.5px;margin-top:16px}}
.health div{{background:#fff;border-radius:10px;padding:8px 14px}} .ok{{color:var(--ok)}} .bad{{color:var(--bad);font-weight:600}}
section.wide{{margin-top:16px}} a{{color:#2a5aa0}}
</style></head><body>
<header><h1>{e(title)}</h1><small>оновлено {datetime.now().strftime("%d.%m %H:%M")}</small>
<div class="tabs"><button class="on" onclick="show(1,this)">сьогодні</button><button onclick="show(7,this)">7 днів</button><button onclick="show(30,this)">30 днів</button></div>
<a class="nav" href="/dialogs.html">💬 діалоги</a></header>
<main>
{period(1, True)}{period(7, False)}{period(30, False)}
<div class="health">
<div class="{'ok' if ok else 'bad'}">{'🟢 бот працює' if hh['bot_enabled'] else '🔴 БОТ ВИМКНЕНО'}</div>
<div class="{'ok' if hh['outbox_failed'] == 0 else 'bad'}">outbox failed: {hh['outbox_failed']}</div>
<div>pending: {hh['outbox_pending']}</div><div>LLM сьогодні ${hh['llm_usd_today']:.2f}</div>
<div>handoff 7 дн.: {reasons}</div></div>
<section class="wide"><h2>Останні 20 замовлень</h2>
<table><tr><th>#</th><th>школа</th><th>набір</th><th>сума</th><th>стадія</th><th>клієнт → діалог</th><th>оновлено</th></tr>{drows}</table></section>
</main>
<script>function show(d,btn){{document.querySelectorAll(".period").forEach(p=>p.classList.remove("on"));
document.getElementById("p"+d).classList.add("on");
document.querySelectorAll(".tabs button").forEach(b=>b.classList.remove("on"));btn.classList.add("on")}}</script>
</body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


import re as _re_mod

_TAG_RX = _re_mod.compile(r"<[^>]+>")


def _plain(t: str) -> str:
    return _TAG_RX.sub("", t or "")


def render_dialogs_html(store: Store, out: Path, title: str, limit_chats: int = 30, limit_msgs: int = 120) -> Path:
    """Читалка переписок: чати з повідомленнями, бульбашки клієнт/Оля, якорі #u<id> для лінків з дашборда."""
    chats = store.c.execute(
        """SELECT c.tg_user_id, c.first_name, c.username, c.name, c.variant, c.mode,
                  MAX(m.ts_utc) AS last_ts, COUNT(m.id) AS n
           FROM chats c JOIN messages m ON m.chat_id = c.tg_user_id
           GROUP BY c.tg_user_id ORDER BY last_ts DESC LIMIT ?""", (limit_chats,)).fetchall()
    blocks = []
    for ch in chats:
        o = store.c.execute("SELECT id, set_code, stage, price_uah FROM orders WHERE chat_id=? ORDER BY id DESC LIMIT 1",
                            (ch["tg_user_id"],)).fetchone()
        msgs = store.c.execute("SELECT role, content, ts_utc FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                               (ch["tg_user_id"], limit_msgs)).fetchall()
        bub = []
        for mrow in reversed(msgs):
            side = "user" if mrow["role"] == "user" else "bot"
            bub.append(f'<div class="msg {side}"><div class="b">{e(_plain(mrow["content"]))}'
                       f'<span class="t">{mrow["ts_utc"][5:16].replace("T", " ")}</span></div></div>')
        who = e(ch["name"] or ch["first_name"] or "?") + (f' <small>@{e(ch["username"])}</small>' if ch["username"] else "")
        meta = f'{ch["variant"] or "?"}' + (f' · #{o["id"]} {o["set_code"] or ""} {o["stage"]}' if o else "")
        mode = ' · <b class="bad">У МЕНЕДЖЕРА</b>' if ch["mode"] == "human" else ""
        blocks.append(f'<details id="u{ch["tg_user_id"]}"><summary><b>{who}</b> <span class="meta">{meta}{mode} · '
                      f'{ch["n"]} повід. · {ch["last_ts"][5:16].replace("T", " ")}</span></summary>'
                      f'<div class="thread">{"".join(bub)}</div></details>')
    html = f"""<!doctype html><html lang="uk"><head><meta charset="utf-8"><title>{e(title)} · діалоги</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="900">
<style>
:root{{--navy:#121c3a;--gold:#d6b25e;--cream:#f6f1e8;--ink:#1e1e22;--mut:#8a8a92;--bad:#b04a4a}}
*{{box-sizing:border-box}} body{{font-family:-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--cream);color:var(--ink);margin:0}}
header{{background:var(--navy);color:var(--cream);padding:18px 28px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:5}}
header h1{{font-size:22px;margin:0}} header small{{color:var(--gold)}}
a.nav{{margin-left:auto;color:var(--cream);text-decoration:none;background:#2a3a6a;padding:8px 14px;border-radius:10px;font-size:14px}}
main{{padding:20px 28px;max-width:900px;margin:0 auto}}
details{{background:#fff;border-radius:14px;padding:12px 18px;margin-bottom:10px}} details[open]{{padding-bottom:16px}}
summary{{cursor:pointer;font-size:15px}} summary small{{color:var(--mut)}}
.meta{{color:var(--mut);font-size:13px}} .bad{{color:var(--bad)}}
.thread{{margin-top:12px;max-height:70vh;overflow-y:auto;display:flex;flex-direction:column;gap:6px}}
.msg{{display:flex}} .msg.bot{{justify-content:flex-end}}
.msg .b{{max-width:76%;padding:8px 12px;border-radius:14px;font-size:14px;white-space:pre-wrap;background:#efece4}}
.msg.bot .b{{background:#f3e7c9}} .msg .t{{display:block;color:#9a9aa2;font-size:11px;margin-top:4px}}
</style></head><body>
<header><h1>{e(title)} · діалоги</h1><small>оновлено {datetime.now().strftime("%d.%m %H:%M")}</small>
<a class="nav" href="/dashboard.html">📊 дашборд</a></header>
<main>{"".join(blocks) or "<p>Ще немає переписок.</p>"}</main>
<script>document.querySelectorAll("details").forEach(d=>d.addEventListener("toggle",()=>{{if(d.open){{const t=d.querySelector(".thread");t.scrollTop=t.scrollHeight}}}}));
if(location.hash){{const d=document.querySelector(location.hash);if(d){{d.open=true;d.scrollIntoView()}}}}</script>
</body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
