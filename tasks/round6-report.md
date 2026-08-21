# تقرير الجولة السادسة: تدقيق الوظائف والعمليات والـlifecycle

## الملخص التنفيذي

ركزت هذه الجولة على ما يفعله البوت فعلياً أثناء التشغيل: استقبال تحديث Telegram، توجيه handler، تنفيذ moderation pipeline، اتخاذ القرار، تنفيذ الإجراء، حفظ الإحصاءات، إدارة الانضمامات والـraid، تشغيل الألعاب والمتجر والميزات المساعدة، وإغلاق الموارد. لم يُعتبر وجود ملف أو handler دليلاً كافياً على أن الوظيفة مكتملة؛ تم تتبع callers، نقاط lifecycle، Redis keys، مسارات قاعدة البيانات، والاختبارات.

أثبت التدقيق ثلاث فجوات تشغيلية مهمة. أولاً، كان voice backend يملك دالة بدء حقيقية، لكن لم يكن هناك caller في startup، لذلك كان يمكن أن تُقبل أوامر الموسيقى بينما لا يبدأ Pyrogram/PyTgCalls. ثانياً، كان raid detector يضع مفتاح Redis بمدة خمس دقائق دون جدولة استدعاء `release_lockdown`، ما قد يترك slow mode وصلاحيات Telegram مقيدة بعد انتهاء TTL. ثالثاً، كانت بنية التقارير تعلن مؤشرات raids وtop offenders وcircuit trips دون أن تكتب أو تقرأ هذه المؤشرات.

تم إصلاح الفجوات دون إعادة بناء المعمارية. أصبحت دورة الصوت والـraid والتقارير قابلة للاختبار، وأصبحت الوثائق تعكس ما يعمل فعلياً وما يحتاج خدمة خارجية.

## خريطة دورة التشغيل التي تمت مراجعتها

رسائل المجموعات تبدأ من `handle_message` ثم `run_pipeline`. يبدأ المسار بفحص DoS، وتسجيل نشاط المجموعة والمستخدم، وفحص cross-group threat، ثم normalization وfast rules، ثم flood وbehavioral بالتوازي، وaccount intelligence، وevasion، وتحليل near-duplicate وlink وmedia وanti-forward بالتوازي، ثم language guard وAI عند ملاءمة الموارد، ثم risk scoring وdecision engine وaction execution. بعد الإجراء تُنفذ audit logging وmod-log وstatistics بالتوازي.

أحداث الأعضاء الجدد تمر عبر account join tracking وraid detection، ثم CAPTCHA أو welcome flow. الأوامر والـcallbacks للميزات والألعاب والمتجر تسجل في Application، بينما يتم تشغيل Redis وDB خلال lifecycle. Celery worker وbeat يعملان كخدمتين منفصلتين في Docker Compose، وليس كجزء من event loop الخاص بالبوت.

## الفجوات المثبتة قبل التنفيذ

| الأولوية | الفجوة | الأثر | المعالجة |
|---|---|---|---|
| عالية | `start_voice_backend()` بلا caller في startup | الصوت الحقيقي قد لا يبدأ رغم ظهور أوامر الموسيقى | استدعاء startup وإضافة shutdown منظم |
| عالية | Redis TTL للـraid بلا cleanup Telegram مجدول | قد تبقى قيود المجموعة بعد انتهاء TTL | JobQueue باسم ثابت لكل مجموعة يستدعي `release_lockdown` |
| متوسطة | حقول report للـraids وoffenders وcircuit غير مملوءة | تقرير `/report` ناقص مقارنة بالعقد المعلن | writers من مسارات الأحداث وreader/formatter واختبار roundtrip |
| متوسطة | Celery tasks معرفة، وبعضها بلا enqueue caller | لا يجوز اعتبار deferred domain/batch processing جزءاً من bot hot path | إبقاء الحدود واضحة وتوثيق worker/beat كعملية منفصلة دون enqueue عشوائي |
| منخفضة | `_safe` يستمر بعد فشل layer بالقيم الافتراضية | الاعتمادية جيدة، لكن fail-closed يحتاج سياسة لكل طبقة | لم يُغيّر عشوائياً؛ سُجل كموضوع مستقل يحتاج تحليلاً طبقيّاً |

## التعديلات المنفذة

### دورة voice backend

تم ربط `start_voice_backend()` داخل `main.post_init`. يبدأ backend فقط عندما تتوفر إعدادات واعتماديات الصوت، ويظل فشل هذه الميزة معزولاً عن تشغيل moderation. أضيف `stop_voice_backend()` إلى `post_shutdown`، وهو يلغي player loops النشطة، ينتظر انتهائها، يستدعي stop للعملاء المتاحين، ثم يمسح الحالة العامة. جعلت عملية البدء idempotent عندما تكون الحالة جاهزة، وسُجلت الأخطاء بنوع الاستثناء بدلاً من أسرار الإعدادات.

هذا لا يدعي أن voice chat يعمل في بيئة الاختبار؛ الاختبارات تتحقق من lifecycle wiring والتدهور الآمن، بينما الانضمام إلى voice chat يحتاج Pyrogram session وTelegram API حي.

### raid auto-release

