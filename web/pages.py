"""Сторінки пульта в дизайн-мові Telegram: dashboard.html, dialogs.html (месенджер), broadcast.html.

Статичні файли у var/ (перегенерація щогодини), живі дані та дії — через /api/* (web/api.py).
Шаблони — з плейсхолдерами %%X%%: жодних f-string навколо JS/CSS фігурних дужок.
"""
from __future__ import annotations

import json
import re as _re
from datetime import datetime, timedelta, timezone
from html import escape as e
from pathlib import Path

from core.store import Store
from obs.stats import FUNNEL, ab, grn, health, metrics, pct  # noqa: F401

# ──────────────────────────────── дизайн-система ────────────────────────────────
_CSS = r"""
:root{
 --bg:#0e1621;--bg2:#17212b;--card:#1f2936;--card2:#232e3c;--hover:#2b3948;
 --ink:#ffffff;--sub:#7f92a5;--line:#0b1218;
 --acc:#3390ec;--acc2:#64baf0;--accsoft:rgba(51,144,236,.14);
 --green:#4dcd5e;--red:#ef5350;--yellow:#e8a33d;
 --in:#182533;--out:#2b5278;--outink:#ffffff;
 --shadow:0 1px 2px rgba(0,0,0,.28),0 8px 24px rgba(0,0,0,.18);
 --r:14px;--r2:18px;
}
:root[data-theme="light"]{
 --bg:#eef1f4;--bg2:#ffffff;--card:#ffffff;--card2:#f7f8fa;--hover:#f0f3f6;
 --ink:#0f1419;--sub:#707579;--line:#e4e9ec;
 --acc:#3390ec;--acc2:#2481cc;--accsoft:rgba(51,144,236,.10);
 --green:#31a24c;--red:#e0393e;--yellow:#c98a1e;
 --in:#ffffff;--out:#eeffde;--outink:#0f1419;
 --shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.06);
}
@media (prefers-color-scheme:light){:root:not([data-theme="dark"]){
 --bg:#eef1f4;--bg2:#ffffff;--card:#ffffff;--card2:#f7f8fa;--hover:#f0f3f6;
 --ink:#0f1419;--sub:#707579;--line:#e4e9ec;--acc2:#2481cc;--accsoft:rgba(51,144,236,.10);
 --green:#31a24c;--red:#e0393e;--yellow:#c98a1e;--in:#ffffff;--out:#eeffde;--outink:#0f1419;
 --shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.06);
}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);min-height:100vh;
 font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"Helvetica Neue",sans-serif;
 font-size:15px;line-height:1.45;-webkit-font-smoothing:antialiased}
a{color:var(--acc);text-decoration:none}
::-webkit-scrollbar{width:8px;height:8px}
::-webkit-scrollbar-thumb{background:rgba(127,146,165,.35);border-radius:8px}
::-webkit-scrollbar-track{background:transparent}

/* топбар */
.top{position:sticky;top:0;z-index:20;background:var(--bg2);border-bottom:1px solid var(--line);
 display:flex;align-items:center;gap:12px;padding:10px 20px;min-height:60px}
.brand{display:flex;align-items:center;gap:11px;min-width:0}
.ava{width:40px;height:40px;border-radius:50%;flex:none;display:grid;place-items:center;
 font-weight:600;font-size:16px;color:#fff}
.g0{background:linear-gradient(180deg,#5caffe,#237bd3)}.g1{background:linear-gradient(180deg,#ff885e,#ff516a)}
.g2{background:linear-gradient(180deg,#a0de7e,#54cb68)}.g3{background:linear-gradient(180deg,#ffcd6a,#ffa85c)}
.g4{background:linear-gradient(180deg,#82b1ff,#665fff)}.g5{background:linear-gradient(180deg,#e0a2f3,#d669ed)}
.g6{background:linear-gradient(180deg,#53edd6,#28c9b7)}
.brand .nm{font-weight:600;font-size:15.5px;line-height:1.2;white-space:nowrap}
.brand .st{font-size:13px;color:var(--acc2);line-height:1.3}
.brand .st.off{color:var(--red)}
.seg{display:flex;background:var(--card2);border-radius:11px;padding:3px;margin-left:auto;flex:none}
.seg button{border:0;background:transparent;color:var(--sub);font:inherit;font-size:13.5px;font-weight:500;
 padding:7px 15px;border-radius:9px;cursor:pointer;transition:color .18s}
.seg button.on{background:var(--acc);color:#fff;font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.2)}
.seg button:not(.on):hover{color:var(--ink)}
.tbtn{width:38px;height:38px;border-radius:50%;border:0;background:transparent;color:var(--sub);
 display:grid;place-items:center;cursor:pointer;font-size:17px;transition:background .18s,color .18s;flex:none}
.tbtn:hover{background:var(--hover);color:var(--ink)}
.tbtn.lbl{width:auto;border-radius:19px;padding:0 14px;height:38px;font-size:14px;gap:7px;font-weight:500}
.tbtn.lbl .ico{display:grid;place-items:center;width:18px;height:18px}
.tbtn.lbl .ico svg{width:18px;height:18px}
.tabbar a i svg{width:23px;height:23px}
.tbtn.lbl.on{background:var(--accsoft);color:var(--acc)}
.upd{font-size:12.5px;color:var(--sub);font-variant-numeric:tabular-nums;white-space:nowrap}
@media(max-width:900px){.top{flex-wrap:wrap;padding:10px 14px}.seg{order:5;width:100%;margin-left:0}
 .seg button{flex:1}.upd{display:none}}

/* каркас */
main{max-width:1180px;margin:0 auto;padding:18px 20px 56px}
@media(max-width:640px){main{padding:14px 12px 44px}}
.cols{display:grid;gap:14px}
.c-2{grid-template-columns:1.06fr .94fr}
.c-hero{grid-template-columns:1.15fr .85fr}
@media(max-width:940px){.c-2,.c-hero{grid-template-columns:1fr}}
.card{background:var(--card);border-radius:var(--r2);box-shadow:var(--shadow);padding:18px 20px;
 animation:rise .38s cubic-bezier(.22,.8,.22,1) both}
.card.p0{padding:0;overflow:hidden}
@keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.d1{animation-delay:.04s}.d2{animation-delay:.08s}.d3{animation-delay:.12s}.d4{animation-delay:.16s}
.ttl{font-size:11.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--acc);
 margin:0 0 14px;display:flex;align-items:center;gap:8px}
.ttl .r{margin-left:auto;color:var(--sub);font-weight:500;letter-spacing:0;text-transform:none;font-size:12.5px}
.hint{color:var(--sub);font-size:12.5px;margin:12px 0 0;line-height:1.5}
.hint.top{margin:-6px 0 14px}

/* hero */
.hero .lab{font-size:12.5px;color:var(--sub);font-weight:500}
.hero .big{font-size:46px;font-weight:700;letter-spacing:-.02em;line-height:1.15;font-variant-numeric:tabular-nums;
 background:linear-gradient(180deg,var(--ink),var(--sub));-webkit-background-clip:text;background-clip:text;
 -webkit-text-fill-color:transparent;margin:2px 0 4px}
.hero .sub{font-size:13.5px;color:var(--sub)}
.hero .badges{display:flex;gap:7px;flex-wrap:wrap;margin-top:14px}
.badge{font-size:12.5px;font-weight:500;padding:5px 11px;border-radius:20px;background:var(--card2);color:var(--sub);
 display:inline-flex;align-items:center;gap:5px}
.badge.acc{background:var(--accsoft);color:var(--acc)}
.badge.gr{background:rgba(77,205,94,.14);color:var(--green)}
.badge.rd{background:rgba(239,83,80,.14);color:var(--red)}

/* kpi */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin:14px 0}
.kpi{background:var(--card);border-radius:var(--r);box-shadow:var(--shadow);padding:14px 16px;position:relative;
 transition:transform .2s cubic-bezier(.22,.8,.22,1);animation:rise .38s cubic-bezier(.22,.8,.22,1) both}
.kpi:hover{transform:translateY(-2px)}
.kpi .k{font-size:11.5px;color:var(--sub);font-weight:600;letter-spacing:.03em;text-transform:uppercase;
 display:block;padding-right:52px}
.kpi .v{font-size:27px;font-weight:700;letter-spacing:-.01em;font-variant-numeric:tabular-nums;display:block;margin:3px 0 1px}
.kpi .s{font-size:11.5px;color:var(--sub);display:block;min-height:16px}
.kpi.acc .v{color:var(--acc2)}.kpi.gr .v{color:var(--green)}
.dl{position:absolute;top:13px;right:14px;font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:20px;
 font-variant-numeric:tabular-nums}
.dl.up{color:var(--green);background:rgba(77,205,94,.14)}
.dl.dn{color:var(--red);background:rgba(239,83,80,.14)}
.kpi.flash::after{content:"";position:absolute;inset:0;border-radius:var(--r);background:var(--accsoft);
 animation:fl .95s ease-out forwards;pointer-events:none}
@keyframes fl{from{opacity:1}to{opacity:0}}

/* воронка */
.fn{display:flex;flex-direction:column;gap:3px}
.fr{display:grid;grid-template-columns:98px minmax(0,1fr) 42px 44px;gap:10px;align-items:center;
 padding:6px 8px;border-radius:10px;transition:background .15s}
.fr>*{min-width:0}
.fr .l{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fr:hover{background:var(--hover)}
.fr .l{font-size:14px;font-weight:500}
.fr .l em{font-style:normal;display:block;font-size:10px;color:var(--sub);line-height:1;letter-spacing:.04em;text-transform:uppercase}
.trk{height:8px;border-radius:8px;background:var(--card2);overflow:hidden}
.trk i{display:block;height:100%;border-radius:8px;background:linear-gradient(90deg,var(--acc),var(--acc2));
 transition:width .85s cubic-bezier(.22,.8,.22,1)}
.fr .n{text-align:right;font-weight:600;font-size:14px;font-variant-numeric:tabular-nums}
.fr .p{text-align:right;color:var(--sub);font-size:12.5px;font-variant-numeric:tabular-nums}
.fr.up .l{padding-left:14px;color:var(--yellow);font-size:13px}
.fr.up .trk i{background:linear-gradient(90deg,var(--yellow),#f3c37a)}
.fr.drop .p{color:var(--red)}

/* A/B */
.ab{width:100%;border-collapse:collapse;font-size:14px}
.ab th,.ab td{padding:9px 10px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
.ab thead th{font-size:12px;font-weight:600;padding-bottom:11px}
.ab thead th span{display:block;font-size:11px;color:var(--sub);font-weight:500}
.ab tbody td:first-child{color:var(--sub);font-size:12.5px;width:154px;white-space:normal}
.ab td{font-variant-numeric:tabular-nums;font-weight:500}
.ab td s{text-decoration:none;color:var(--sub);font-size:11.5px;font-weight:400;margin-left:3px}
.ab tbody tr:hover{background:var(--hover)}
.ab td.w{color:var(--green);font-weight:700}
.ab td.w::before{content:"● ";font-size:10px;vertical-align:middle}
.ab tr.key td{background:var(--accsoft);font-size:16px;font-weight:700}
.ab tr.key td:first-child{color:var(--acc);font-size:12.5px;font-weight:600}
.ab tr.key td.w{color:var(--green)}
.ab tr.pg td{border-bottom:0;color:var(--sub);font-size:11.5px;font-weight:400}
.pgb{display:inline-block;width:52px;height:5px;border-radius:5px;background:var(--card2);overflow:hidden;
 vertical-align:middle;margin-right:5px}
.pgb i{display:block;height:100%;background:var(--acc);border-radius:5px}
.crown{font-size:12px}

/* пульс */
.pulse{display:flex;align-items:flex-end;gap:5px;height:130px;padding-top:6px}
.pd{flex:1;display:flex;flex-direction:column;align-items:center;gap:6px;min-width:0}
.pd .pv{font-size:11.5px;font-weight:700;font-variant-numeric:tabular-nums;min-height:15px;color:var(--sub)}
.pd.hi .pv{color:var(--ink)}
.pcol{width:100%;max-width:30px;height:88px;display:flex;flex-direction:column;justify-content:flex-end;
 background:var(--card2);border-radius:8px;overflow:hidden}
.pcol i{display:block;width:100%;border-radius:8px;background:linear-gradient(180deg,var(--acc2),var(--acc));
 transition:height .85s cubic-bezier(.22,.8,.22,1)}
.pd.today .pcol i{background:linear-gradient(180deg,#6ee08a,var(--green))}
.pd .pl{font-size:10px;color:var(--sub);font-variant-numeric:tabular-nums}

/* стрічка подій */
.feed{display:flex;flex-direction:column;gap:8px;max-height:246px;overflow-y:auto;padding-right:4px}
.ev{display:flex;gap:10px;align-items:flex-start}
.ev .ic{width:30px;height:30px;border-radius:50%;flex:none;display:grid;place-items:center;font-size:14px;
 background:var(--card2)}
.ev .bb{background:var(--in);border-radius:4px 14px 14px 14px;padding:7px 11px;font-size:13.5px;min-width:0;
 box-shadow:0 1px 1px rgba(0,0,0,.12)}
:root[data-theme="light"] .ev .bb{border:1px solid var(--line)}
.ev .bb b{font-weight:600}
.ev .bb .t{color:var(--sub);font-size:11px;margin-left:7px;white-space:nowrap}
.ev.money .bb{background:var(--out);color:var(--outink)}
.ev.money .bb .t{color:rgba(255,255,255,.6)}
:root[data-theme="light"] .ev.money .bb .t{color:#5a8a4a}
.ev:first-child{animation:pop .4s cubic-bezier(.22,.8,.22,1)}
@keyframes pop{from{opacity:0;transform:translateY(-6px) scale(.97)}to{opacity:1;transform:none}}

/* список замовлень */
.rows{display:flex;flex-direction:column}
.row{display:flex;align-items:center;gap:12px;padding:10px 20px;border-bottom:1px solid var(--line);
 transition:background .15s;text-decoration:none;color:inherit}
.row:last-child{border-bottom:0}
.row:hover{background:var(--hover)}
.row .ava{width:44px;height:44px;font-size:16px}
.row .mid{min-width:0;flex:1}
.row .n1{display:flex;align-items:baseline;gap:8px}
.row .n1 b{font-weight:600;font-size:14.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .n1 .tag{font-size:10.5px;font-weight:600;color:var(--acc);background:var(--accsoft);border-radius:6px;padding:1px 6px;flex:none}
.row .n2{font-size:13px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .rt{text-align:right;flex:none}
.row .rt .sum{font-weight:600;font-size:14px;font-variant-numeric:tabular-nums}
.row .rt .tm{font-size:11.5px;color:var(--sub);font-variant-numeric:tabular-nums}
.st-dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;vertical-align:middle}
.sd-ok{background:var(--green)}.sd-wait{background:var(--yellow)}.sd-bad{background:var(--red)}.sd-mid{background:var(--acc)}

/* гроші по шляху */
.mf{width:100%;border-collapse:collapse;font-size:14px}
.mf th,.mf td{padding:9px 10px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
.mf th:first-child,.mf td:first-child{text-align:left}
.mf thead th{font-size:11px;font-weight:600;color:var(--sub);text-transform:uppercase;letter-spacing:.05em}
.mf td{font-variant-numeric:tabular-nums;font-weight:500}
.mf tbody tr:hover{background:var(--hover)}
.mf .stg{display:flex;align-items:center;gap:8px;font-weight:600}
.mf .dotc{width:8px;height:8px;border-radius:50%;flex:none}
.mf .cv{color:var(--acc);font-weight:700}
.mf .cv.low{color:var(--yellow)}
.mf tr.cash td{background:rgba(77,205,94,.10)}
.mf tr.cash td:first-child{color:var(--green)}
.mf tr.cash td b{color:var(--green)}
.mf tr.lost td{color:var(--red);opacity:.85}
.mf .muted{color:var(--sub);font-weight:400}
/* статус-рядок */
.statusbar{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;align-items:center}
.chip{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:7px 13px;font-size:12.5px;
 color:var(--sub);display:inline-flex;align-items:center;gap:7px}
.chip.ok{color:var(--green)}.chip.bad{color:var(--red);font-weight:700;border-color:var(--red)}
.chip button,.chip.tog{border:0;background:transparent;color:var(--acc);font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;padding:0}
.chip.tog{cursor:pointer;padding:7px 13px}
.sw{width:34px;height:20px;border-radius:20px;background:var(--card2);position:relative;transition:background .2s;flex:none}
.sw i{position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:50%;background:var(--sub);transition:.2s}
.sw.on{background:var(--acc)}.sw.on i{left:17px;background:#fff}
/* тост / конфетті */
#toast{position:fixed;left:50%;transform:translateX(-50%);bottom:22px;z-index:60}
.toast{background:var(--card);color:var(--ink);border-radius:14px;padding:12px 18px;font-size:14.5px;font-weight:500;
 box-shadow:0 6px 30px rgba(0,0,0,.35);display:flex;align-items:center;gap:10px;animation:tup .42s cubic-bezier(.22,.8,.22,1)}
@keyframes tup{from{opacity:0;transform:translateY(26px)}to{opacity:1;transform:none}}
.cf{position:fixed;top:-14px;width:8px;height:13px;border-radius:2px;z-index:70;animation:fall linear forwards}
@keyframes fall{to{transform:translateY(106vh) rotate(720deg);opacity:.15}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
.scroll-x{overflow-x:auto}

/* ── таб-бар (моб.) ── */
.tabbar{display:none}
.navtop{display:contents}
@media(max-width:900px){
 .navtop{display:none}
 .tabbar{display:grid;grid-template-columns:repeat(4,1fr);position:fixed;left:0;right:0;bottom:0;z-index:40;
  background:var(--bg2);border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom);
  box-shadow:0 -2px 16px rgba(0,0,0,.22)}
 .tabbar a{display:flex;flex-direction:column;align-items:center;gap:3px;padding:9px 0 8px;font-size:10.5px;
  color:var(--sub);text-decoration:none;font-weight:600;letter-spacing:.01em;transition:color .16s}
 .tabbar a i{font-style:normal;display:grid;place-items:center;height:23px}
 .tabbar a.on{color:var(--acc)}
 .tabbar a:active{transform:scale(.94)}
}
/* ── планшет/телефон: шапка ── */
@media(max-width:900px){
 .top{padding:8px 12px;min-height:52px;gap:9px;flex-wrap:wrap}
 .brand .ava{width:34px;height:34px;font-size:14px}
 .brand .nm{font-size:15px}.brand .st{font-size:11.5px}
 .seg{order:5;width:100%;margin:1px 0 0}
 .seg button{flex:1;padding:9px 0;font-size:13.5px}
 main{padding-bottom:82px}
 .search input,.comp textarea,.compose textarea,.compose input{font-size:16px}
}
/* ── телефон ── */
@media(max-width:640px){
 main{padding:12px 12px 82px}
 .cols{gap:12px}
 .card{padding:15px 16px;border-radius:16px}
 .hero .big{font-size:38px}
 .hero .sub{font-size:12.5px;line-height:1.5}
 .hero .badges{margin-top:12px;gap:6px}
 .badge{font-size:12px;padding:5px 10px}
 .kpis{grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}
 .kpi{padding:12px 13px}
 .kpi .k{font-size:10px;padding-right:40px;letter-spacing:.02em}
 .kpi .v{font-size:23px}
 .kpi .s{font-size:11px;line-height:1.35}
 .dl{top:11px;right:11px;font-size:10.5px;padding:2px 6px}
 .feed{max-height:none;overflow:visible;padding-right:0}
 .ev .bb{font-size:13px;padding:7px 10px}
 .fr{grid-template-columns:72px minmax(0,1fr) 28px 38px;gap:7px;padding:5px 2px}
 .fr .l{font-size:13px}.fr .n{font-size:13px}.fr .p{font-size:11.5px}
 .fr.up .l{padding-left:9px;font-size:12px}
 .ab th,.ab td{padding:8px 9px;font-size:13px}
 .ab tbody td:first-child,.ab thead th:first-child{position:sticky;left:0;z-index:2;background:var(--card);
  width:104px;min-width:104px;font-size:11.5px}
 .ab tr.key td:first-child{background:linear-gradient(var(--accsoft),var(--accsoft)),var(--card)}
 .ab thead th{font-size:11.5px}
 .ab thead th span{font-size:10px}
 .pulse{height:112px;gap:4px}
 .pcol{height:74px;max-width:26px}
 .row{padding:11px 14px;gap:10px}
 .row .ava{width:42px;height:42px}
 .row .n1 b{font-size:14px}
 .row .n2{font-size:12.5px}
 .ttl{font-size:11px}
 .hint{font-size:12px}
 #toast{left:12px;right:12px;transform:none;bottom:calc(78px + env(safe-area-inset-bottom))}
 .toast{font-size:13.5px;padding:11px 15px}
}
.row:active,.ch:active,.kpi:active{transform:scale(.985)}
.scroll-x{-webkit-overflow-scrolling:touch}
"""

