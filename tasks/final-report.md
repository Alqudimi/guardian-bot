# تقرير تدقيق وتطوير Guardian Bot

**التاريخ:** 18 أغسطس 2026

## الملخص التنفيذي

تم فحص الأرشيف المرفق واستخراج صورة تشغيلية كاملة للمشروع، ثم تنفيذ دفعة مركزة من التحسينات ذات الأثر الأعلى على الأمان والاستقرار وقابلية التشغيل. حافظت التعديلات على المعمارية متعددة الطبقات، ولم تستبدل المنسق أو إطار Telegram، لكنها أصلحت حدوداً كانت تمنع الاختبارات أو تضعف التفويض أو تجعل بعض الميزات لا تُسجل فعلياً.

كان خط الأساس الأولي يحتوي على **119 اختباراً ناجحاً و36 اختباراً فاشلاً**. سبب الفشل المركزي هو أن validator إعداد `TELEGRAM_ADMIN_IDS` لا يتعامل مع وصول معرف واحد كعدد صحيح. بعد الإصلاح وإضافة اختبارات أمان وتكامل Redis وsmoke test للإقلاع الكامل أصبحت النتيجة **166 اختباراً ناجحاً**، مع مرور `compileall` و`pip check`، وتقرير `pip-audit` بلا ثغرات معروفة في الاعتماديات المفحوصة.

> النتيجة الحالية قوية على مستوى الشيفرة والاختبارات المحلية، لكنها ليست اعتماداً لاختبار Telegram حي؛ لا يوجد token حقيقي أو مجموعة اختبار أو Docker daemon في البيئة المعزولة.

## نطاق الفحص

المشروع Python غير متزامن ويحتوي على 120 ملف Python تقريباً بعد إضافة الاختبارات، ويضم مسار إشراف متعدد الطبقات، ميزات إضافية، ألعاباً، متجراً، PostgreSQL، Redis، Celery، وطبقات اختيارية لنماذج الذكاء الاصطناعي. تمت مراجعة نقطة الدخول، إعدادات البيئة، تسجيل handlers، منسق pipeline، تنفيذ إجراءات Telegram، webhook hardening، Redis singleton، سجل الميزات، Docker/Compose، الاعتماديات، الاختبارات، والتوثيق.

| المجال | الحالة بعد التطوير | الدليل |
|---|---|---|
| الصياغة البرمجية | ناجحة | `python -m compileall -q -f .` |
| اختبارات المشروع | ناجحة | 166 اختباراً ناجحاً |
| Redis التكاملـي | ناجح محلياً | Redis 7 محلي حقيقي، واختبارات cooldown وwebhook dedup |
| الاعتماديات المثبتة | ناجحة | `pip check` بلا تعارضات |
| الثغرات المعروفة في الاعتماديات | لا نتائج معروفة | `pip-audit -r requirements.txt` |
| lint | غير مكتمل | توجد مخالفات تاريخية عديدة؛ تقريرها مرفق ولم تُخفَ |
| بناء Docker | غير منفذ | Docker daemon غير متاح في البيئة |
| Telegram Bot API حي | غير منفذ | لا يوجد token حقيقي أو مجموعة اختبار |

## الإصلاحات الأمنية والمنطقية المنفذة

### إعدادات التشغيل والأسرار

تم جعل token الافتراضي فارغاً بدلاً من قيمة اختبار قابلة للالتباس، وإضافة تحقق من صيغة token، والتحقق من أن production وstaging لا يعملان بلا token. كما يدعم parser معرفات الإدارة كقيمة مفردة أو CSV أو JSON list أو قائمة رقمية، ويرفض القيم السالبة وغير الصحيحة ويزيل التكرارات.

عند تفعيل webhook أصبح HTTPS إلزامياً وسر webhook إلزامياً بطول URL-safe محدد. كذلك تم إزالة token من مسار webhook؛ التطبيق يستخدم الآن `/telegram-webhook` بدلاً من وضع credential داخل URL. هذا متوافق مع توصية Telegram الرسمية باستخدام `secret_token` الذي يصل في header `X-Telegram-Bot-Api-Secret-Token` [1]، ومع سلوك `python-telegram-bot` الذي يرفض webhook عند غياب header أو خطئه عند استخدام `secret_token` [2].

### تفويض الإدارة

