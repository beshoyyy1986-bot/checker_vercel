"""
JAMAIKA CHECKER BOT — Vercel Entry Point (Flask WSGI)
Catch-all routes تضمن استقبال أى مسار يرسله Vercel أو Telegram.
"""
import os
import sys
import threading
import time
import logging

# ── إعداد البيئة ─────────────────────────────────────────────────────────────
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = "/tmp"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, request, jsonify   # noqa: E402
import requests as http                      # noqa: E402
import telebot                               # noqa: E402
from bot import bot                          # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
_MAX_WAIT = 55   # ثانية (Vercel maxDuration = 60)

# ← Vercel بيكتشف متغير `app` تلقائياً كـ WSGI entrypoint
app = Flask(__name__)


# ══════════════════════════════════════════════════════════════════
# Catch-all — يستقبل أى مسار (الأصلى أو المُعاد كتابته من Vercel)
# ══════════════════════════════════════════════════════════════════
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>",             methods=["GET", "POST"])
def main(path):

    # ── POST ← Telegram webhook ──────────────────────────────────
    if request.method == "POST":
        return _handle_webhook()

    # ── GET /...setup... ← تسجيل الـ Webhook مع Telegram ─────────
    if "setup" in path or "setup" in request.query_string.decode():
        return _handle_setup()

    # ── GET أى حاجة تانية ← health check ─────────────────────────
    return "JAMAIKA CHECKER BOT is running on Vercel! ✅", 200


# ══════════════════════════════════════════════════════════════════
# معالج Webhook
# ══════════════════════════════════════════════════════════════════
def _handle_webhook():
    try:
        data   = request.get_json(force=True, silent=True) or {}
        update = telebot.types.Update.de_json(data)

        before_ids = {t.ident for t in threading.enumerate()}
        bot.process_new_updates([update])

        # انتظر خيوط فحص الكروت / Bulk حتى تنتهى
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


# ══════════════════════════════════════════════════════════════════
# معالج Setup — يسجّل Webhook URL مع Telegram
# ══════════════════════════════════════════════════════════════════
def _handle_setup():
    secret = request.args.get("secret", "")

    if not BOT_TOKEN:
        return "BOT_TOKEN env var not set in Vercel.", 500

    if secret != BOT_TOKEN:
        return "Wrong secret. Visit: /setup?secret=YOUR_BOT_TOKEN", 401

    # الـ Webhook يشير لجذر الموقع — كل POST هيوصل لـ _handle_webhook
    webhook_url = f"https://{request.host}/"

    try:
        resp   = http.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url, "drop_pending_updates": True},
            timeout=15,
        )
        result = resp.json()
    except Exception as exc:
        return f"Telegram API error: {exc}", 500

    ok  = result.get("ok", False)
    msg = (
        f"{'✅ Done!' if ok else '❌ Failed'}\n"
        f"Webhook URL: {webhook_url}\n\n"
        f"Telegram response: {resp.text}"
    )
    return msg, 200 if ok else 400
