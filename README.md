# cod-agent — Telegram-продавец для UA COD (пилот Olavita)

Сервис 24/7 на VPS: кнопка на лендинге → бот → телефон/ім'я/відділення НП → один апсейл →
«Підтверджую» → заказ в LP-CRM (статус «Прийнято») → ТТН → «прибула» → напоминания → выкуп.
Сложное → менеджеру в форум-топик. Мозг — Claude с tool-calling; **цены/статусы/даты только из кода** (`offer.yaml`).

## Запуск локально (test-бот)
```bash
cp config.env.example config.env   # BOT_TOKEN тестового бота, ANTHROPIC_API_KEY, ENV=test, LPCRM_DRY_RUN=1
.venv/bin/python -m pytest -q
.venv/bin/python bot.py
```

## Деплой
```bash
deploy/deploy.sh            # rsync → venv → systemd; config.env на сервере не перезаписывает
ssh hostinger-studio 'journalctl -u cod-agent -f'   # или tail -f /var/log/cod-agent.log
```
Прод: `ENV=prod` в `/srv/cod_agent/config.env`; unit ставит `COD_AGENT_PROD_OK=1` — локально прод-токен не поднять (один токен = один поллер).

## Кнопка на лендинге
Deep-link: `https://t.me/<bot>?start=<set>_<src>_<rtkcid>` — `set` = `s1|s2|s3` (набор из offer.yaml), `src` = источник, `rtkcid` — из `window.LP_UTM.rtkcid`.
```html
<a id="tg-order" class="of-btn" href="#">Замовити в Telegram</a>
<script>
(function(){var u=window.LP_UTM||{},cfg=window.LP_CFG||{};
var set='s1',src=(u.utm_source||'fb').replace(/[^a-z0-9]/gi,'').slice(0,10),cid=(u.rtkcid||'').slice(0,32);
document.getElementById('tg-order').href='https://t.me/BOT_USERNAME?start='+[set,src,cid].filter(Boolean).join('_');})();
</script>
```
Лимит payload — 64 символа, только `A-Za-z0-9_-`.

## Группа менеджеров
Супергруппа с включёнными «Темами» (forum). Бот — админ с правом «Manage topics». `MANAGERS_CHAT_ID` = id группы (отрицательный).
Команды: `/bot on|off|status`, `/stats [7]`, `/order <id>`, `/close` (в теме клиента). Ответ менеджера в теме уходит клиенту от имени бота.

## LP-CRM
Подтверждено против `tallside.lp-crm.biz` (2026-08-23): `getStatuses`, `getOrdersIdByStatus`, `getOrdersByID` (multi-id; отдаёт `ttn`, `ttn_status`, `status`), `getCategories`, `getProductsByCategory`.
Статусы: 3 Новий · **11 Прийнято** · 14 Відправлено · 58/59/60 у відділенні · 18 Завершено · 13 Відмова.
Товары: 333 сироватка (590) · 341 крем для очей (499) · 298 філер (299). Рабочий ключ — «вихідний».
`addNewOrder` шлём со `status=11` + коммент «✅ ПІДТВЕРДЖЕНО В TELEGRAM — не дзвонити». Принимает ли CRM `status` — проверить на первом реальном заказе; если нет — заказ придёт «Новий» с комментом, оператор переводит руками (метод смены статуса в API не найден, `editOrder` отвечает 422 — спросить доку в кабинете FAQ → API).
Лимит 429 — клиент держит паузу 3 с между запросами.

## E2E-чеклист (тест-бот, тест-группа) — `tests/e2e_manual.md`

## Структура
`bot.py` entrypoint · `config.py` · `offer.yaml` (цены/наборы/факты/запреты) · `prompts/system.md` ·
`core/` state, store, tools, guards, agent, handoff, outbox, scheduler · `clients/` lpcrm, novaposhta, claude ·
`tg/` handlers_client, handlers_admin, keyboards, texts · `obs/` logging, stats · `voice/` (v2) · `deploy/`.