_MSG_CSS = r"""
.tgwrap{display:grid;grid-template-columns:352px 1fr;height:calc(100vh - 61px)}
@media(max-width:860px){.tgwrap{grid-template-columns:1fr;height:calc(100vh - 61px)}
 .tgwrap.open .list{display:none}.tgwrap:not(.open) .conv{display:none}}
.list{border-right:1px solid var(--line);background:var(--bg2);display:flex;flex-direction:column;min-height:0}
.search{padding:9px 12px;border-bottom:1px solid var(--line)}
.search input{width:100%;background:var(--card2);border:0;border-radius:20px;padding:9px 15px;color:var(--ink);
 font:inherit;font-size:14px;outline:none}
.search input::placeholder{color:var(--sub)}
.fchips{display:flex;gap:6px;margin-top:8px}
.fc{flex:1;border:0;background:var(--card2);color:var(--sub);font:inherit;font-size:12.5px;font-weight:600;
 padding:7px 4px;border-radius:9px;cursor:pointer;transition:.16s}
.fc.on{background:var(--accsoft);color:var(--acc)}
.chats{overflow-y:auto;flex:1;min-height:0;padding:4px 0}
.ch{display:flex;gap:11px;align-items:center;padding:9px 12px;cursor:pointer;border-radius:12px;margin:2px 6px;
 transition:background .14s}
.ch:hover{background:var(--hover)}
.ch.on{background:var(--acc)}
.ch.on .nm,.ch.on .pv,.ch.on .tm{color:#fff}
.ch .ava{width:48px;height:48px;font-size:17px}
.ch .m{min-width:0;flex:1}
.ch .r1{display:flex;align-items:baseline;gap:7px}
.ch .nm{font-weight:600;font-size:14.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ch .tm{margin-left:auto;font-size:11.5px;color:var(--sub);flex:none}
.ch .pv{font-size:13px;color:var(--sub);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px}
.ch .bdg{background:var(--green);color:#fff;font-size:10.5px;font-weight:700;border-radius:11px;padding:1px 7px;flex:none;
 max-width:74px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ch .bdg.hum{background:var(--red)} .ch .bdg.mine{background:var(--acc)}
.conv{display:flex;flex-direction:column;min-height:0;background:var(--bg)}
.chead{display:flex;align-items:center;gap:11px;padding:9px 18px;background:var(--bg2);border-bottom:1px solid var(--line);min-height:58px}
.chead .ava{width:38px;height:38px;font-size:15px}
.chead .nm{font-weight:600;font-size:15px}
.chead .st{font-size:12.5px;color:var(--sub)}
.chead .st b{color:var(--acc2);font-weight:500}
.back{display:none}
@media(max-width:860px){.back{display:grid}}
.msgs{flex:1;overflow-y:auto;padding:18px 18px 8px;display:flex;flex-direction:column;gap:3px;min-height:0}
.msgs .day{align-self:center;font-size:11.5px;color:var(--sub);background:var(--card2);border-radius:12px;
 padding:3px 11px;margin:10px 0 6px}
.m{max-width:min(74%,560px);padding:7px 12px 6px;font-size:14.5px;line-height:1.38;position:relative;
 box-shadow:0 1px 1px rgba(0,0,0,.14);animation:mpop .3s cubic-bezier(.22,.8,.22,1);word-wrap:break-word;white-space:pre-wrap}
@keyframes mpop{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.m.i{align-self:flex-start;background:var(--in);border-radius:14px 14px 14px 5px}
.m.o{align-self:flex-end;background:var(--out);color:var(--outink);border-radius:14px 14px 5px 14px}
:root[data-theme="light"] .m.i{border:1px solid var(--line)}
.m .mt{float:right;font-size:11px;color:var(--sub);margin:6px -3px -2px 9px;font-variant-numeric:tabular-nums}
.m.o .mt{color:rgba(255,255,255,.55)}
:root[data-theme="light"] .m.o .mt{color:#63a15a}
.m .who{display:block;font-size:11.5px;font-weight:600;color:var(--acc2);margin-bottom:2px}
.m.o .who{color:#cfe6ff}
:root[data-theme="light"] .m.o .who{color:#4a7c3a}
.comp{display:flex;align-items:flex-end;gap:10px;padding:11px 18px 16px;background:var(--bg2);border-top:1px solid var(--line)}
.comp textarea{flex:1;background:var(--card);border:0;border-radius:20px;padding:11px 16px;color:var(--ink);font:inherit;
 font-size:14.5px;resize:none;max-height:120px;outline:none;box-shadow:var(--shadow)}
.comp textarea::placeholder{color:var(--sub)}
.send{width:44px;height:44px;border-radius:50%;border:0;background:var(--acc);color:#fff;font-size:18px;cursor:pointer;
 flex:none;display:grid;place-items:center;transition:transform .16s,background .16s}
.send:hover{background:var(--acc2);transform:scale(1.06)}
.cst{padding:0 18px 10px;font-size:12.5px;color:var(--sub);background:var(--bg2)}
.empty{flex:1;display:grid;place-items:center;color:var(--sub);font-size:14px;text-align:center;padding:30px;line-height:1.6}
"""

