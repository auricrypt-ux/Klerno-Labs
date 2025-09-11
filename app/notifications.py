# app/notifications.py
import os, httpx

SLACK_WEBHOOK = (os.getenv("SLACK_WEBHOOK_URL") or "").strip()

async def slack_notify(text: str) -> dict:
    if not SLACK_WEBHOOK:
        return {"sent": False, "reason": "no webhook configured"}
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(SLACK_WEBHOOK, json={"text": text})
        return {"sent": (200 <= r.status_code < 300), "status": r.status_code}
