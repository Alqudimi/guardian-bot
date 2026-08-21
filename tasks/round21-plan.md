# خطة الجولة الحادية والعشرون — sweep شامل قابل للإثبات

## الهدف

تنفيذ الفجوات البرمجية القابلة للإصلاح التي ظهرت في التدقيق الشامل، مع فصلها عن الأعمال التي تتطلب Telegram أو PostgreSQL أو Celery worker أو providers أو Docker/staging حقيقية.

## التغييرات المنفذة

| الفجوة | الإجراء |
|---|---|
| CAPTCHA timeout lifecycle | نقل task إلى `create_background_task` حتى يدخل registry ويُلغى في shutdown |
| CAPTCHA config drift | توحيد gate مع `group_settings` وإضافة lazy migration للمفتاح القديم وحذفه عند write/reset |
| RUF012 في game registry | استخدام `ClassVar` للـGameManager registry |
| F821 في shop admin | استيراد `OrderValidationError` من `order_engine` |
| shop time-dependent tests | تثبيت وقت النهار داخل الاختبار فقط لعزل discount ليلي مقصود |
| Ruff technical debt | تطبيق الإصلاحات الآلية الآمنة المتاحة، مع عدم تطبيق unsafe fixes على كود دلالي عشوائياً |

## معايير القبول

نجاح suite كاملة مع `-W error`، compileall، pip check، pip-audit، وفحص Ruff correctness على الملفات المعدلة، مع اختبار إيجابي وسلبي وفشل لمسار CAPTCHA canonical وlifecycle.

## الحدود

اختبارات Telegram الحية، PostgreSQL production، Celery broker/worker، PyTgCalls، yt-dlp، payment providers، Docker daemon، staging rollout، وقياس الأداء لا يمكن تنفيذها داخل البيئة الحالية. كما بقي instant fulfillment وMafia scoring غير منفذين عمداً لغياب executor/provider وscoring contract حقيقيين.