_BC_CSS = r"""
.seglist{display:flex;flex-direction:column}
.sgi{display:flex;align-items:center;gap:12px;padding:12px 4px;border-bottom:1px solid var(--line);cursor:pointer}
.sgi:last-child{border-bottom:0}
.sgi input{appearance:none;-webkit-appearance:none;width:21px;height:21px;border-radius:50%;border:2px solid var(--sub);
 flex:none;transition:border-color .16s;position:relative;margin:0}
.sgi input:checked{border-color:var(--acc)}
.sgi input:checked::after{content:"";position:absolute;inset:3px;border-radius:50%;background:var(--acc)}
.sgi .t{flex:1;font-size:14.5px}
.sgi .c{font-weight:600;font-variant-numeric:tabular-nums;color:var(--acc)}
.compose{background:var(--card2);border-radius:16px;padding:14px 16px}
.compose textarea{width:100%;min-height:132px;background:transparent;border:0;color:var(--ink);font:inherit;
 font-size:15px;resize:vertical;outline:none}
.compose input{width:100%;background:transparent;border:0;border-top:1px solid var(--line);padding-top:10px;
 color:var(--ink);font:inherit;font-size:13.5px;outline:none;margin-top:8px}
.acts{display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap}
.btn{border:0;border-radius:22px;padding:12px 22px;font:inherit;font-size:14.5px;font-weight:600;cursor:pointer;
 transition:transform .16s,background .16s}
.btn:hover{transform:translateY(-1px)}
.btn.pri{background:var(--acc);color:#fff}.btn.pri:hover{background:var(--acc2)}
.btn.sec{background:var(--card2);color:var(--ink)}
.pvbox{background:var(--bg);border-radius:16px;padding:16px;margin-top:14px}
"""


def _page(title: str, css_extra: str, body: str) -> str:
    return ('<!doctype html><html lang="uk"><head><meta charset="utf-8">'
            f'<title>{e(title)}</title>'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="theme-color" content="#17212b">'
            '<link rel="manifest" href="/manifest.json">'
            '<link rel="apple-touch-icon" href="/icon-192.png">'
            '<meta name="apple-mobile-web-app-capable" content="yes">'
            '<meta name="mobile-web-app-capable" content="yes">'
            '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
            f"<style>{_CSS}{css_extra}</style></head><body>{body}</body></html>")


_THEME_JS = r"""
<script>
(function(){const t=localStorage.getItem("cod_theme");if(t)document.documentElement.dataset.theme=t;
 window.toggleTheme=function(){const cur=document.documentElement.dataset.theme
  ||(matchMedia("(prefers-color-scheme:light)").matches?"light":"dark");
  const nx=cur==="dark"?"light":"dark";document.documentElement.dataset.theme=nx;localStorage.setItem("cod_theme",nx);
  document.querySelectorAll(".themeico").forEach(el=>el.textContent=nx==="dark"?"☾":"☀");};
 document.addEventListener("DOMContentLoaded",function(){const cur=document.documentElement.dataset.theme
  ||(matchMedia("(prefers-color-scheme:light)").matches?"light":"dark");
  document.querySelectorAll(".themeico").forEach(el=>el.textContent=cur==="dark"?"☾":"☀")});})();
</script>
"""

_KEY_JS = r"""
<script>
function key(){let k=localStorage.getItem("cod_key");if(!k){k=prompt("Введіть свій код доступу:")||"";if(k)localStorage.setItem("cod_key",k)}return k}
function paintLogin(){const b=document.getElementById("loginbtn");if(!b)return;
 const me=localStorage.getItem("cod_me");
 b.innerHTML=me?("👤 "+me):"Увійти";b.classList.toggle("on",!!me);
 b.title=me?"Натисніть, щоб вийти або змінити код":"Введіть код доступу";}
async function login(){const me=localStorage.getItem("cod_me");
 if(me){if(confirm("Ви увійшли як "+me+". Вийти?")){localStorage.removeItem("cod_key");localStorage.removeItem("cod_me");paintLogin()}return}
 const k=prompt("Введіть свій код доступу:");if(!k)return;
 const r=await fetch("/api/whoami",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key:k.trim()})});
 const j=await r.json();
 if(j.ok){localStorage.setItem("cod_key",k.trim());localStorage.setItem("cod_me",j.name);paintLogin();
  if(window.toast)toast("👤 Вітаю, "+j.name+"! Тепер можна відповідати клієнтам і робити розсилки")}
 else alert(j.error||"Невірний код")}
async function checkKey(){const k=localStorage.getItem("cod_key");if(!k){paintLogin();return}
 try{const r=await fetch("/api/whoami",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({key:k})});
  const j=await r.json();if(j.ok)localStorage.setItem("cod_me",j.name);else{localStorage.removeItem("cod_key");localStorage.removeItem("cod_me")}}catch(e){}
 paintLogin()}
document.addEventListener("DOMContentLoaded",checkKey);
async function api(path,body){body.key=key();
 const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
 let j={};try{j=await r.json()}catch(e){}
 if(r.status===403){localStorage.removeItem("cod_key");alert("Невірний код доступу")}
 return j}
</script>
"""



_SVG = {
    "dash": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 20.5h18"/><rect x="4.5" y="11" width="3.6" height="6.5" rx="1.2"/><rect x="10.2" y="5.5" width="3.6" height="12" rx="1.2"/><rect x="15.9" y="8.5" width="3.6" height="9" rx="1.2"/></svg>',
    "dlg": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 11.6a8.2 8.2 0 0 1-8.3 8.2 8.4 8.4 0 0 1-3.8-.9l-5 1.6 1.7-4.7a8.2 8.2 0 0 1 7.1-12.4 8.2 8.2 0 0 1 8.3 8.2z"/></svg>',
    "flow": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="4.5" cy="6" r="1.6"/><circle cx="4.5" cy="12" r="1.6"/><circle cx="4.5" cy="18" r="1.6"/><path d="M9 6h11M9 12h11M9 18h7"/></svg>',
    "bc": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 10.5v3a1 1 0 0 0 1 1H7l5.5 4v-13L7 9.5H4.5a1 1 0 0 0-1 1z"/><path d="M16.5 8.5a5 5 0 0 1 0 7"/><path d="M19.2 5.8a9 9 0 0 1 0 12.4"/></svg>',
}


