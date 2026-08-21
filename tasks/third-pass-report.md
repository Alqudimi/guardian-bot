# تقرير الجولة الثالثة — Guardian Bot

## نطاق الجولة

تم التعامل مع محتوى الطلب الثالث كتعليمات تنفيذية، ثم أعيد تشغيل خط الأساس من الحالة الحالية قبل أي تعديل. كان الخط الأساس compileall ناجحاً و176 اختباراً ناجحاً باستخدام `pytest -W error`. ركزت الجولة على فجوات schema/migrations التي ثبتت بالتشغيل الفعلي، مع الحفاظ على المعمارية الحالية وعدم إعادة كتابة المشروع.

## المشكلات التي ثبتت بالتشغيل

| المشكلة | الدليل الفعلي |
|---|---|
| Alembic لا يملك أي revision head | `alembic heads` لم يعرض revision قبل الإضافة |
| قالب Alembic مفقود | `alembic revision --autogenerate` فشل بـ `FileNotFoundError` بسبب `migrations/script.py.mako` |
| نماذج المتجر غير مسجلة في Alembic metadata | `migrations/env.py` كان يستورد core Base فقط رغم وجود shop models مبنية على Base نفسه |
| baseline المولدة احتوت import ناقصاً | `alembic upgrade head` فشل بـ `NameError: Text is not defined` |
| JSONB المباشر لا يعمل في SQLite المحلي | upgrade و`init_db` فشلا بـ `UnsupportedCompilationError` عند إنشاء JSONB |
| `create_all` كان يمكن أن ينشئ schema في production | `init_db` لم يكن يملك بوابة واضحة تفرض migrations |

## التغييرات المنفذة

تمت إضافة `migrations/script.py.mako`، واستيراد `src.shop.models` داخل `migrations/env.py`، وتوليد baseline revision باسم `e28d7e1c3e09_initial_guardian_schema.py` يغطي جداول core والمتجر. تم تصحيح imports الناقصة، ثم جعل أنواع JSON في revision تستخدم `sa.JSON()` مع `postgresql.JSONB()` كـ variant للإبقاء على نوع JSONB في PostgreSQL والسماح باختبار SQLite.

تم تعريف `JSON_TYPE` مركزياً في `src/db/models.py` واستخدامه في core وshop models، ما أصلح فشل `AUTO_CREATE_TABLES` في SQLite دون تغيير دلالة PostgreSQL. كما أضيف إعداد `AUTO_CREATE_TABLES` إلى Settings و`.env.example`، مع default development مريح ورفض صريح لتفعيله في production/staging.

تم تعديل `init_db` بحيث ينشئ الجداول فقط عندما يكون الخيار مفعلاً في development. في production/staging يتحقق من وجود `alembic_version` ويرفض التشغيل برسالة واضحة إذا لم تُنفذ `alembic upgrade head`، بدلاً من إنشاء schema بصمت.

## الاختبارات والتحقق

| الفحص | النتيجة |
|---|---|
| `python -m compileall -q -f .` | ناجح |
| `python -m pytest tests/ -q -W error` | **179 passed** |
| coverage على `src` و`config` | 36% إجمالياً |
| `pip check` | No broken requirements found |
| `pip-audit -r requirements.txt` | No known vulnerabilities found |
| `alembic upgrade head` على SQLite فارغة | ناجح |
| `alembic check` بعد upgrade | ناجح: No new upgrade operations detected |
| `alembic downgrade base` | ناجح |
| development `init_db` probe | نجح وأنشأ schema فعلياً |
| production `init_db` gate probe | نجح في الرفض قبل schema migration |
| full Ruff | ما زال يفشل بسبب مخالفات تاريخية موزعة في features والhandlers والموديلات؛ لم يتم إخفاؤها |

اختبار migration تم على SQLite disposable فقط؛ لم يتوفر PostgreSQL حقيقي في البيئة، ولذلك لم يتم الادعاء باختبار PostgreSQL production. تم الحفاظ على JSONB في PostgreSQL عبر `with_variant`، وتبقى توصية إلزامية تشغيل upgrade على PostgreSQL staging قبل production.

## الملفات الجديدة والمعدلة المهمة

تم تعديل `config/settings.py` و`src/db/session.py` و`src/db/models.py` و`src/shop/models.py` و`migrations/env.py` و`.env.example` و`README.md` و`AGENT.md` و`pyproject.toml`. وتمت إضافة `migrations/script.py.mako` و`migrations/versions/e28d7e1c3e09_initial_guardian_schema.py` واختبارات schema إلى `tests/test_hardening_regressions.py`، إضافة إلى ملفات تقارير الجولة الثالثة.

## القيود والخطوات التالية

لم يتم اختبار migration على PostgreSQL حقيقي، ولم يتم تنفيذ Bot API حي أو بناء Docker لعدم توفر PostgreSQL/token ومجموعة Telegram وDocker daemon. كما أن coverage ما زالت 36% وRuff ما زال يعرض ديناً تقنياً تاريخياً؛ الخطوة التالية المناسبة هي إنشاء بيئة staging حقيقية بـ PostgreSQL وRedis وتشغيل upgrade/check/rollback عليها، ثم تقسيم إصلاحات Ruff واختبارات التكامل حسب الطبقات بدلاً من إعادة تنسيق المشروع عشوائياً.
