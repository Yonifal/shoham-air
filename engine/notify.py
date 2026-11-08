"""Alert delivery. Channels switch on when their secrets exist in the GitHub repo settings."""
import os

import requests


def send(text: str) -> None:
    print("ALERT:", text)
    sent = False
    # Telegram (free, simplest): TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if tok and chat:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": text}, timeout=30)
        sent = True
    # WhatsApp Cloud API (official): WA_TOKEN + WA_PHONE_ID + WA_RECIPIENTS (comma-separated)
    # Proactive messages must use an approved template; WA_TEMPLATE names it (one text parameter).
    wa_tok, wa_phone = os.getenv("WA_TOKEN"), os.getenv("WA_PHONE_ID")
    if wa_tok and wa_phone:
        for to in filter(None, os.getenv("WA_RECIPIENTS", "").split(",")):
            requests.post(
                f"https://graph.facebook.com/v21.0/{wa_phone}/messages",
                headers={"Authorization": f"Bearer {wa_tok}"},
                json={"messaging_product": "whatsapp", "to": to.strip(), "type": "template",
                      "template": {"name": os.getenv("WA_TEMPLATE", "smoke_alert"),
                                   "language": {"code": "he"},
                                   "components": [{"type": "body", "parameters": [
                                       {"type": "text", "text": text}]}]}},
                timeout=30)
        sent = True
    if not sent:
        print("(no channel configured yet — alert only logged)")