def _ava(seed, letter: str, cls: str = "ava") -> str:
    n = sum(ord(c) for c in str(seed)) % 7
    return f'<span class="{cls} g{n}">{e((letter or "?")[:1].upper())}</span>'


def _nav(active: str) -> str:
    def b(href, ico, txt, k):
        return (f'<a class="tbtn lbl{" on" if k == active else ""}" href="{href}">'
                f'<span class="ico">{_SVG[k]}</span>{txt}</a>')
    return ('<span class="navtop">' + b("/dashboard.html", "", "Пульт", "dash")
            + b("/dialogs.html", "", "Діалоги", "dlg") + b("/flow.html", "", "Сценарій", "flow")
            + b("/broadcast.html", "", "Розсилка", "bc") + '</span>'
            + '<button class="tbtn lbl" id="loginbtn" onclick="login()">Увійти</button>'
            + '<button class="tbtn" onclick="toggleTheme()" title="Тема"><span class="themeico">☾</span></button>')


def _tabbar(active: str) -> str:
    def t(href, txt, k):
        return f'<a class="{"on" if k == active else ""}" href="{href}"><i>{_SVG[k]}</i>{txt}</a>'
    return ('<nav class="tabbar">' + t("/dashboard.html", "Пульт", "dash")
            + t("/dialogs.html", "Діалоги", "dlg") + t("/flow.html", "Сценарій", "flow")
            + t("/broadcast.html", "Розсилка", "bc") + '</nav>')


_STAGE = {"new": ("sd-wait", "збирає дані"), "phone": ("sd-wait", "дає телефон"), "name": ("sd-wait", "пише ім'я"),
          "city": ("sd-wait", "обирає місто"), "warehouse": ("sd-wait", "обирає відділення"),
          "upsell": ("sd-wait", "думає над курсом"), "review": ("sd-wait", "перевіряє підсумок"),
          "confirmed": ("sd-mid", "підтверджено"), "queued_crm": ("sd-mid", "їде в CRM"),
          "confirmed_crm": ("sd-ok", "у CRM, чекає ТТН"), "shipped": ("sd-mid", "в дорозі"),
          "arrived": ("sd-mid", "у відділенні"), "picked": ("sd-ok", "викуплено"), "done": ("sd-ok", "завершено"),
          "returned": ("sd-bad", "повернення"), "cancelled": ("sd-bad", "скасовано"),
          "lead_crm": ("sd-wait", "на прозвон")}


