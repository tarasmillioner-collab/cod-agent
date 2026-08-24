"""Агентный цикл: история → Claude → tools (≤5 ходов) → guards → ответ.

LLM говорит, код решает: всё, что меняет заказ, проходит через exec_tool;
итоговый текст проходит Guards.check; при блоке — одна регенерация с указанием
нарушения, затем детерминированный fallback по стадии.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from core import state as S
from core.guards import Guards
from core.offer import Offer
from core.store import Store
from core.tools import TOOLS, ToolCtx, exec_tool

log = logging.getLogger("agent")

MAX_TOOL_ROUNDS = 5

FALLBACK_BY_STAGE = {
    S.NEW: "Щоб оформити замовлення, надішліть, будь ласка, номер телефону кнопкою нижче 📱",
    S.PHONE: "Надішліть, будь ласка, номер телефону кнопкою нижче — він потрібен лише для накладної 📱",
    S.NAME: "Як до вас звертатися? Напишіть ім'я для накладної Нової пошти.",
    S.CITY: "У яке місто відправити? Напишіть назву — знайду відділення.",
    S.WAREHOUSE: "Яке відділення Нової пошти зручне? Напишіть номер або вулицю.",
    S.UPSELL: "Перевірте, будь ласка, підсумок замовлення нижче.",
    S.REVIEW: "Перевірте, будь ласка, підсумок замовлення нижче і підтвердіть.",
}
FALLBACK_DEFAULT = "Я поруч — якщо є питання щодо замовлення, напишіть, відповім."


class LLMLimited(Exception):
    """Подписка/лимит/авторизация — LLM недоступен, нужен fallback + человек."""


@dataclass
class AgentReply:
    text: str
    ui: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)


class Agent:
    def __init__(self, llm, store: Store, offer: Offer, guards: Guards, np, prompt_path: str | Path):
        self.llm = llm
        self.store = store
        self.offer = offer
        self.guards = guards
        self.np = np
        self.prompt_tpl = Path(prompt_path).read_text(encoding="utf-8")

    # ---------- prompt ----------
    def system_prompt(self, chat: dict, order: dict | None) -> str:
        base = self.prompt_tpl.format(
            persona=self.offer.persona,
            product=self.offer.product["name_ua"],
            support_hours=self.offer.faq.get("support_hours", "робочі години"),
        )
        snap = {
            "client_name": order.get("name") if order else chat.get("name"),
            "stage": order["stage"] if order else "none",
            "set": order.get("set_code") if order else None,
            "missing": S.ready_to_confirm(order) if order else ["phone"],
            "city": order.get("np_city_name") if order else None,
            "warehouse": order.get("np_wh_name") if order else None,
            "flags": chat.get("flags", {}),
        }
        from core import experiments as X
        pl = X.persona_line(self.offer, chat.get("variant"))
        return base + (f"\n\nСТИЛЬ (варіант {chat.get('variant')}): {pl}" if pl else "") + \
            "\n\nПОТОЧНИЙ СТАН (від системи, не переказуй дослівно):\n" + json.dumps(snap, ensure_ascii=False)

    def build_messages(self, chat_id: int, limit: int = 20) -> list[dict]:
        msgs: list[dict] = []
        for h in self.store.history(chat_id, limit=limit):
            role = "assistant" if h["role"] in ("assistant", "manager") else "user" if h["role"] == "user" else None
            if role is None:
                continue
            content = h["content"].strip()
            if not content:
                continue
            if h["role"] == "manager":
                content = "[менеджер написав]: " + content
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"] += "\n" + content
            else:
                msgs.append({"role": role, "content": content})
        if not msgs or msgs[0]["role"] != "user":
            msgs.insert(0, {"role": "user", "content": "[клієнт відкрив чат]"})
        if msgs[-1]["role"] != "user":
            msgs.append({"role": "user", "content": "[продовжуй]"})
        return msgs

    # ---------- main ----------
    def transcript(self, chat_id: int, limit: int = 20) -> str:
        lines = []
        for h in self.store.history(chat_id, limit=limit):
            if h["role"] == "user":
                lines.append("Клієнт: " + h["content"].strip())
            elif h["role"] == "assistant":
                lines.append("Оля: " + h["content"].strip())
            elif h["role"] == "manager":
                lines.append("Менеджер: " + h["content"].strip())
        return ("Це історія чату (останні репліки). Відповідай на ОСТАННЄ повідомлення клієнта як Оля, "
                "використовуючи інструменти. Поверни лише текст відповіді клієнту.\n\n" + "\n".join(lines))

    async def reply(self, chat: dict, order: dict | None, extra_amounts: set[int] | None = None) -> AgentReply:
        ctx = ToolCtx(store=self.store, offer=self.offer, np=self.np, chat=chat, order=order,
                      extra_amounts=extra_amounts or set())
        system = self.system_prompt(chat, order)
        if hasattr(self.llm, "run"):          # Claude Agent SDK (підписка): цикл tools крутить SDK
            tool_names: list[str] = []

            async def executor(name: str, args: dict) -> dict:
                tool_names.append(name)
                res = await exec_tool(ctx, name, args)
                self.store.add_message(chat["tg_user_id"], "tool", f"{name}({json.dumps(args, ensure_ascii=False)})",
                                       tool={"name": name, "input": args, "result": res})
                return res

            r = await self.llm.run(system, self.transcript(chat["tg_user_id"]), TOOLS, executor)
            self.store.log_usage(chat["tg_user_id"], getattr(self.llm, "model", "sdk"), 0, 0, r.usd)
            if r.limited:
                raise LLMLimited(r.error)
            ctx.refresh()
            final, reasons = await self._guard(system, [], r.text, ctx, regen=False)
            return AgentReply(text=final, ui=ctx.ui, blocked_reasons=reasons, tool_names=tool_names)
        messages = self.build_messages(chat["tg_user_id"])
        tool_names: list[str] = []
        text = ""
        for _ in range(MAX_TOOL_ROUNDS):
            turn = await self.llm.turn(system, messages, TOOLS)
            self.store.log_usage(chat["tg_user_id"], getattr(self.llm, "model", ""), turn.in_tokens, turn.out_tokens, turn.usd)
            text = turn.text
            if not turn.tool_calls:
                break
            messages.append({"role": "assistant", "content": turn.blocks})
            results = []
            for call in turn.tool_calls:
                tool_names.append(call["name"])
                res = await exec_tool(ctx, call["name"], call["input"])
                self.store.add_message(chat["tg_user_id"], "tool", f"{call['name']}({json.dumps(call['input'], ensure_ascii=False)})",
                                       tool={"name": call["name"], "input": call["input"], "result": res})
                results.append({"type": "tool_result", "tool_use_id": call["id"], "content": json.dumps(res, ensure_ascii=False)})
            messages.append({"role": "user", "content": results})
            if turn.stop_reason != "tool_use":
                break
        else:
            log.warning("tool loop limit for chat %s", chat["tg_user_id"])

        ctx.refresh()
        final, reasons = await self._guard(system, messages, text, ctx)
        return AgentReply(text=final, ui=ctx.ui, blocked_reasons=reasons, tool_names=tool_names)

    async def _guard(self, system: str, messages: list[dict], text: str, ctx: ToolCtx, regen: bool = True) -> tuple[str, list[str]]:
        extra = set(ctx.extra_amounts)
        if ctx.order and ctx.order.get("price_uah"):
            extra.add(int(ctx.order["price_uah"]))
        if not text.strip():
            return self._fallback(ctx), ["empty"]
        g = self.guards.check(text, extra_amounts=extra)
        if g.ok:
            return g.text, []
        reasons = list(g.reasons)
        if not regen:
            return self._fallback(ctx), reasons
        # одна регенерация с указанием нарушения
        retry_msgs = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "[система] Відповідь відхилено: " + ", ".join(reasons) +
             ". Перепиши коротше, без цих порушень, без цифр, яких немає в get_offer, без обіцянок дат і без медичних тверджень."},
        ]
        try:
            turn = await self.llm.turn(system, retry_msgs, [])
            self.store.log_usage(ctx.chat["tg_user_id"], getattr(self.llm, "model", ""), turn.in_tokens, turn.out_tokens, turn.usd)
            g2 = self.guards.check(turn.text, extra_amounts=extra)
            if g2.ok and turn.text.strip():
                return g2.text, reasons
            reasons += g2.reasons
        except Exception as e:  # noqa: BLE001
            log.warning("regen failed: %s", e)
            reasons.append("regen_error")
        return self._fallback(ctx), reasons

    def _fallback(self, ctx: ToolCtx) -> str:
        stage = ctx.order["stage"] if ctx.order else S.NEW
        return FALLBACK_BY_STAGE.get(stage, FALLBACK_DEFAULT)
