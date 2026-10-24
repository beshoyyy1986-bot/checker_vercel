"""
JAMAIKA CHECKER BOT — Vercel Entry Point (Flask WSGI)
يسجّل الـ Webhook أوتوماتيك عند أى GET request.
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

# ── تتبع آخر تسجيل webhook ───────────────────────────────────────────────────
_last_webhook_host   = None
_webhook_lock        = threading.Lock()


# ══════════════════════════════════════════════════════════════════
# تسجيل Webhook — يُستدعى أوتوماتيك من كل GET request
# ══════════════════════════════════════════════════════════════════
def _auto_register_webhook(host):
    """يسجّل الـ Webhook مع Telegram إذا تغيّر الـ host أو لم يُسجَّل بعد."""
    global _last_webhook_host

    with _webhook_lock:
        if _last_webhook_host == host:
            return  # مسجَّل مسبقاً بنفس الـ host — لا حاجة لإعادة التسجيل

        if not BOT_TOKEN:
            logger.error("BOT_TOKEN not set — cannot register webhook")
            return

        webhook_url = f"https://{host}/"
        try:
            resp = http.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                json={"url": webhook_url, "drop_pending_updates": True},
                timeout=10,
            )
            result = resp.json()
            if result.get("ok"):
                logger.info(f"✅ Webhook registered → {webhook_url}")
                _last_webhook_host = host
            else:
                logger.error(f"❌ Webhook registration failed: {result}")
        except Exception as exc:
            logger.error(f"Webhook registration error: {exc}")


# ══════════════════════════════════════════════════════════════════
# Catch-all — يستقبل أى مسار (الأصلى أو المُعاد كتابته من Vercel)
# ══════════════════════════════════════════════════════════════════
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>",             methods=["GET", "POST"])
def main(path):

    # ── POST ← Telegram webhook ──────────────────────────────────
    if request.method == "POST":
        return _handle_webhook()

    # ── GET ← تسجيل الـ Webhook أوتوماتيك + health check ────────
    threading.Thread(
        target=_auto_register_webhook,
        args=(request.host,),
        daemon=True
    ).start()

    return (
        "JAMAIKA CHECKER BOT is running on Vercel! ✅\n"
        "Webhook auto-registration triggered."
    ), 200


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
