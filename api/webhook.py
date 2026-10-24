"""
Vercel Serverless Webhook Handler — JAMAIKA CHECKER BOT
يستقبل التحديثات من Telegram ويوزعها على معالجات البوت.
"""
from http.server import BaseHTTPRequestHandler
import json
import sys
import os
import threading
import time
import logging

# ── ضبط المسارات قبل أى import آخر ─────────────────────────────────────────
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = "/tmp"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import telebot          # noqa: E402
from bot import bot     # noqa: E402  — يستورد instance البوت المجهز بكل handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# أقصى وقت انتظار للخيوط الخلفية (ثواني) — vercel maxDuration = 60
_MAX_THREAD_WAIT = 55

# Vercel يجمّد الـ instance بمجرد إرسال الاستجابة، لذلك لازم المعالج يشتغل داخل
# الـ request نفسه. خيوط worker_pool الخاصة بـ telebot تُنشأ وقت الـ import فلا
# تراها حلقة انتظار الخيوط الجديدة بالأسفل — الرد كان يخرج قبل ما يوصل.
bot.threaded = False


class handler(BaseHTTPRequestHandler):
    """WSGI-compatible handler — Vercel calls do_POST/do_GET per request."""

    def log_message(self, format, *args):  # noqa: A002
        pass  # أوقف لوج HTTP الافتراضى (verbose جداً)

    # ── Health Check ─────────────────────────────────────────────────────────
    def do_GET(self):
        self._send(200, b"JAMAIKA CHECKER BOT is running on Vercel!")

    # ── Telegram Webhook ──────────────────────────────────────────────────────
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)

            # ① حلّل التحديث
            data   = json.loads(body.decode("utf-8"))
            update = telebot.types.Update.de_json(data)

            # ② سجّل الخيوط الموجودة قبل المعالجة
            before_ids = {t.ident for t in threading.enumerate()}

            # ③ ادفع التحديث لـ handlers (قد تُولد خيوط خلفية لفحص الكروت)
            bot.process_new_updates([update])

            # ④ انتظر الخيوط الجديدة حتى تنتهى (فحص الكروت / Bulk)
            deadline = time.time() + _MAX_THREAD_WAIT
            while True:
                active = [
                    t for t in threading.enumerate()
                    if t.ident not in before_ids
                    and not t.daemon
                    and t.is_alive()
                ]
                if not active:
                    break
                remaining = deadline - time.time()
                if remaining <= 0:
                    logger.warning(
                        "Thread-wait timeout — %d thread(s) still running", len(active)
                    )
                    break
                time.sleep(0.25)

            logger.info("Update %s handled", update.update_id)

        except Exception as exc:
            logger.exception("Webhook handler error: %s", exc)

        finally:
            # 200 دائماً — حتى بعد المعالجة أو عند الخطأ — لمنع Telegram من الـ retry
            try:
                self._send(200, b"OK")
            except Exception:
                pass

    # ── Helper ────────────────────────────────────────────────────────────────
    def _send(self, code: int, body: bytes):
        """إرسال استجابة HTTP بسيطة."""
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        try:
            self.wfile.flush()
        except Exception:
            pass
