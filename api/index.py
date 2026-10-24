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
APP_URL   = os.environ.get("APP_URL", "").rstrip("/")
_MAX_WAIT = 55

app = Flask(__name__)

# Vercel freezes the instance the moment the response is returned, so the update
# must be handled inside the request. telebot's worker-pool threads are created
# at import time, which makes them invisible to the "wait for new threads" logic
# in _handle_webhook — the response would go out before the reply was sent.
# Running inline keeps the handler in the request thread; the long-running work
# that handlers spawn themselves (card checks, bulk, gate scans) still creates
# brand-new threads, which the wait loop below does pick up.
bot.threaded = False


def _webhook_url(host):
    """APP_URL يثبّت العنوان على الـ alias الدائم بدل عنوان الـ deploy المتغيّر."""
    return f"{APP_URL}/" if APP_URL else f"https://{host}/"


def _register_webhook(host):
    """يسجّل الـ Webhook مع Telegram — يتخطى التسجيل لو العنوان مطابق بالفعل."""
    if not BOT_TOKEN:
        return False, "BOT_TOKEN not set in environment variables"

    webhook_url = _webhook_url(host)
    api = f"https://api.telegram.org/bot{BOT_TOKEN}"
    try:
        info = http.get(f"{api}/getWebhookInfo", timeout=10).json()
        current = info.get("result", {}).get("url") if info.get("ok") else None
        if current == webhook_url:
            return True, f"{webhook_url} (already registered)"

        resp   = http.post(
            f"{api}/setWebhook",
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
    started = time.time()
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
            if not active:
                break
            if time.time() >= deadline:
                logger.warning(
                    "Thread-wait timeout — %d thread(s) still running", len(active)
                )
                break
            time.sleep(0.25)

        logger.info(
            "Update %s handled in %.2fs", update.update_id, time.time() - started
        )
    except Exception as exc:
        logger.exception("Webhook error: %s", exc)

    return jsonify({"ok": True}), 200