كان التفويض يعتمد على وجود `effective_user.id` في قائمة عامة فقط. أُضيفت طبقة `src/security/admin_authorization.py` التي تشترط القائمة المسموح بها، ثم تستدعي Telegram `get_chat_member` داخل المجموعة وتقبل فقط رتبة `administrator` أو `creator`. عند فشل الاستعلام أو عدم وجود العضو كمسؤول يُرفض الأمر بدلاً من السماح الوقائي. طُبقت السياسة على أوامر الإدارة في `admin_commands.py` وأوامر الأمان في `message_handler.py`.

### Redis وسباقات التنفيذ

أصبح حجز تبريد المستخدم في `action_execution.py` عملية `SET NX EX` ذرية قبل استدعاء Bot API، ما يمنع تحديثين متزامنين من تجاوز التبريد قبل تسجيل الإجراء الأول. كما أصبح dedup لـ webhook يستخدم `SET NX EX`، وأضيفت قيمة فريدة لكل عضو في sliding-window rate limiter لتجنب تصادم timestamp المتساوي.

تم إصلاح Redis singleton ليكتشف انتقاله بين event loops، ويسقط pool المرتبط بحلقة مغلقة دون محاولة إغلاقه على loop غير صالح. هذا أصلح فشل تكامل حقيقي ظهر عند تشغيل اختبارات pytest غير المتزامنة.

### منع السلوك الأمني غير الحتمي

أُلغي مسار `borderline miss simulation` الذي كان يسمح عشوائياً بمرور نسبة من الحالات ذات الخطورة المتوسطة. بقيت دالة التوافق موجودة لكنها تعيد `False` دائماً، وأصبح التأخير مجرد pacing لا يغير القرار الأمني. كما نُقل تسجيل نشاط pacing من وقت حساب التأخير إلى ما بعد نجاح الإجراء الفعلي.

### السجلات والبيئة

تم ربط `token_guard` بمعالج structlog مركزي لتنقيح token وDSN وJWT ومفاتيح شائعة قبل وصولها إلى renderer. كذلك لم يعد Redis URL الذي قد يتضمن كلمة مرور يُكتب في سجل الاتصال. وأضيفت ملفات `.env` وقواعد البيانات المحلية إلى `.gitignore` مع إبقاء `.env.example` فقط.

## إصلاحات الوظائف والتشغيل

كان `register.py` يحاول استيراد وحدات غير موجودة مثل `anti_spam` و`moderation` و`welcome` و`rules` و`captcha`، ما كان يولد أخطاء عند كل إقلاع. تم استبدال ذلك بتسجيل ديناميكي للوحدات الموجودة فعلياً: azkar وinstagram وmedia_downloader وquotes وquran وsmart_detect وsoundcloud وvoice_chat، مع فشل اختياري واضح إذا غابت تبعية مستقبلية.

كان callback العام يطابق كل callbacks تقريباً، وكان game message handler مسجلاً في نفس المجموعة قبل تحديد فصل واضح. تم تقييد callback العام إلى أنماطه الفعلية، ووضع handlers الألعاب في المجموعة 1 بعد مسار الإشراف، مع pattern صريح لـ `game:`. في اختبار بناء Application الفعلي سُجلت 87 handler ضمن المجموعات 0 و1 و2، مع 18 لعبة ونظام المتجر والميزات الإضافية دون أخطاء تسجيل.

تم ضبط أوامر `/mute` و`/ban` لتستخدم حدوداً صريحة للمدة وترفض القيم السالبة أو غير الواقعية. كما أُضيفت حزمة `python-telegram-bot` و`transformers` إلى requirements التي كانت تفتقدهما رغم أن التطبيق يستوردهما فعلياً. وأُعيد بناء `pyproject.toml` من تعريف ملوث بمئات مصادر PyTorch غير المرتبطة إلى تعريف نظيف متوافق مع requirements وpytest وruff وpip-audit.

## Docker وCompose

تم إصلاح Dockerfile الذي كان يفتقد image base، وإضافة Python 3.11 slim، متغيرات Python الآمنة، مستخدم غير root، وعدم الاحتفاظ بـ pip cache. في Compose أُزيلت كلمات مرور PostgreSQL الثابتة، وأصبحت القيم تأتي من `.env`، ولم تعد PostgreSQL وRedis منشورتين كمنافذ عامة. أضيفت `no-new-privileges` و`read_only` و`tmpfs` وhealth checks واعتماديات service health.

