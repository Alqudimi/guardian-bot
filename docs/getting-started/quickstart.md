# البدء السريع

## الهدف

يشرح هذا الدليل تشغيل Guardian Bot محلياً باستخدام long polling وRedis وPostgreSQL. التشغيل المحلي مخصص للتطوير والتحقق، وليس دليلاً على جاهزية Telegram production.

## المتطلبات

| المتطلب | الحد الأدنى العملي | الغرض |
|---|---:|---|
| Python | 3.11+ | تشغيل التطبيق والاختبارات |
| PostgreSQL | 14+، والمتحقق محلياً 16 | التخزين الدائم |
| Redis | 7+ | الإعدادات، التنسيق الذري، الجلسات، Celery |
| Telegram token | مطلوب للتشغيل مع Telegram فقط | استقبال وإرسال التحديثات |
| Docker | اختياري | تشغيل الخدمات في حاويات |

## التثبيت

```bash
git clone <repository-url>
cd guardian-bot
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

حرر `.env` وضع token حقيقياً فقط إذا كنت ستتصل بـTelegram. في الاختبارات يمكن استخدام token شكلي كما هو موضح في دليل الاختبارات، لكن لا تستخدمه لتشغيل bot فعلي.

## تجهيز PostgreSQL وRedis

شغّل خدماتك المحلية، ثم تحقق من الاتصال:

```bash
redis-cli ping
psql "$DATABASE_URL" -c 'select 1'
```

في development يمكن استخدام `AUTO_CREATE_TABLES=true` لتسهيل البدء، لكن المسار الموصى به هو تطبيق Alembic صراحة:

```bash
alembic upgrade head
```

في staging والإنتاج يجب أن يكون `AUTO_CREATE_TABLES=false`. يرفض التطبيق الاعتماد على إنشاء schema صامتاً عند غياب migration state.

## تشغيل البوت

```bash
export PYTHONPATH=.
python main.py
```

يستخدم التشغيل المحلي long polling عندما يكون `TELEGRAM_WEBHOOK_URL` فارغاً. لا تستخدم polling وwebhook معاً؛ Telegram يجعل طريقتي استقبال التحديثات متنافيتين [1].

## أول تحقق

نفذ ما يلي بالترتيب:

```bash
python -m compileall -q -f .
python -m pytest tests/ -q -W error
python -m pip check
```

إذا أردت اختباراً فعلياً على مجموعة staging، اتبع [`../runbooks/telegram-staging.md`](../runbooks/telegram-staging.md) ولا تستخدم مجموعة إنتاج.

## الإيقاف

أوقف العملية بـ`Ctrl+C`، ثم أغلق Celery وRedis وPostgreSQL حسب طريقة تشغيلها. لا تترك worker أو beat يعملين على قاعدة اختبار مشتركة بعد انتهاء التجربة.

## الخطوات التالية

اقرأ [`configuration.md`](configuration.md) لضبط كل المتغيرات، ثم [`docker.md`](docker.md) للتشغيل بالحاويات، ثم [`../development/testing.md`](../development/testing.md) قبل تعديل الكود.

## المراجع

[1]: https://core.telegram.org/bots/api#receiving-updates "Telegram Bot API — receiving updates"
[2]: https://alembic.sqlalchemy.org/en/latest/ "Alembic documentation"