# ──────────────────────────────── ПУЛЬТ ────────────────────────────────
_DASH = r"""
<div class="top">
 <div class="brand">%%AVA%%<div><div class="nm">%%NAME%%</div>
  <div class="st" id="botst">%%BOTST%%</div></div></div>
 <span class="upd" id="upd">оновлення…</span>
 <div class="seg"><button class="on" onclick="setDays(1,this)">Сьогодні</button>
  <button onclick="setDays(7,this)">7 днів</button><button onclick="setDays(30,this)">30 днів</button></div>
 %%NAV%%
</div>
<main>
 <div class="cols c-hero">
  <div class="card hero">
   <span class="lab" id="hlab">Сьогодні заробили</span>
   <div class="big" id="hval">—</div>
   <div class="sub" id="hsub"></div>
   <div class="badges" id="hbadges"></div>
  </div>
  <div class="card d1"><div class="ttl">Живий ефір <span class="r" id="feedn"></span></div>
   <div class="feed" id="feed"><div class="ev"><span class="ic">⏳</span><div class="bb">слухаю ефір…</div></div></div></div>
 </div>
 <div class="kpis" id="kpis"></div>
 <div class="cols c-2">
  <div class="card d2"><div class="ttl">Воронка <span class="r" id="fnr"></span></div>
   <div class="fn" id="funnel"></div><p class="hint" id="fnhint"></p></div>
  <div class="card d3"><div class="ttl">A/B-тест · три Олі продають по-різному</div>
   <p class="hint top">Кожен новий клієнт випадково потрапляє до однієї з трьох Оль. Зелена крапка — краща в рядку,
    підсвічений рядок унизу — головний: скільки грошей приносить один зайшлий.</p>
   <div class="scroll-x" id="ab"></div><p class="hint" id="abhint"></p></div>
 </div>
 <div class="card d3" style="margin-top:14px"><div class="ttl">Скільки грошей доходить до каси
  <span class="r" id="mfr">когорта періоду</span></div>
 <div class="scroll-x"><table class="mf" id="mf"></table></div>
 <p class="hint" id="mfhint"></p></div>
<div class="card d4" style="margin-top:14px"><div class="ttl">Пульс · 14 днів <span class="r">підтверджені замовлення за день</span></div>
  <div class="pulse" id="pulse"></div></div>
 <div class="card p0 d4" style="margin-top:14px">
  <div class="ttl" style="padding:16px 20px 0;margin-bottom:10px">Останні замовлення <span class="r">клік — відкрити діалог</span></div>
  <div class="rows">%%ORDERS%%</div></div>
 <div class="statusbar" id="statusbar"></div>
 <div class="card d4" id="logcard" style="margin-top:14px;display:none"><div class="ttl">Хто що робив
  <span class="r">дії з пульта</span></div><div class="rows" id="log"></div></div>
</main>
<div id="toast"></div>
<script>
const INIT=%%INIT%%;
let DAYS=1,prevM=null,lastCid=null,unseen=0,lastUpd=Date.now();
const FN=[["bot_start","Зайшли",""],["phone_received","Телефон",""],["name_received","Ім'я",""],
 ["warehouse_received","Відділення",""],["lead_confirmed","Підтвердили","approve"],["crm_created","В CRM",""],
 ["ttn_sent","ТТН",""],["arrived_notified","Прибули",""],["picked_up","Забрали",""]];
const NB="\u00A0";
const grn=n=>Math.round(n).toLocaleString("uk-UA").replace(/[\s,\u00A0]/g,NB)+NB+"₴";
const plural=(n,f)=>{const a=Math.abs(n)%100,b=a%10;
 return f[(a>10&&a<20)?2:(b===1?0:(b>1&&b<5?1:2))]};
const pc=(a,b)=>b?(a/b*100):0;
const p0=x=>x.toFixed(0)+"%";
function up(el,to,fmt){const from=parseFloat(el.dataset.v||0);el.dataset.v=to;const t0=performance.now();
 function step(t){const k=Math.min(1,(t-t0)/620),v=from+(to-from)*(1-Math.pow(1-k,3));
  el.textContent=fmt(v);if(k<1)requestAnimationFrame(step)}
 requestAnimationFrame(step)}
function iso(ts){if(!ts)return null;const t=String(ts);
 const z=(t.indexOf("+")>10||t.indexOf("Z")>10)?t:t+"Z";const d=new Date(z);return isNaN(d)?null:d}
function ago(ts){const d=iso(ts);if(!d)return "";
 const s=Math.max(0,Math.round((Date.now()-d.getTime())/1000));
 if(s<60)return s+" с";if(s<3600)return Math.round(s/60)+" хв";if(s<86400)return Math.round(s/3600)+" год";return Math.round(s/86400)+" дн"}
function med(m){if(!m)return "—";return m<1?Math.round(m*60)+" сек":Math.round(m)+" хв"}
function dl(cur,prev,pp,fmt){if(prev==null||isNaN(prev))return "";const d=cur-prev;if(Math.abs(d)<0.5)return "";
 const c=d>0?"up":"dn",a=d>0?"↑":"↓";
 const t=pp?Math.abs(d).toFixed(0)+" п.п.":(prev?Math.abs(d/prev*100).toFixed(0)+"%":"");
 return t?`<i class="dl ${c}" title="минулий період: ${fmt?fmt(prev):prev}">${a} ${t}</i>`:""}
const KPI=[["in","Зайшли",""],["ap","Approve",""],["us","Апсейл на бандл",""],
 ["ch","Середній чек","acc"],["mg","Маржа з замовлення","acc"],["bo","Викуп","gr"]];
function buildKpis(){document.getElementById("kpis").innerHTML=KPI.map(function(a,i){
 return `<div class="kpi ${a[2]}" id="k_${a[0]}" style="animation-delay:${.04*i}s"><span class="k">${a[1]}</span>
  <span class="v" data-v="">—</span><span class="s"></span></div>`}).join("")}
function setK(id,v,fmt,sub,d,flash){const c=document.getElementById("k_"+id),b=c.querySelector(".v");
 const ch=b.dataset.v!==""&&parseFloat(b.dataset.v)!==v;up(b,v,fmt);c.querySelector(".s").textContent=sub;
 const o=c.querySelector(".dl");if(o)o.remove();if(d)c.insertAdjacentHTML("beforeend",d);
 if(flash&&ch){c.classList.remove("flash");void c.offsetWidth;c.classList.add("flash")}}
function render(d,anim){const m=d.m,A=d.ab,L=d.labels,P=d.prev||null;
 document.getElementById("hlab").textContent=DAYS===1?"Сьогодні заробили":`Заробили за ${DAYS} днів`;
 up(document.getElementById("hval"),m.revenue,grn);
 document.getElementById("hsub").textContent=`Маржа ~ ${grn(m.margin_total||0)} · з одного зайшлого ${grn(m.rpe)}`
  +(P?` · минулий період ${grn(P.revenue)}`:"");
 let bs=[];
 if(m.confirmed)bs.push(`<span class="badge acc">✅ ${m.confirmed} ${plural(m.confirmed,["підтвердження","підтвердження","підтверджень"])}</span>`);
 if(m.shipped)bs.push(`<span class="badge">📦 ${m.shipped} ${plural(m.shipped,["посилка","посилки","посилок"])} в дорозі</span>`);
 if(m.picked)bs.push(`<span class="badge gr">💰 ${m.picked} викупили</span>`);
 if(m.cancelled)bs.push(`<span class="badge rd">✖ ${m.cancelled} скасували</span>`);
 if(m.lead_to_crm)bs.push(`<span class="badge">📞 ${m.lead_to_crm} ${plural(m.lead_to_crm,["лід","ліди","лідів"])} на прозвон</span>`);
 const sk=streak(m);if(sk)bs.unshift(`<span class="badge gr">${sk}</span>`);
 document.getElementById("hbadges").innerHTML=bs.join("");
 const pv=k=>P?P[k]:null;
 setK("in",m.entered,v=>Math.round(v),"людей за період",dl(m.entered,pv("entered"),false,v=>Math.round(v)));
 setK("ap",m.approve,p0,`${m.confirmed} з ${m.entered} зайшлих`,dl(m.approve,pv("approve"),true,p0));
 setK("us",m.upsell_cvr,p0,m.upsell_shown?`${m.upsell_accepted} з ${m.upsell_shown} взяли курс`:"ще не показували",
  m.upsell_shown?dl(m.upsell_cvr,pv("upsell_cvr"),true,p0):"");
 setK("ch",m.avg_check,grn,"по підтверджених",dl(m.avg_check,pv("avg_check"),false,grn),true);
 setK("mg",m.avg_margin==null?0:m.avg_margin,v=>m.avg_margin==null?"—":grn(v),"чек мінус собівартість",
  (m.avg_margin!=null&&P&&P.avg_margin!=null)?dl(m.avg_margin,P.avg_margin,false,grn):"",true);
 if(m.shipped)setK("bo",m.buyout,p0,`${m.picked} з ${m.shipped} відправлених`,dl(m.buyout,pv("buyout"),true,p0));
 else setK("bo",0,()=>"—","ще немає відправок","");
 const base=m.funnel.bot_start||1;let h="",prevV=base;
 for(const F of FN){const k=F[0],lab=F[1],tag=F[2];const v=m.funnel[k]||0,drop=prevV>v?prevV-v:0;
  h+=`<div class="fr${drop?" drop":""}"><span class="l">${lab}${tag?`<em>${tag}</em>`:""}</span>
   <span class="trk"><i style="width:${pc(v,base).toFixed(0)}%"></i></span>
   <span class="n">${v}</span><span class="p">${drop?"−"+drop:p0(pc(v,base))}</span></div>`;
  if(v)prevV=v;
  if(k==="lead_confirmed"){const us=m.upsell_shown,ua=m.upsell_accepted;
   h+=`<div class="fr up"><span class="l">↳ апсейл</span><span class="trk"><i style="width:${pc(ua,us||1).toFixed(0)}%"></i></span>
    <span class="n">${ua}/${us}</span><span class="p">${us?p0(m.upsell_cvr):"—"}</span></div>`}}
 document.getElementById("funnel").innerHTML=h;
 document.getElementById("fnr").textContent=`${m.entered} → ${m.confirmed}`;
 document.getElementById("fnhint").textContent=
  `Праворуч — скільки людей втратили на кроці. Медіана до підтвердження ${med(m.median_min)}.`;
 const vs=Object.keys(A),enough=vs.filter(v=>A[v].entered>=200);
 const best=enough.length?enough.reduce((a,b)=>A[b].rpe>A[a].rpe?b:a,enough[0]):null;
 const R=[["Зайшли",x=>x.entered,x=>String(x.entered),0],
  ["Approve",x=>x.entered?x.approve:null,x=>x.entered?p0(x.approve)+`<s>${x.confirmed}/${x.entered}</s>`:"—",0],
  ["Апсейл на бандл",x=>x.upsell_shown?x.upsell_cvr:null,x=>x.upsell_shown?p0(x.upsell_cvr)+`<s>${x.upsell_accepted}/${x.upsell_shown}</s>`:"—",0],
  ["Середній чек",x=>x.confirmed?x.avg_check:null,x=>x.confirmed?grn(x.avg_check):"—",0],
  ["Маржа з замовлення",x=>x.avg_margin,x=>x.avg_margin==null?"—":grn(x.avg_margin),0],
  ["Викуп",x=>x.shipped?x.buyout:null,x=>x.shipped?p0(x.buyout)+`<s>${x.picked}/${x.shipped}</s>`:"—",0],
  ["Грошей з одного зайшлого",x=>x.entered?x.rpe:null,x=>x.entered?grn(x.rpe):"—",1]];
 let t=`<table class="ab"><thead><tr><th></th>`+vs.map(v=>
  `<th>${v==="A"?"🅐":v==="B"?"🅑":"🅒"} ${L[v]||v} ${v===best?'<span class="crown">👑</span>':""}<span>школа ${v}</span></th>`).join("")+`</tr></thead><tbody>`;
 for(const row of R){const lab=row[0],val=row[1],fmt=row[2],keyrow=row[3];
  const cs=vs.map(v=>val(A[v])),nums=cs.filter(x=>x!=null);
  const mx=nums.length>1?Math.max.apply(null,nums):null;
  const uniq=mx!=null&&nums.filter(x=>x===mx).length===1;
  t+=`<tr class="${keyrow?"key":""}"><td>${lab}</td>`+vs.map((v,i)=>
   `<td class="${(uniq&&cs[i]===mx&&mx>0)?"w":""}">${fmt(A[v])}</td>`).join("")+`</tr>`}
 t+=`<tr class="pg"><td>Даних для вердикту</td>`+vs.map(v=>{const n=A[v].entered;
  return `<td><span class="pgb"><i style="width:${Math.min(100,n/2)}%"></i></span>${n}/200</td>`}).join("")+`</tr></tbody></table>`;
 document.getElementById("ab").innerHTML=t;
 document.getElementById("abhint").textContent=best
  ? `Лідирує школа ${best} — вирішуємо по останньому рядку.`
  : "Поки замало даних: вердикт від 200 лідів на школу, до того цифри стрибають.";
 renderMoney(m);
 if(anim&&prevM&&m.confirmed>prevM.confirmed)party();
 prevM=m}
function renderMoney(m){const M=m.money;if(!M)return;
 const cv=(a,b)=>b?(a/b*100):0;
 const cell=(x,key)=>x&&x[key]!=null?grn(x[key]):'<span class="muted">—</span>';
 const R=[
  ["Зайшли","sd-wait",{n:M.entered.n},null,""],
  ["Підтвердили","sd-mid",M.confirmed,cv(M.confirmed.n,M.entered.n),"approve"],
  ["Відправили","sd-mid",M.shipped,cv(M.shipped.n,M.confirmed.n),"від підтверджених"],
  ["Викупили — гроші в касі","sd-ok",M.picked,cv(M.picked.n,M.shipped.n),"викуп"],
  ["Не забрали","sd-bad",M.returned,cv(M.returned.n,M.shipped.n),"повернення"]];
 let h=`<thead><tr><th>Етап</th><th>Замовлень</th><th>Конверсія</th><th>Гроші</th><th>Сер. чек</th><th>Маржа</th><th>Маржа / зам.</th></tr></thead><tbody>`;
 for(const r of R){const lab=r[0],dot=r[1],x=r[2],conv=r[3],cnote=r[4];
  const cls=lab.indexOf("Викупили")===0?"cash":(lab==="Не забрали"?"lost":"");
  if(lab==="Не забрали"&&(!x||!x.n))continue;
  h+=`<tr class="${cls}"><td><span class="stg"><span class="dotc ${dot}"></span>${lab}</span></td>
   <td><b>${x.n||0}</b></td>
   <td>${conv==null?'<span class="muted">—</span>':`<span class="cv ${conv<60?"low":""}">${conv.toFixed(0)}%</span> <span class="muted">${cnote}</span>`}</td>
   <td>${x.sum!=null&&x.n?grn(x.sum):'<span class="muted">—</span>'}</td>
   <td>${x.avg&&x.n?grn(x.avg):'<span class="muted">—</span>'}</td>
   <td>${x.n?cell(x,"margin"):'<span class="muted">—</span>'}</td>
   <td>${x.n?cell(x,"margin_avg"):'<span class="muted">—</span>'}</td></tr>`}
 h+="</tbody>";
 document.getElementById("mf").innerHTML=h;
 const P=M.picked,C=M.confirmed;
 const moneyThrough=C.sum?cv(P.sum,C.sum):0;
 document.getElementById("mfhint").innerHTML=
  `Це <b>когорта періоду</b>: замовлення, що прийшли за ці дні, і що з ними сталося. `
  +(C.n?`З підтверджених грошей до каси дійшло <b>${moneyThrough.toFixed(0)}%</b>. `:"")
  +(P.margin!=null&&M.entered.n?`Чистими з одного зайшлого: <b>${grn(P.margin/M.entered.n)}</b>.`:"")
  +(DAYS===1?" За сьогодні викуп ще визріває — дивіться 7 і 30 днів.":"")}
function renderStatus(j){const S=j.settings||{},push=S.push_orders!=="0";
 const b=document.getElementById("statusbar");if(!b)return;
 b.innerHTML=`<div class="chip ${S.bot_enabled==="0"?"bad":"ok"}">${S.bot_enabled==="0"?"● бот вимкнено":"● бот працює"}</div>
  <div class="chip tog" onclick="togglePush()"><span class="sw ${push?"on":""}"><i></i></span>Пуш у Telegram про кожне замовлення</div>`}
const ACT={reply:["💬","відповів клієнту"],back_to_bot:["↩","повернув чат боту"],
 broadcast:["📣","запустив розсилку"],edit_text:["✏️","змінив текст"],reset_text:["↩","повернув стандартний текст"],
 setting:["⚙️","змінив налаштування"]};
async function loadLog(){try{const j=await(await fetch("/api/log")).json();
 if(!j.ok||!j.items.length)return;
 document.getElementById("logcard").style.display="";
 document.getElementById("log").innerHTML=j.items.map(x=>{const[ic,tx]=ACT[x.action]||["·",x.action];
  return `<div class="row"><div class="mid"><div class="n1"><b>${ic} ${x.actor}</b> <span class="n2">${tx}</span></div>
   <div class="n2">${(x.detail||x.target||"").slice(0,70)}</div></div>
   <div class="rt"><div class="tm">${x.ts_utc.slice(11,16)}</div></div></div>`}).join("")}catch(e){}}
async function togglePush(){const cur=document.querySelector(".statusbar .sw").classList.contains("on");
 const j=await api("/api/setting",{name:"push_orders",value:cur?"0":"1"});
 if(j.ok){document.querySelector(".statusbar .sw").classList.toggle("on");
  toast(cur?"🔕 пуші вимкнено":"🔔 пуші увімкнено — писатиму сюди про кожне замовлення")}}
function streak(m){if(DAYS!==1)return "";
 const today=new Date().toISOString().slice(0,10);let H={};
 try{H=JSON.parse(localStorage.getItem("cod_days")||"{}")}catch(e){}
 H[today]={c:m.confirmed,r:Math.round(m.revenue)};localStorage.setItem("cod_days",JSON.stringify(H));
 let s=0;const d=new Date();
 for(;;){const k=d.toISOString().slice(0,10);if(H[k]&&H[k].c>0){s++;d.setDate(d.getDate()-1)}else break}
 const best=Math.max.apply(null,Object.values(H).map(x=>x.r||0).concat([0]));
 if(best>0&&m.revenue>=best&&m.revenue>0)return "🏆 рекордний день";
 return s>1?`🔥 ${s} дні поспіль із замовленнями`:""}
function renderPulse(D){if(!D)return;if(window.innerWidth<560)D=D.slice(-7);
 const mx=Math.max.apply(null,D.map(x=>x.c).concat([1]));
 document.getElementById("pulse").innerHTML=D.map((x,i)=>
  `<div class="pd ${i===D.length-1?"today hi":(x.c?"hi":"")}" title="${x.d}: ${x.c} підтверджень, ${grn(x.r)}">
   <span class="pv">${x.c||""}</span><span class="pcol"><i style="height:${x.c?Math.max(7,x.c/mx*88):0}px"></i></span>
   <span class="pl">${x.d.slice(3)}</span></div>`).join("")}
const EV={bot_start:["👋","Новий відвідувач",0],lead_confirmed:["✅","Підтвердив замовлення",1],
 upsell_accepted:["💛","Взяли курс 60 днів",1],ttn_sent:["📦","Посилка відправлена",0],
 arrived_notified:["📍","Посилка у відділенні",0],picked_up:["💰","Викупили — гроші в касі",1],
 cancelled_before_ship:["✖️","Скасував замовлення",0]};
function renderFeed(F){if(!F||!F.length)return;
 document.getElementById("feedn").textContent=F.length+" "+plural(F.length,["подія","події","подій"]);
 if(window.innerWidth<640)F=F.slice(0,6);
 document.getElementById("feed").innerHTML=F.map(f=>{const E=EV[f.name]||["·",f.name,0];
  const who=f.first_name?` · <b>${f.first_name}</b>`:"";
  const pr=(f.price_uah&&(f.name==="lead_confirmed"||f.name==="picked_up"||f.name==="upsell_accepted"))?` · ${grn(f.price_uah)}`:"";
  return `<div class="ev ${E[2]?"money":""}"><span class="ic">${E[0]}</span>
   <div class="bb">${E[1]}${who}${pr}<span class="t">${ago(f.ts_utc)}</span></div></div>`}).join("")}
function party(){const C=["#3390ec","#64baf0","#4dcd5e","#e8a33d","#ef5350","#ffffff"];
 for(let i=0;i<70;i++){const el=document.createElement("div");el.className="cf";
  el.style.left=Math.random()*100+"vw";el.style.background=C[i%C.length];
  el.style.animationDuration=(2.1+Math.random()*2)+"s";el.style.animationDelay=(Math.random()*.5)+"s";
  document.body.appendChild(el);setTimeout(()=>el.remove(),5200)}}
function toast(h){const t=document.getElementById("toast");t.innerHTML=`<div class="toast">${h}</div>`;
 setTimeout(()=>t.innerHTML="",6500)}
function setDays(d,b){DAYS=d;document.querySelectorAll(".seg button").forEach(x=>x.classList.remove("on"));
 b.classList.add("on");prevM=null;if(INIT[d])render(INIT[d],false);refresh()}
async function refresh(){try{const r=await fetch("/api/stats?days="+DAYS),j=await r.json();
 if(!j.ok)return;render({m:j.m,ab:j.ab,labels:j.labels,prev:j.prev},true);renderPulse(j.daily);renderFeed(j.feed);
 if(j.last_confirmed){if(lastCid&&j.last_confirmed.id!==lastCid){const c=j.last_confirmed;
   toast(`💰 <b>Замовлення №${c.id}</b> · ${grn(c.price_uah||0)} · ${(c.np_city_name||"").replace("м. ","")}`);
   unseen++;document.title="("+unseen+") "+document.title.split(") ").pop()}
  lastCid=j.last_confirmed.id}
 renderStatus(j);loadLog();
 lastUpd=Date.now();const s=document.getElementById("botst");
 s.textContent=(j.settings&&j.settings.bot_enabled==="0")?"бот вимкнено":"онлайн · продає зараз";
 s.classList.toggle("off",j.settings&&j.settings.bot_enabled==="0")}
 catch(e){const s=document.getElementById("botst");s.textContent="немає зв'язку з ботом";s.classList.add("off")}}
setInterval(function(){const s=Math.round((Date.now()-lastUpd)/1000);
 document.getElementById("upd").textContent=s<8?"оновлено щойно":"оновлено "+(s<60?s+" с":Math.round(s/60)+" хв")+" тому"},2500);
buildKpis();render(INIT[1],false);refresh();setInterval(refresh,25000);
document.addEventListener("visibilitychange",function(){if(!document.hidden){refresh();unseen=0;
 document.title=document.title.split(") ").pop()}});
</script>
"""


