"""Проба SDK-клиента на VPS: читает config.env, один вопрос с одним tool."""
import asyncio, os, sys
sys.path.insert(0, "/srv/cod_agent")
from config import load_config
from clients.claude_sdk import ClaudeSdkClient

async def ex(n, a):
    return {"topic": a.get("topic"), "fact": "Сироватка з пептидами, 30 мл на місяць."}

async def main():
    cfg = load_config("/srv/cod_agent/config.env")
    c = ClaudeSdkClient(cfg.claude_oauth_token, cfg.claude_model, cwd="/srv/cod_agent/var")
    r = await c.run("Ти Оля. Відповідай коротко українською. Факти бери лише з get_faq.",
                    "Клієнт: привіт, що це за сироватка?",
                    [{"name": "get_faq", "description": "факт за темою",
                      "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}], ex)
    print("limited:", r.limited, "| err:", r.error[:200], "| text:", r.text[:300], "| tools:", r.tool_names)

asyncio.run(main())
