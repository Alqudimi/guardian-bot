# إعداد البيئة

## قاعدة عامة

يُحمّل التطبيق الإعدادات من متغيرات البيئة. استخدم `.env.example` كقائمة مرجعية، وانسخها إلى `.env` محلياً. لا ترفع `.env` أو ملفات الأسرار أو كلمات المرور أو tokens إلى GitHub.

## المتغيرات الأساسية

| المتغير | مطلوب | الوصف |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | عند تشغيل Telegram | token من BotFather؛ لا تسجله في logs |
| `TELEGRAM_ADMIN_IDS` | للأوامر الإدارية العامة | قائمة IDs مفصولة بفواصل، ولا تغني عن تحقق رتبة Telegram داخل المجموعة |
| `DATABASE_URL` | staging/production | اتصال SQLAlchemy async، ويفضل `postgresql+asyncpg://` |
| `REDIS_URL` | التشغيل الكامل | Redis للإعدادات والـrate limit والجلسات |
| `ENVIRONMENT` | نعم | `development` أو staging/production حسب إعدادات المشروع |
| `DRY_RUN` | موصى به محلياً | يسجل القرار دون تنفيذ mutation عندما يكون مفعلاً |

## قاعدة البيانات وRedis

```dotenv
POSTGRES_DB=tgbot
POSTGRES_USER=tgbot
POSTGRES_PASSWORD=<strong-random-password>
DATABASE_URL=postgresql+asyncpg://tgbot:<password>@localhost:5432/tgbot
REDIS_URL=redis://:<password>@localhost:6379/0
AUTO_CREATE_TABLES=false
```

في الإنتاج نفذ `alembic upgrade head` من عملية نشر منفصلة أو محكومة، ثم شغل bot. لا تعتمد على `AUTO_CREATE_TABLES` في الإنتاج.

## Telegram transport

```dotenv
TELEGRAM_WEBHOOK_URL=
TELEGRAM_WEBHOOK_PORT=8443
TELEGRAM_WEBHOOK_SECRET=<random-secret-when-webhook-is-used>
```

اترك `TELEGRAM_WEBHOOK_URL` فارغاً لاستخدام long polling. عند استخدام webhook، يجب أن يكون الرابط HTTPS، ويجب إرسال secret header الذي تدعمه Telegram، مع التأكد من أن `allowed_updates` يتضمن `chat_member` إذا كانت الوظائف تعتمد على تحديثات مغادرة الأعضاء [1].

## الدفع

```dotenv
PAYMENT_PROVIDER_TOKEN=
PAYMENT_CURRENCY=USD
```

ترك `PAYMENT_PROVIDER_TOKEN` فارغاً يعطل الإيداع. لا يغير callback أو user state الرصيد. المسار الحقيقي هو pending transaction، ثم invoice، ثم pre-checkout، ثم `successful_payment` مع مطابقة المستخدم والعملة والمبلغ وcharge ID ومنع الاعتماد المكرر.

## النماذج الاختيارية

```dotenv
ARABIC_TOXICITY_MODEL=hossam87/bert-base-arabic-hate-speech
NSFW_MODEL=Marqo/nsfw-image-detection-384
MODEL_CACHE_DIR=./model_cache
MODEL_DEVICE=cpu
```

تحميل النماذج lazy. إذا تعذر الوصول إلى Hugging Face أو لم تُثبت الاعتمادات، يعمل bot بوضع degraded واضح ولا يحول فشل provider إلى حظر مؤكد.

## thresholds وlimits

المتغيرات `TOXICITY_THRESHOLD` و`NSFW_THRESHOLD` و`SPAM_SCORE_THRESHOLD` و`PHISHING_THRESHOLD` تضبط حساسية الإشارات. أما `FLOOD_*` و`BURST_*` و`DUPLICATE_WINDOW_SECONDS` فتحدد نوافذ السلوك. يجب معايرة أي تغيير على false positives قبل استخدامه في production.

متغيرات anti-ban هي `ACTION_RATE_LIMIT_PER_MINUTE` و`ACTION_COOLDOWN_PER_USER_SECONDS` و`BAN_HOURLY_LIMIT` و`DELETE_RATE_PER_MINUTE` و`ACTION_JITTER_MIN/MAX`. هذه آليات تقليل خطر وليست ضماناً ضد rate limits.

## Celery

```dotenv
CELERY_BROKER_URL=redis://:<password>@localhost:6379/1
CELERY_RESULT_BACKEND=redis://:<password>@localhost:6379/2
```

كل task طويل العمر يجب أن يمر عبر registry lifecycle، وكل task يجب أن يكون idempotent أمام redelivery. راجع [`../architecture/data-and-lifecycle.md`](../architecture/data-and-lifecycle.md).

## التحقق من الإعداد

```bash
python -c 'from config.settings import settings; print(settings.environment)'
python -m compileall -q -f .
```

لا تطبع الكائن الكامل للإعدادات إذا احتوى أسراراً. استخدم `/status` أو diagnostic محدوداً يعرض حالة configured/unavailable دون القيم السرية.

## المراجع

[1]: https://core.telegram.org/bots/api#chatmemberupdated "Telegram Bot API — ChatMemberUpdated"
[2]: https://core.telegram.org/bots/api#payments "Telegram Bot API — Payments"
[3]: https://docs.celeryq.dev/en/stable/userguide/configuration.html "Celery configuration"
