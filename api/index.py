"""
JAMAIKA CHECKER BOT — Vercel Entry Point (Flask WSGI)
"""
import os
import sys
import threading
import time
import logging

if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = "/tmp"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, request, jsonify
import requests as http
import telebot
from bot import bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
_MAX_WAIT = 55

app = Flask(__name__)


def _register_webhook(host):
    """يسجّل الـ Webhook بشكل متزامن (synchronous) مع Telegram."""
    if not BOT_TOKEN:
        return False, "BOT_TOKEN not set in environment variables"

    webhook_url = f"https://{host}/"
    try:
        resp   = http.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url, "drop_pending_updates": True},
            timeout=10,
        )
        result = resp.json()
        if result.get("ok"):
            logger.info(f"Webhook registered → {webhook_url}")
            return True, webhook_url
        else:
            logger.error(f"Webhook failed: {result}")
            return False, str(result)
    except Exception as exc:
        logger.error(f"Webhook error: {exc}")
        return False, str(exc)


@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>",             methods=["GET", "POST"])
def main(path):

    # ── POST ← Telegram webhook ──────────────────────────────────
    if request.method == "POST":
        return _handle_webhook()

    # ── GET /setup ← تسجيل يدوي أو تشخيص ───────────────────────
    if path == "setup" or "setup" in request.args:
        ok, msg = _register_webhook(request.host)
        status  = 200 if ok else 500
        return f"{'✅ Done' if ok else '❌ Failed'}: {msg}", status

    # ── GET / ← health check + تسجيل أوتوماتيك متزامن ──────────
    ok, msg = _register_webhook(request.host)
    webhook_status = f"✅ Webhook: {msg}" if ok else f"⚠️ Webhook: {msg}"
    return (
        f"JAMAIKA CHECKER BOT is running on Vercel! ✅\n"
        f"{webhook_status}"
    ), 200


def _handle_webhook():
    try:
        data   = request.get_json(force=True, silent=True) or {}
        update = telebot.types.Update.de_json(data)

        before_ids = {t.ident for t in threading.enumerate()}
        bot.process_new_updates([update])

        deadline = time.time() + _MAX_WAIT
        while True:
            active = [
                t for t in threading.enumerate()
                if t.ident not in before_ids
                and not t.daemon
                and t.is_alive()
            ]
            if not active or time.time() >= deadline:
                break
            time.sleep(0.25)

    except Exception as exc:
        logger.exception("Webhook error: %s", exc)

    return jsonify({"ok": True}), 200
