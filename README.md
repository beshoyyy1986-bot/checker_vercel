# JAMAIKA CHECKER BOT — نشر على Vercel

## الملفات المرفوعة

```
vercel_bot/
├── bot.py              ← البوت الأصلى (تعديلان فقط)
├── baner.webp          ← ضع ملف الصورة هنا (اختيارى)
├── vercel.json         ← إعدادات Vercel
├── requirements.txt    ← المكتبات
├── .env.example        ← مثال متغيرات البيئة
└── api/
    ├── webhook.py      ← نقطة استقبال التحديثات
    └── setup.py        ← مساعد تسجيل الـ Webhook
```

---

## خطوات النشر

### 1. رفع المشروع على Vercel

```bash
# إما من الـ Dashboard أو CLI:
npm i -g vercel
cd vercel_bot
vercel
```

أو:
- اذهب لـ [vercel.com](https://vercel.com) → New Project
- ارفع المجلد أو اربطه بـ GitHub

---

### 2. أضف متغيرات البيئة

في Vercel Dashboard → Settings → Environment Variables:

| Key        | Value                         |
|------------|-------------------------------|
| `BOT_TOKEN` | توكن البوت من BotFather       |
| `ADMIN_ID`  | رقمك على Telegram             |
| `DATA_DIR`  | `/tmp`                        |
| `APP_URL`   | `https://your-app.vercel.app` — عنوان النشر الدائم |

> `APP_URL` يثبّت الـ Webhook على الـ alias الدائم. بدونه يُعاد تسجيل الـ Webhook
> بعنوان الـ deploy المتغيّر مع كل طلب، فيرجع Telegram خطأ `429 Too Many Requests`.

---

### 3. سجّل الـ Webhook مع Telegram

بعد انتهاء الـ Deploy، افتح في المتصفح:

```
https://YOUR-APP.vercel.app/api/setup?secret=YOUR_BOT_TOKEN
```

لو ظهر `"ok": true` — البوت شغّال ✅

---

## ملاحظات مهمة

| الموضوع | التفصيل |
|---------|---------|
| **قاعدة البيانات** | SQLite على `/tmp` — البيانات (اشتراكات، أكواد) **تُمسح** عند إعادة تشغيل الـ Function (Cold Start). للإنتاج استخدم Supabase/Turso |
| **مهلة الوظيفة** | `maxDuration: 60` ثانية — كافية لفحص كرت واحد. الـ Bulk الكبير قد يُقطع |
| **الـ Webhook** | يستبدل الـ Polling — لا تشغّل الاثنين في نفس الوقت |
| **baner.webp** | اختيارى. البوت يشتغل بدونها ويرسل نص عادى بدل الصورة |

---

## التعديلات على bot.py

1. `DATA_DIR` افتراضياً `/tmp` بدل مجلد الكود (Vercel للقراءة فقط)
2. `BANNER_PATH` أصبح مسار مطلق (لضمان إيجاد الملف من أى working directory)
3. `edit_banner` يعدّل نص الرسالة حين لا يوجد `baner.webp` — بدل حذف الرسالة
   وإعادة إرسالها مع كل ضغطة زر

## لماذا `bot.threaded = False` في `api/`؟

Vercel يجمّد الـ Function بمجرد إرسال الاستجابة. الوضع الافتراضى لـ pyTelegramBotAPI
(`threaded=True`) يدفع التحديث إلى `worker_pool` — وهى خيوط تُنشأ وقت الـ import،
فلا تراها حلقة «انتظار الخيوط الجديدة» في الـ webhook. النتيجة: الاستجابة تخرج
فوراً (~0.18s) قبل أن يوصل البوت الرد، ثم يجمّد Vercel الـ instance ويضيع الرد.

بـ `threaded=False` يشتغل الـ handler داخل الـ request نفسه، أما الأعمال الطويلة
(فحص الكروت / Bulk / فحص البوابات) فهى تنشئ خيوطاً جديدة فعلاً — وحلقة الانتظار
تلتقطها وتنتظرها حتى 55 ثانية.
