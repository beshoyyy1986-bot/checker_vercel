"""
JAMAIKA CHECKER BOT — Vercel Entry Point (Flask WSGI)
ملف واحد يستقبل كل طلبات Telegram عبر Webhook.
"""
import os
import sys
import threading
import time
import logging

# ── إعداد المسارات قبل أى import ─────────────────────────────────────────────
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = "/tmp"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, request, jsonify   # noqa: E402
import requests as http                      # noqa: E402
import telebot                               # noqa: E402
from bot import bot                          # noqa: E402 — كل handlers محمّلة هنا

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
_MAX_WAIT   = 55   # ثانية — vercel maxDuration = 60

app = Flask(__name__)   # ← Vercel بيكتشف هذا المتغير تلقائياً كـ WSGI entrypoint


# ══════════════════════════════════════════════════════════════════
# Health check
# ══════════════════════════════════════════════════════════════════
@app.route("/", methods=["GET"])
@app.route("/api/webhook", methods=["GET"])
def health():
    return "JAMAIKA CHECKER BOT is running on Vercel!", 200


# ══════════════════════════════════════════════════════════════════
# Telegram Webhook
# ══════════════════════════════════════════════════════════════════
@app.route("/", methods=["POST"])
@app.route("/api/webhook", methods=["POST"])
def webhook():
    try:
        data   = request.get_json(force=True, silent=True) or {}
        update = telebot.types.Update.de_json(data)

        # سجّل الخيوط الموجودة قبل المعالجة
        before_ids = {t.ident for t in threading.enumerate()}

        # وزّع التحديث على معالجات البوت (قد تُولد خيوط لفحص الكروت)
        bot.process_new_updates([update])

        # انتظر الخيوط الجديدة (فحص الكروت / Bulk / Gate scan)
        deadline = time.time() + _MAX_WAIT
        while True:
            active = [
                t for t in threading.enumerate()
                if t.ident not in before_ids and not t.daemon and t.is_alive()
            ]
            if not active or time.time() >= deadline:
                break
            time.sleep(0.25)

    except Exception as exc:
        logger.exception("Webhook error: %s", exc)

    # دائماً ارجع 200 لمنع Telegram من إعادة الإرسال
    return jsonify({"ok": True}), 200


# ══════════════════════════════════════════════════════════════════
# Webhook Setup Helper  — /api/setup?secret=<BOT_TOKEN>
# ══════════════════════════════════════════════════════════════════
@app.route("/api/setup", methods=["GET"])
def setup():
    secret = request.args.get("secret", "")

    if not BOT_TOKEN:
        return "BOT_TOKEN env var not set in Vercel.", 500

    if secret != BOT_TOKEN:
        return "Wrong secret. Use: /api/setup?secret=<BOT_TOKEN>", 401

    webhook_url = f"https://{request.host}/api/webhook"
    try:
        resp = http.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url, "drop_pending_updates": True},
            timeout=15,
        )
        result = resp.json()
    except Exception as exc:
        return f"Telegram API error: {exc}", 500

    status = 200 if result.get("ok") else 400
    body   = f"Webhook: {webhook_url}\n\nTelegram: {resp.text}"
    return body, status
