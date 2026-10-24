"""
Webhook Setup Helper — JAMAIKA CHECKER BOT
زور هذا المسار بعد الـ Deploy لتسجيل Webhook مع Telegram.

Usage:
  https://your-app.vercel.app/api/setup?secret=<BOT_TOKEN>

يمرر التوكن كـ secret للتحقق من الهوية — لا يحفظ شيئاً.
"""
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import os
import sys
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")


class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):  # noqa: A002
        pass

    def do_GET(self):
        query  = parse_qs(urlparse(self.path).query)
        secret = query.get("secret", [""])[0]

        if not BOT_TOKEN:
            return self._reply(500, "❌ BOT_TOKEN env var not set in Vercel.")

        if secret != BOT_TOKEN:
            return self._reply(401, "❌ Wrong secret. Pass ?secret=<BOT_TOKEN>")

        host        = self.headers.get("Host", "")
        webhook_url = f"https://{host}/api/webhook"

        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                json={"url": webhook_url, "drop_pending_updates": True},
                timeout=15,
            )
            data = resp.json()
        except Exception as exc:
            return self._reply(500, f"❌ Request to Telegram failed: {exc}")

        body = (
            f"Webhook URL: {webhook_url}\n\n"
            f"Telegram response:\n{json.dumps(data, indent=2, ensure_ascii=False)}"
        )
        self._reply(200 if data.get("ok") else 400, body)

    def _reply(self, code: int, body: str):
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