أصبح `check_raid` يعيد `True` فقط عند تفعيل lockdown جديد، ولا يعيد جدولة cleanup عند كل انضمام أثناء lockdown قائم. عند التفعيل، يستدعي `handle_new_member` `schedule_lockdown_release`. هذه الدالة تزيل أي Job سابق باسم `raid-lockdown:<chat_id>` ثم تسجل `run_once` بعد 300 ثانية. Callback `auto_release_lockdown` يتحقق من chat ID ثم يستدعي مسار `release_lockdown` الحقيقي.

إذا لم يكن `context.job_queue` متاحاً، تُسجل حالة `raid_auto_release_unavailable`. هذا يمنع ادعاء auto-release في بيئة لا تدعمه، ويترك الحالة مرئية للمراقبة بدلاً من إخفائها.

### تقارير moderation الفعلية

تم توسيع `record_action_stat` لقبول `user_id` وحفظه في Redis sorted set يومي. عند توليد التقرير، تُجمع النتائج عبر الأيام وتُرتب أعلى خمسة مستخدمين. أضيف `record_raid_stat` عند تفعيل raid جديد، و`record_circuit_suppression` عندما يمنع circuit breaker إجراءً عقابياً. أضيفت هذه المؤشرات إلى `format_report`.

في المقابل، أزيلت الادعاءات غير الموصولة من docstring: لا يوجد حالياً daily/weekly automatic delivery ولا risk distribution في generator، ولذلك لا يعلن التقرير عنهما. Celery beat الحالي موثق على أنه يشغل trust-score maintenance فقط.

## الاختبارات والتحقق

أضيف `tests/test_operations_round6.py` لاختبار startup/shutdown lifecycle، failure isolation للـvoice backend، استبدال JobQueue للمهمة القديمة، واستدعاء release الحقيقي من callback. كما أضيف اختبار Redis تكاملي حقيقي يكتب action وraid وcircuit metrics ثم يقرأ تقريراً من Redis ويثبت `top_offenders` وحقول الأحداث. وتم توسيع `tests/test_management.py` لتغطية formatting والتقارير الجديدة.

| الفحص | النتيجة |
|---|---:|
| `python -m compileall -q -f .` | ناجح |
| `pytest tests/test_operations_round6.py tests/test_management.py -q -W error` | **40 ناجحاً** |
| `pytest tests/ -q -W error` | **175 ناجحاً** |
| `pip check` | لا توجد متطلبات مكسورة |
| `pip-audit -r requirements.txt` | لا توجد ثغرات معروفة في نتيجة الفحص الحالية |
| Ruff للملف الجديد `tests/test_operations_round6.py` | يجب أن يبقى فحصه مستقلاً عن مخالفات الملفات التاريخية |
| Ruff العام/ملفات قديمة | ما زالت مخالفات تاريخية متعددة خارج نطاق الجولة |

## الحدود التشغيلية والقرارات المؤجلة

لم يُنفذ Bot API حي، ولا voice backend حي، ولا JobQueue فعلي متصل بمجموعة Telegram؛ السبب عدم توفر token حقيقي ومجموعة اختبار وPyrogram session. Redis المحلي استُخدم فعلياً لاختبار roundtrip التقارير، أما Telegram API فبقي معزولاً في اختبارات wiring.

تعريف Celery موجود وله worker وbeat في `docker-compose.yml`، لكن `update_domain_reputation` و`batch_log_events` لا يملكان enqueue calls من hot path. لم يتم ربطهما عشوائياً لأن ذلك يحتاج سياسة تشغيل واضحة، retry، مراقبة broker، وحدوداً تمنع تراكم المهام. هذا قرار أمان وتشغيل، وليس ادعاءً بأنهما جزء من المسار الحي.

فحص Ruff العام لا يزال يظهر مخالفات سابقة في المشروع، منها import ordering وline length وبعض قواعد logging وexception handling. لم تُجرَ عملية auto-fix واسعة لأنها قد تعدل مئات الأسطر خارج نطاق الجولة وتزيد خطر التراجع. تم فحص الاختبار الجديد مستقلاً، وتشغيل suite كاملة مع `-W error`.

## الملفات الرئيسية

| الملف | الدور في الجولة |
|---|---|
| `main.py` | ربط voice startup/shutdown داخل lifecycle |
| `src/features/voice_chat.py` | start/stop حقيقي وتنظيف player tasks |
| `src/pipeline/raid_detector.py` | JobQueue auto-release وتوحيد مدة lockdown |
| `src/handlers/message_handler.py` | جدولة cleanup وتسجيل raid metric |
| `src/management/reports.py` | writers/readers/formatter للمؤشرات الجديدة |
| `src/layers/action_execution.py` | تسجيل circuit suppression للمجموعة |
| `src/pipeline/orchestrator.py` | إسناد moderation action إلى user في الإحصاءات |
| `tests/test_operations_round6.py` | اختبارات lifecycle وJobQueue وRedis roundtrip |
| `tests/test_management.py` | توسيع اختبارات التقارير |
| `tasks/round6-analysis.md` | الأدلة ومصفوفة الأولويات |
| `tasks/round6-ptb-jobqueue-research.md` | المرجع الرسمي لاستخدام JobQueue |
| `tasks/round6-quality.txt` | سجل فحص الجودة ونتيجة pip-audit |

## المراجع

[1]: https://docs.python-telegram-bot.org/en/v22.2/telegram.ext.jobqueue.html "python-telegram-bot JobQueue v22.2"

[2]: https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.callbackcontext.html "python-telegram-bot CallbackContext v22.5"
