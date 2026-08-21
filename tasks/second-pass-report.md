# تقرير الجولة الثانية — Guardian Bot

**التاريخ:** 18 أغسطس 2026

## النطاق والقاعدة المتبعة

تمت قراءة ملف الطلب الثاني باعتباره تعليمات تنفيذ ملزمة، ثم أُعيد فحص المشروع من حالته الحالية قبل أي تعديل. لم يُفترض وجود مكونات غير مثبتة، ولم تُجرَ إعادة كتابة شاملة. كل تعديل في هذه الجولة بدأ بملاحظة من الكود أو اختبار أو تشغيل فعلي، ثم أُعيد تشغيل الاختبارات بعده.

## خط الأساس قبل الجولة

كان المشروع في الحالة التي انتهت إليها الجولة الأولى: compileall يمر و166 اختباراً يمر. أعيد تشغيل الخط الأساس فعلياً قبل التعديل، فنجح compileall و166 اختباراً. شملت المراجعة أيضاً جداول SQLAlchemy الفعلية، ومواضع قراءة Settings عند import، ومجرى link analysis وSSRF وdynamic blacklist وrate budgets.

## المشكلات المثبتة والتعديلات المنفذة

| المشكلة المثبتة | التعديل الفعلي | التحقق |
|---|---|---|
| `delete_rate_per_minute` كان يظهر في budget لكنه لا يمنع التنفيذ | إضافة Lua script ذري في `action_execution.py` يحجز delete slot قبل Bot API | اختبار Redis حقيقي لسقف واحد |
| تصادم أعضاء sorted sets عند تطابق timestamp | إضافة UUID إلى action/flood/raid members | suite كاملة |
| `anti_ban` يقرأ Settings عند import | نقل القراءة إلى داخل الدوال | اختبار runtime budget |
| link expansion لا يستعمل SSRF guard ولا يتحقق من redirect النهائي | استدعاء `validate_url` قبل وبعد redirect مع max redirects | اختبار loopback فعلي |
| DNS resolution blocking داخل event loop | نقل resolver إلى `asyncio.to_thread` وfail-closed عند الفشل | suite وwarnings-as-errors |
| dynamic regex قد يسبب ReDoS أو تخزين pattern طويل | مكتبة `regex`، حد 512 محرفاً، timeout 50ms، حد إدخال 4096، والتحقق في command | اختبار regex طويل ومهلة |
| قص النص الطويل قد ينتج match خاطئاً عند الحد | تجاوز dynamic search للنص الأكبر من الحد بدلاً من قصه | اختبار regression |
| empty cache marker كان يُكتب ولا يُقرأ | short-circuit قبل استدعاء PostgreSQL عند marker | اختبار Redis حقيقي |
| إعدادات رقمية صفرية أو سالبة كانت تقبل | validators للحدود الأمنية ومنافذ webhook | اختبارات حالات حدية |
| تفاصيل أخطاء DB كانت تُرسل للمشرف | logging داخلي برسائل Telegram عامة في أوامر patterns | compile وsuite |
| Settings مثبتة عند import في عدة layers | تحويل AI/audit/behavior/flood/media/raid/link إلى runtime settings | grep بعدي وsuite |
| ResourceWarning من Redis pools بين event loops | `tests/conftest.py` يغلق pool بعد كل اختبار | `pytest -W error` يمر |
| معالجة `zip(urls, results)` كانت تتجاوز أول 10 روابط بصمت | `zip(urls[:10], results, strict=True)` | compile وsuite |

## التحقق النهائي

| الفحص | النتيجة الفعلية |
|---|---|
| `python -m compileall -q -f .` | ناجح |
| `python -m pytest tests/ -q -W error` | **176 passed** |
| coverage على `src` و`config` | 36% إجمالياً |
| `pip check` | No broken requirements found |
| `pip-audit -r requirements.txt` | No known vulnerabilities found |
| targeted Ruff | ما زالت هناك مخالفات legacy موثقة في `tasks/ruff-second-pass-targeted-after-fix.txt` |

نسبة coverage الحالية 36% بعد إضافة اختبارات الجولة الثانية. الفجوات الكبرى ما زالت في الميزات الخارجية، handlers، AI، audit logging، وpipeline الكامل، لأن تشغيلها يتطلب قواعد بيانات أو Telegram أو نماذج خارجية. لم تُحوّل هذه الفجوات إلى assertions وهمية.

## ملاحظة عن الاختبارات الحقيقية

اختبارات Redis في هذه الجولة استخدمت Redis محلياً فعلياً، لا fake أو mock. اختبار SSRF يتحقق من منع loopback قبل الاتصال. اختبار Application يبني PTB Application ويسجل handlers فعلياً دون طلب Telegram حي. لم تُنفذ أوامر حذف أو حظر على Telegram حقيقي لعدم توفر token ومجموعة مخصصة؛ لذلك لا يُدّعى إجراء اختبار Bot API حي.

## ما لم يُنفذ ولماذا

لا توجد ملفات versioned migrations فعلية تحت `migrations/versions`، وقاعدة البيانات تشمل جداول core وshop متعددة. لذلك لم يتم اختلاق migration يدوياً دون PostgreSQL فعلي. الخطوة الصحيحة التالية هي إنشاء baseline عبر Alembic في بيئة PostgreSQL، ثم اختبار `upgrade` و`downgrade` وstartup preflight.

لم يتم إعادة تنسيق المشروع كله لإجبار Ruff على النجاح، لأن ذلك سيغير عدداً كبيراً من الملفات غير المغطاة وقد يخفي مخاطر سلوكية. تم تطبيق الإصلاحات الآلية الآمنة على الملفات المتأثرة، وأُبقيت المخالفات التاريخية في تقرير مستقل بدلاً من إسكاتها.

## مراجع الويب

تؤكد وثائق Telegram Bot API الرسمية دعم `secret_token` في webhook ووجود `getChatMember` وطرق الإدارة [1]. وتؤكد وثائق python-telegram-bot الحالية v22.8 دعم الواجهة asynchronous وwebhook وpolling وrate limiting [2].

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/stable/ "python-telegram-bot v22.8"