def render_dashboard(store: Store, out: Path, variants: list[str], labels: dict, title: str, default_set: str = "s1") -> Path:
    init = {d: {"m": metrics(store, d, None, default_set), "ab": ab(store, d, variants, default_set), "labels": labels}
            for d in (1, 7, 30)}
    hh = health(store)
    rows = []
    for r in store.c.execute(
            "SELECT o.id, o.chat_id, o.variant, o.set_code, o.price_uah, o.stage, COALESCE(o.name, c.first_name), o.updated_utc "
            "FROM orders o JOIN chats c ON c.tg_user_id=o.chat_id ORDER BY o.updated_utc DESC LIMIT 10").fetchall():
        dot, txt = _STAGE.get(r[5], ("sd-mid", r[5]))
        nm = r[6] or "Без імені"
        vtag = f'<span class="tag">{e(r[2])}</span>' if r[2] else ""
        rows.append(f'<a class="row" href="/dialogs.html#u{r[1]}">{_ava(r[1], nm)}'
                    f'<div class="mid"><div class="n1"><b>{e(nm)}</b>'
                    f'<span class="tag">№{r[0]}</span>{vtag}</div>'
                    f'<div class="n2"><span class="st-dot {dot}"></span>{e(txt)}'
                    f'{" · " + e(r[3]) if r[3] else ""}</div></div>'
                    f'<div class="rt"><div class="sum">{grn(r[4]) if r[4] else "—"}</div>'
                    f'<div class="tm">{_kyiv_hm(r[7])}</div></div></a>')
    slug = title.split("·")[0].strip() or "Olavita"
    botst = "онлайн · продає зараз" if hh["bot_enabled"] else "бот вимкнено"
    body = (_DASH.replace("%%AVA%%", _ava("olya", slug))
            .replace("%%NAME%%", e(slug))
            .replace("%%BOTST%%", e(botst))
            .replace("%%NAV%%", _nav("dash"))
            .replace("%%ORDERS%%", "".join(rows) or '<div class="row"><div class="mid n2">Замовлень ще немає</div></div>')
            .replace("%%INIT%%", json.dumps(init, ensure_ascii=False).replace("</", "<\\/")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page(title, "", _THEME_JS + _KEY_JS + body + _tabbar("dash")), encoding="utf-8")
    return out


# ──────────────────────────────── ДІАЛОГИ ────────────────────────────────
_TAG_RX = _re.compile(r"<[^>]+>")
_SERVICE_RX = _re.compile(r"^[a-z_]{3,30}\(\{.*\}\)$", _re.DOTALL)


def _uah(n) -> str:
    return f"{int(round(n or 0)):,}".replace(",", "\u00a0") + "\u00a0₴"


def _kyiv_hm(ts: str | None) -> str:
    """UTC ISO → 'HH:MM' за Києвом (UTC+3 влітку/взимку — фіксовано +3 як у боті)."""
    if not ts:
        return ""
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return (d.astimezone(timezone(timedelta(hours=3)))).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return ts[11:16]


def _plain(t: str) -> str:
    return _TAG_RX.sub("", t or "").strip()


_DLG = r"""
<div class="top">
 <div class="brand">%%AVA%%<div><div class="nm">%%NAME%%</div><div class="st">діалоги клієнтів</div></div></div>
 <span class="upd">%%UPD%%</span><div style="margin-left:auto"></div>
 %%NAV%%
</div>
<div class="tgwrap" id="wrap">
 <div class="list">
  <div class="search"><input id="q" placeholder="Пошук за іменем або текстом" oninput="filter()">
   <div class="fchips"><button class="fc on" data-f="all" onclick="setF(this)">Всі</button>
    <button class="fc" data-f="wait" onclick="setF(this)">Чекають</button>
    <button class="fc" data-f="mine" onclick="setF(this)">У мене</button></div></div>
  <div class="chats" id="chats"></div>
 </div>
 <div class="conv" id="conv">
  <div class="empty">Виберіть діалог зліва —<br>побачите всю переписку і зможете відповісти від себе.</div>
 </div>
</div>
<script>
const CH=%%CHATS%%;
let cur=null,ME=localStorage.getItem("cod_me")||"";
const grn=n=>Math.round(n).toLocaleString("uk-UA").replace(/[\s,\u00A0]/g,"\u00A0")+"\u00A0₴";
function ava(id,nm,cls){let s=0;const t=String(id);for(let i=0;i<t.length;i++)s+=t.charCodeAt(i);
 return `<span class="${cls||"ava"} g${s%7}">${(nm||"?")[0].toUpperCase()}</span>`}
function esc(s){return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
const TZ="Europe/Kyiv";
function iso(ts){if(!ts)return null;const t=String(ts);
 const z=(t.indexOf("+")>10||t.indexOf("Z")>10)?t:t+"Z";const d=new Date(z);return isNaN(d)?null:d}
function tm(ts){const d=iso(ts);return d?d.toLocaleTimeString("uk-UA",{hour:"2-digit",minute:"2-digit",timeZone:TZ}):""}
function kd(d){return d.toLocaleDateString("sv-SE",{timeZone:TZ})}
function dayLab(ts){const d=iso(ts);if(!d)return "";
 const k=kd(d),t=kd(new Date()),y=kd(new Date(Date.now()-864e5));
 if(k===t)return "Сьогодні";if(k===y)return "Вчора";
 return d.toLocaleDateString("uk-UA",{day:"2-digit",month:"long",timeZone:TZ})}
let FLT="all";
function setF(b){FLT=b.dataset.f;document.querySelectorAll(".fc").forEach(x=>x.classList.remove("on"));
 b.classList.add("on");renderList(document.getElementById("q").value)}
function waiting(c){const lm=c.msgs.length?c.msgs[c.msgs.length-1]:null;return !!lm&&lm.r==="u"}
function renderList(f){const q=(f||"").toLowerCase();
 const items=CH.filter(c=>(!q||(c.nm+" "+(c.un||"")+" "+c.msgs.map(m=>m.t).join(" ")).toLowerCase().indexOf(q)>=0)
  &&(FLT==="all"||(FLT==="wait"&&waiting(c))||(FLT==="mine"&&c.mode==="human")));
 document.getElementById("chats").innerHTML=items.map(c=>{
  const lm=c.msgs.length?c.msgs[c.msgs.length-1]:{t:"",r:"a",ts:c.last};
  const wait=lm.r==="u";
  return `<div class="ch ${cur===c.id?"on":""}" onclick="open_(${c.id})">${ava(c.id,c.nm,"ava")}
   <div class="m"><div class="r1"><span class="nm">${esc(c.nm)}</span><span class="tm">${tm(lm.ts||c.last)}</span></div>
   <div class="r1"><span class="pv">${lm.r==="a"?"↩ ":""}${esc(lm.t.slice(0,60))}</span>
   ${c.mode==="human"?'<span class="bdg hum">я</span>':(wait?'<span class="bdg">!</span>':"")}</div></div></div>`}).join("")
  ||'<div class="empty" style="padding:24px;font-size:13px">Нічого не знайшлось</div>'}
function filter(){renderList(document.getElementById("q").value)}
function open_(id){cur=id;const c=CH.find(x=>x.id===id);if(!c)return;
 document.getElementById("wrap").classList.add("open");
 let h=`<div class="chead"><button class="tbtn back" onclick="closeConv()">‹</button>${ava(c.id,c.nm,"ava")}
  <div><div class="nm">${esc(c.nm)}</div><div class="st">${c.un?"@"+esc(c.un)+" · ":""}${c.order?("замовлення №"+c.order.id+" · "+esc(c.order.stage)):"без замовлення"} ${c.mode==="human"?"· <b>ви ведете чат</b>":"· бот веде чат"}</div></div>
  <div style="margin-left:auto"><button class="tbtn lbl" onclick="giveBack(${c.id})">↩ боту</button></div></div>
  <div class="msgs" id="msgs">`;
 let lastDay="";
 for(const m of c.msgs){const d=dayLab(m.ts);
  if(d!==lastDay){h+=`<div class="day">${d}</div>`;lastDay=d}
  const mgr=m.r==="a"&&m.t.charAt(0)==="["&&m.t.indexOf("]")>0;
  const who=mgr?`<span class="who">${esc(m.t.slice(1,m.t.indexOf("]")))}</span>`:"";
  const txt=mgr?m.t.slice(m.t.indexOf("]")+1).trim():m.t;
  h+=`<div class="m ${m.r==="u"?"i":"o"}">${who}${esc(txt)}<span class="mt">${tm(m.ts)}</span></div>`}
 h+=`</div><div class="cst" id="cst">Ваша відповідь ставить бота на паузу в цьому чаті</div>
  <div class="comp"><textarea id="inp" rows="1" placeholder="Написати повідомлення…"
   oninput="grow(this)" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}"></textarea>
   <button class="send" onclick="send()">➤</button></div>`;
 document.getElementById("conv").innerHTML=h;
 const M=document.getElementById("msgs");M.scrollTop=M.scrollHeight;
 renderList(document.getElementById("q").value)}
function closeConv(){document.getElementById("wrap").classList.remove("open")}
function grow(t){t.style.height="auto";t.style.height=Math.min(120,t.scrollHeight)+"px"}
async function send(){const i=document.getElementById("inp"),t=i.value.trim();if(!t||!cur)return;
 const j=await api("/api/reply",{chat_id:cur,text:t});
 if(j.ok){const c=CH.find(x=>x.id===cur),ts=new Date().toISOString().slice(0,19);
  c.msgs.push({r:"a",t:"[ви] "+t,ts:ts});c.mode="human";
  const M=document.getElementById("msgs");
  M.insertAdjacentHTML("beforeend",`<div class="m o"><span class="who">ви</span>${esc(t)}<span class="mt">${tm(ts)}</span></div>`);
  M.scrollTop=M.scrollHeight;i.value="";grow(i);
  document.getElementById("cst").textContent="✓ надіслано · чат закріплено за вами, бот тут на паузі";renderList()}
 else document.getElementById("cst").textContent="⚠️ "+(j.error||"не вдалось надіслати")}
async function giveBack(id){const j=await api("/api/close",{chat_id:id});
 if(j.ok){const c=CH.find(x=>x.id===id);c.mode="bot";c.who=null;
  document.getElementById("cst").textContent="↩ чат повернуто боту";renderList()}}
renderList();
if(location.hash.indexOf("#u")===0)open_(parseInt(location.hash.slice(2)));
else if(CH.length&&window.innerWidth>860)open_(CH[0].id);
</script>
"""


def render_dialogs(store: Store, out: Path, title: str, limit_chats: int = 40, limit_msgs: int = 80) -> Path:
    chats = []
    for ch in store.c.execute(
            """SELECT c.tg_user_id, c.first_name, c.username, c.name, c.variant, c.mode,
                      MAX(m.ts_utc) AS last_ts, COUNT(m.id) AS n
               FROM chats c JOIN messages m ON m.chat_id = c.tg_user_id
               GROUP BY c.tg_user_id ORDER BY last_ts DESC LIMIT ?""", (limit_chats,)).fetchall():
        ch = dict(ch)
        try:
            ch["assignee"] = store.c.execute("SELECT assignee FROM chats WHERE tg_user_id=?", (ch["tg_user_id"],)).fetchone()[0]
        except Exception:  # noqa: BLE001
            ch["assignee"] = None
        o = store.c.execute("SELECT id, set_code, stage FROM orders WHERE chat_id=? ORDER BY id DESC LIMIT 1",
                            (ch["tg_user_id"],)).fetchone()
        msgs = [{"r": "u" if m["role"] == "user" else "a", "t": _plain(m["content"])[:900], "ts": m["ts_utc"][:19]}
                for m in reversed(store.c.execute(  # службові виклики інструментів відсіюємо нижче
                    "SELECT role, content, ts_utc FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                    (ch["tg_user_id"], limit_msgs)).fetchall())]
        msgs = [m for m in msgs if m["t"] and not _SERVICE_RX.match(m["t"])]
        if not msgs:
            continue
        chats.append({"id": ch["tg_user_id"], "nm": ch["name"] or ch["first_name"] or "Без імені",
                      "un": ch["username"], "v": ch["variant"], "mode": ch["mode"],
                      "who": ch.get("assignee"),
                      "last": (ch["last_ts"] or "")[:19], "n": ch["n"],
                      "order": ({"id": o["id"], "set": o["set_code"],
                                 "stage": _STAGE.get(o["stage"], ("", o["stage"]))[1]} if o else None),
                      "msgs": msgs})
    slug = title.split("·")[0].strip() or "Olavita"
    body = (_DLG.replace("%%AVA%%", _ava("olya", slug)).replace("%%NAME%%", e(slug))
            .replace("%%UPD%%", datetime.now().strftime("%d.%m %H:%M")).replace("%%NAV%%", _nav("dlg"))
            .replace("%%CHATS%%", json.dumps(chats, ensure_ascii=False).replace("</", "<\\/")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page(f"{title} · діалоги", _MSG_CSS, _THEME_JS + _KEY_JS + body + _tabbar("dlg")), encoding="utf-8")
    return out


# ──────────────────────────────── РОЗСИЛКА ────────────────────────────────
_BC = r"""
<div class="top">
 <div class="brand">%%AVA%%<div><div class="nm">%%NAME%%</div><div class="st">розсилка по базі</div></div></div>
 <div style="margin-left:auto"></div>%%NAV%%
</div>
<main style="max-width:760px">
 <div class="card"><div class="ttl">Кому надіслати</div>
  <div class="seglist" id="segs"><div class="hint" style="margin:0">завантажую сегменти…</div></div></div>
 <div class="card d1" style="margin-top:14px"><div class="ttl">Повідомлення</div>
  <div class="compose"><textarea id="txt" maxlength="3500" placeholder="Напишіть так, ніби пишете одній клієнтці — від імені Олі…" oninput="preview()"></textarea>
   <input id="photo" placeholder="URL фото (не обов'язково, https://…)"></div>
  <div class="acts"><button class="btn pri" onclick="go()">Надіслати ➤</button>
   <button class="btn sec" onclick="dry()">Перевірити охоплення</button>
   <span class="hint" id="st" style="margin:0"></span></div>
  <div class="pvbox"><div class="ttl" style="margin-bottom:10px">Як побачить клієнт</div>
   <div class="msgs" style="padding:0;gap:3px;overflow:visible"><div class="m o" id="pvm">…<span class="mt">зараз</span></div></div></div>
 </div>
 <div class="card d2" style="margin-top:14px"><div class="ttl">Історія</div>
  <div class="scroll-x" id="hist"><div class="hint" style="margin:0">—</div></div></div>
</main>
<script>
function esc(s){return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function seg(){const c=document.querySelector('input[name=seg]:checked');return c?c.value:null}
function preview(){const t=document.getElementById("txt").value||"…";
 document.getElementById("pvm").innerHTML=esc(t)+'<span class="mt">зараз</span>'}
async function loadSegs(){const j=await api("/api/segments",{});if(!j.ok)return;
 document.getElementById("segs").innerHTML=Object.entries(j.segments).map(function(kv,i){
  return `<label class="sgi"><input type="radio" name="seg" value="${kv[0]}" ${i===0?"checked":""}>
   <span class="t">${kv[1].label}</span><span class="c">${kv[1].count}</span></label>`}).join("")}
async function dry(){const j=await api("/api/broadcast",{segment:seg(),text:document.getElementById("txt").value||"-",dry:1});
 document.getElementById("st").textContent=j.ok?`отримають ${j.total} чол.`:("⚠️ "+(j.error||""))}
async function go(){const t=document.getElementById("txt").value.trim();if(!t){alert("Порожній текст");return}
 const d=await api("/api/broadcast",{segment:seg(),text:t,dry:1});
 if(!d.ok){document.getElementById("st").textContent="⚠️ "+d.error;return}
 if(!confirm(`Надіслати ${d.total} людям? Скасувати вже не можна.`))return;
 const j=await api("/api/broadcast",{segment:seg(),text:t,photo_url:document.getElementById("photo").value.trim()});
 document.getElementById("st").textContent=j.ok?`🚀 пішла — №${j.broadcast_id}, ${j.total} отримувачів`:("⚠️ "+j.error);
 if(j.ok)setTimeout(loadHist,1200)}
async function loadHist(){const j=await api("/api/broadcasts",{});if(!j.ok||!j.items.length)return;
 document.getElementById("hist").innerHTML='<table class="ab"><thead><tr><th>№</th><th>Коли</th><th>Сегмент</th><th>Текст</th><th>Надіслано</th><th>Блок</th><th></th></tr></thead><tbody>'
 +j.items.map(x=>`<tr><td>${x.id}</td><td>${x.ts_utc.slice(5,16).replace("T"," ")}</td><td>${x.segment}</td>
  <td style="white-space:normal">${esc(x.text.slice(0,50))}</td><td>${x.sent}/${x.total}</td><td>${x.blocked}</td>
  <td>${x.state==="done"?"✅":"⏳"}</td></tr>`).join("")+"</tbody></table>"}
loadSegs();loadHist();setInterval(loadHist,10000);preview();
</script>
"""


def render_broadcast(out: Path, title: str) -> Path:
    slug = title.split("·")[0].strip() or "Olavita"
    body = _BC.replace("%%AVA%%", _ava("olya", slug)).replace("%%NAME%%", e(slug)).replace("%%NAV%%", _nav("bc"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page(f"{title} · розсилка", _MSG_CSS + _BC_CSS, _THEME_JS + _KEY_JS + body + _tabbar("bc")), encoding="utf-8")
    return out


# ──────────────────────────────── СЦЕНАРІЙ ────────────────────────────────
_FLOW_CSS = r"""
.vpick{display:flex;gap:6px;background:var(--card2);border-radius:12px;padding:4px;margin-bottom:14px;flex-wrap:wrap}
.vpick button{flex:1;min-width:110px;border:0;background:transparent;color:var(--sub);font:inherit;font-size:13.5px;
 font-weight:600;padding:9px 10px;border-radius:9px;cursor:pointer;transition:color .16s}
.vpick button.on{background:var(--acc);color:#fff}
.stp{position:relative;padding-left:46px;margin-bottom:12px}
.stp::before{content:"";position:absolute;left:17px;top:34px;bottom:-12px;width:2px;background:var(--line)}
.stp:last-child::before{display:none}
.stp .num{position:absolute;left:0;top:0;width:36px;height:36px;border-radius:50%;background:var(--card2);
 display:grid;place-items:center;font-size:16px;border:2px solid var(--bg)}
.stp .hd{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;margin-bottom:7px}
.stp .hd b{font-size:15px;font-weight:600}
.stp .when{font-size:12px;color:var(--sub);background:var(--card2);border-radius:20px;padding:2px 9px}
.stp .bub{background:var(--out);color:var(--outink);border-radius:14px 14px 14px 5px;padding:9px 13px 8px;
 font-size:14px;line-height:1.42;white-space:pre-wrap;max-width:min(100%,620px);box-shadow:0 1px 1px rgba(0,0,0,.14)}
.stp .note{font-size:12.5px;color:var(--sub);margin-top:7px;line-height:1.5}
.stp .edits{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}
.ebtn{border:1px solid var(--line);background:var(--card2);color:var(--acc);border-radius:18px;padding:6px 13px;
 font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;transition:background .16s}
.ebtn:hover{background:var(--hover)}
.ebtn.ed{color:var(--yellow)}
.edit{background:var(--card2);border-radius:14px;padding:12px 14px;margin-top:9px}
.edit .lab{font-size:11.5px;color:var(--sub);text-transform:uppercase;letter-spacing:.05em;font-weight:600;margin-bottom:7px}
.edit textarea{width:100%;min-height:96px;background:var(--card);border:0;border-radius:11px;padding:11px 13px;
 color:var(--ink);font:inherit;font-size:14.5px;resize:vertical;outline:none;line-height:1.45}
.edit .row2{display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
.edit .msg{font-size:12.5px;color:var(--sub);flex:1}
.edit .msg.err{color:var(--red)}
.edit .msg.ok{color:var(--green)}
.mini{border:0;border-radius:18px;padding:9px 16px;font:inherit;font-size:13.5px;font-weight:600;cursor:pointer}
.mini.pri{background:var(--acc);color:#fff}.mini.gh{background:transparent;color:var(--sub)}
.objs{display:flex;flex-direction:column;gap:2px}
.obj{padding:11px 12px;border-radius:12px;transition:background .15s}
.obj:hover{background:var(--hover)}
.obj .q{font-size:13.5px;font-weight:600;margin-bottom:4px}
.obj .a{font-size:13.5px;color:var(--sub);line-height:1.45}
.edited{display:inline-block;font-size:10.5px;font-weight:700;color:var(--yellow);background:rgba(232,163,61,.14);
 border-radius:6px;padding:1px 6px;margin-left:6px;vertical-align:middle}
@media(max-width:640px){
 .stp{padding-left:40px}.stp::before{left:14px}.stp .num{width:30px;height:30px;font-size:14px}
 .stp .bub{font-size:13.5px}.edit textarea{font-size:16px}
 .vpick button{min-width:0;font-size:12.5px;padding:9px 4px}
}
"""

_FLOW = r"""
<div class="top">
 <div class="brand">%%AVA%%<div><div class="nm">%%NAME%%</div><div class="st">сценарій продажу</div></div></div>
 <div style="margin-left:auto"></div>%%NAV%%
</div>
<main style="max-width:820px">
 <div class="card"><div class="ttl">Яку Олю показати <span class="r">у кожної свій характер</span></div>
  <div class="vpick" id="vpick"></div>
  <p class="hint" style="margin:0">Це весь шлях клієнта від «Почати» до повторного замовлення — рівно те, що бачить людина.
   Тексти, позначені кнопкою «Змінити», можна правити прямо тут: збереження діє одразу, без перезапуску бота.</p></div>
 <div id="steps" style="margin-top:14px"></div>
 <div class="card d2" style="margin-top:14px"><div class="ttl">Банк заперечень <span class="r">миттєва відповідь, без ШІ</span></div>
  <p class="hint top">Якщо клієнт пише щось із цього списку — бот відповідає одразу цією фразою.</p>
  <div class="objs" id="objs"></div></div>
</main>
<script>
let FLOW=null,VAR=null,OPEN=null;
function esc(s){return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function safeHtml(s){return esc(s).replace(/&lt;(\/?)(b|i|u|s|code|br)&gt;/g,"<$1$2>")}
async function load(v){const r=await fetch("/api/flow"+(v?"?variant="+v:""));const j=await r.json();
 if(!j.ok)return;FLOW=j;VAR=j.variant;draw()}
function draw(){
 document.getElementById("vpick").innerHTML=FLOW.variants.map(v=>
  `<button class="${v===VAR?"on":""}" onclick="load('${v}')">${v==="A"?"🅐":v==="B"?"🅑":"🅒"} ${FLOW.labels[v]||v}</button>`).join("");
 document.getElementById("steps").innerHTML='<div class="card">'+FLOW.steps.map(s=>{
  const ed=s.fields.filter(f=>FLOW.overrides.indexOf(f.key)>=0).length;
  return `<div class="stp" id="s${s.n}"><span class="num">${s.ico}</span>
   <div class="hd"><b>${s.n}. ${esc(s.title)}</b><span class="when">${esc(s.when)}</span>
    ${ed?'<span class="edited">змінено</span>':""}</div>
   <div class="bub">${safeHtml(s.text)}</div>
   ${s.note?`<div class="note">${esc(s.note)}</div>`:""}
   ${s.fields.length?`<div class="edits">`+s.fields.map(f=>
     `<button class="ebtn ${FLOW.overrides.indexOf(f.key)>=0?"ed":""}" onclick="edit('${f.key}',this)">✏️ ${esc(f.label)}</button>`).join("")+`</div>`:""}
   <div id="e_${s.n}"></div></div>`}).join("")+'</div>';
 document.getElementById("objs").innerHTML=FLOW.objections.map(o=>
  `<div class="obj"><div class="q">«${esc(o.label)}» ${FLOW.overrides.indexOf(o.key)>=0?'<span class="edited">змінено</span>':""}
    <button class="ebtn" style="float:right" onclick="edit('${o.key}',this)">✏️</button></div>
   <div class="a">${safeHtml(o.value)}</div><div id="e_${o.key.replace(".","_")}"></div></div>`).join("")}
function findField(k){for(const s of FLOW.steps)for(const f of s.fields)if(f.key===k)return {f:f,host:"e_"+s.n};
 for(const o of FLOW.objections)if(o.key===k)return {f:o,host:"e_"+k.replace(".","_")};return null}
function edit(k,btn){const F=findField(k);if(!F)return;
 const host=document.getElementById(F.host);
 if(OPEN===k){host.innerHTML="";OPEN=null;return}
 OPEN=k;
 host.innerHTML=`<div class="edit"><div class="lab">${esc(F.f.label)} · ключ ${k}</div>
  <textarea id="ta">${esc(F.f.value)}</textarea>
  <div class="row2"><button class="mini pri" onclick="save('${k}')">Зберегти</button>
   <button class="mini gh" onclick="save('${k}',1)">Повернути стандартний</button>
   <span class="msg" id="msg">Можна <b>жирний</b>, {addr} — це ім'я клієнтки у кличному відмінку.</span></div></div>`;
 host.querySelector("textarea").focus()}
async function save(k,reset){const ta=document.getElementById("ta"),msg=document.getElementById("msg");
 const j=await api("/api/flow_save",{field:k,text:reset?"":ta.value,reset:reset?1:0});
 if(j.ok){msg.className="msg ok";msg.textContent=reset?"↩ повернуто стандартний текст":"✓ збережено — бот уже пише так";
  setTimeout(()=>{OPEN=null;load(VAR)},700)}
 else{msg.className="msg err";msg.textContent="⚠️ "+(j.error||"не збереглось")}}
load();
</script>
"""


def render_flow(out: Path, title: str) -> Path:
    slug = title.split("·")[0].strip() or "Olavita"
    body = _FLOW.replace("%%AVA%%", _ava("olya", slug)).replace("%%NAME%%", e(slug)).replace("%%NAV%%", _nav("flow"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_page(f"{title} · сценарій", _MSG_CSS + _FLOW_CSS, _THEME_JS + _KEY_JS + body + _tabbar("flow")),
                   encoding="utf-8")
    return out


def render_pwa(var_dir: Path, name: str) -> None:
    """manifest.json + іконки: пульт додається на екран «Додому» і відкривається як застосунок."""
    var_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": f"{name} · пульт", "short_name": name[:12], "start_url": "/dashboard.html",
                "display": "standalone", "orientation": "portrait", "background_color": "#0e1621",
                "theme_color": "#17212b", "lang": "uk",
                "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                          {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}]}
    (var_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:  # noqa: BLE001
        return
    letter = (name or "O")[:1].upper()
    for size in (192, 512):
        p = var_dir / f"icon-{size}.png"
        if p.exists():
            continue
        im = Image.new("RGB", (size, size), (23, 33, 43))
        d = ImageDraw.Draw(im)
        for y in range(size):                       # м'який градієнт Telegram-синього
            k = y / size
            d.line((0, y, size, y), fill=(int(92 - 40 * k), int(175 - 60 * k), int(254 - 43 * k)))
        f = None
        for cand in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            if Path(cand).exists():
                f = ImageFont.truetype(cand, int(size * 0.5))
                break
        f = f or ImageFont.load_default()
        bb = d.textbbox((0, 0), letter, font=f)
        d.text(((size - bb[2] + bb[0]) / 2, (size - bb[3] + bb[1]) / 2 - size * 0.03), letter, font=f, fill="white")
        im.save(p)