لم يتم تنفيذ `docker build` لأن Docker daemon غير متاح في sandbox. لذلك يجب تشغيل البناء في بيئة تشغيلية فعلية قبل النشر، خصوصاً للتحقق من حزم `py-tgcalls` و`torch` وباقي الاعتماديات الأصلية.

## الاختبارات والتحقق

أضيف الملف `tests/test_hardening_regressions.py` ويغطي parsing إعدادات الإدارة، رفض production بلا token، قواعد webhook، تفويض الإدارة داخل المجموعة، رفض أخطاء `get_chat_member`، تنقيح السجلات، عدم إسقاط borderline actions، حجز cooldown ذري عبر Redis حقيقي، dedup لـ webhook عبر Redis حقيقي، وبناء Application الكامل.

| الفحص | النتيجة |
|---|---|
| `python -m compileall -q -f .` | ناجح |
| `python -m pytest tests/ -q` | 166 passed |
| `pip check` | No broken requirements found |
| `pip-audit -r requirements.txt` | No known vulnerabilities found |
| بناء Application الكامل | ناجح، 87 handler، مجموعات 0 و1 و2 |
| coverage | 21% إجمالي، مع فجوات كبيرة في handlers وميزات AI والمتجر |
| `ruff check .` | غير ناجح؛ مخالفات تاريخية كثيرة مذكورة في التقرير المرفق |

نسبة coverage الإجمالية 21% لا تعني أن الإصلاحات غير مختبرة؛ بل تعكس اتساع المشروع ووجود ميزات وhandlers كثيرة لم تكن مغطاة في خط الأساس. أهم الفجوات المتبقية هي `message_handler.py` و`admin_commands.py` و`action_execution.py` و`audit_logging.py` وطبقات AI والميزات الخارجية.

## القيود والمتطلبات الخارجية المتبقية

لم تُنفذ اختبارات PostgreSQL تكاملية لأن PostgreSQL وDocker daemon غير متاحين. ما زالت `init_db()` تستخدم `Base.metadata.create_all` مع وجود تعليق يوصي باستخدام Alembic؛ الخطوة الإنتاجية التالية هي إنشاء migration baseline وتشغيل `alembic upgrade head` عند الإقلاع أو ضمن job مستقل، بدلاً من الاعتماد على create-all.

لم تُنفذ أفعال Telegram المدمرة فعلياً. تنفيذ حذف أو حظر حي يحتاج token حقيقياً ومجموعة اختبار مخصصة يملكها المستخدم، ويفضل تشغيله أولاً في dry-run ثم اختبار مستخدم تجريبي غير حساس. لا ينبغي استخدام token المرفق في أي اختبار أو تسليمه داخل التقرير.

ما زال lint الكامل يحتوي على دين تقني تاريخي في الألعاب والميزات والمتجر وقاعدة البيانات. لم يتم إجراء إعادة تنسيق واسعة لهذه الملفات حتى لا يتغير سلوك ميزات غير مغطاة، لكن التقرير `tasks/ruff-findings-final.txt` يحددها كاملة، ويمكن معالجتها على شرائح مستقلة.

## الملفات الرئيسية المعدلة

تم تعديل `config/settings.py` و`main.py` و`Dockerfile` و`docker-compose.yml` و`requirements.txt` و`pyproject.toml` و`.env.example` و`.gitignore` و`README.md` و`AGENT.md`، إضافة إلى `src/security/admin_authorization.py` و`human_behavior.py` و`token_guard.py` و`webhook_hardening.py` و`src/utils/logger.py` و`src/utils/redis_client.py` و`src/layers/action_execution.py` وملفات handlers و`src/features/register.py`. أضيفت اختبارات hardening وتقارير التدقيق تحت `tasks/`.

## التوصية التالية

الأولوية التالية هي إنشاء migration baseline لـ PostgreSQL، إضافة اختبارات تكاملية لمسار pipeline غير المدمر، ثم تقسيم lint debt إلى شرائح: handlers، التنفيذ الأمني، features الخارجية، الألعاب، والمتجر. بعد توفير مجموعة Telegram اختبار وtoken حقيقي يمكن تنفيذ smoke test حي محدود الصلاحيات، ثم الانتقال إلى تشغيل webhook خلف reverse proxy مع secret token وإدارة الأسرار خارج ملفات Compose.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API — setWebhook secret_token and administrator rights"
[2]: https://docs.python-telegram-bot.org/en/stable/telegram.ext.updater.html "python-telegram-bot v22.8 — Updater.start_webhook"
