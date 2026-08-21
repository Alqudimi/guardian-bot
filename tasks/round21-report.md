# تقرير الجولة الحادية والعشرين — sweep شامل قابل للإثبات

**المشروع:** Guardian Bot — TelegramBot  
**النطاق:** مراجعة الأعمال المؤجلة، lifecycle، group settings، صحة الكود، واختبارات الأقسام المتأثرة  
**الحالة:** مكتملة داخل البيئة المعزولة مع فصل صريح للأعمال الخارجية  
**الكاتب:** Manus AI

## الملخص التنفيذي

طُلب تنفيذ الأعمال المتبقية بالكامل وبشكل صحيح. لذلك بدأ العمل بجرد التقارير والكود الفعلي، ثم فُصلت الفجوات التي يمكن إصلاحها داخل المستودع عن الأعمال التي تحتاج خدمات خارجية أو credentials لا تملكها البيئة. نُفذت كل الفجوات البرمجية القابلة للإثبات التي ظهرت في هذا sweep، وأضيفت اختبارات نجاح ورفض وفشل، ثم أُعيد تشغيل suite كاملة وبوابات الجودة.

أصبح CAPTCHA timeout جزءاً من lifecycle registry المركزي بدلاً من raw `asyncio.create_task`. كما أزيل config drift بين `/setcaptcha` ومسار member join؛ أصبحت القراءة والكتابة عبر `group_settings` canonical، مع lazy migration للقيمة القديمة `1/0/on/off/true/false` وحذف legacy key عند migration أو write أو reset.

كذلك أصلحت المراجعة خطأ F821 فعلياً في shop admin باستيراد `OrderValidationError`، وعالجت RUF012 في GameManager عبر `ClassVar`. ظهر أثناء sweep أن shop integrity tests تتأثر بوقت UTC لأنها تتوقع التسعير النهاري بينما production يطبق خصماً ليلياً بنسبة 5%؛ ثُبت الوقت داخل الاختبارات فقط ولم يتغير production pricing.

## مصفوفة التنفيذ

| المجال | الحالة قبل sweep | التنفيذ الحالي | الدليل |
|---|---|---|---|
| CAPTCHA timeout | raw task خارج registry | `create_background_task` باسم `captcha-timeout:{chat}:{user}` | `tests/test_round21_lifecycle.py` |
| CAPTCHA settings | gate يستخدم `captcha_enabled:{chat}` منفصلاً | gate يستخدم `group_settings.captcha` | canonical read/write tests |
| Legacy migration | لا يوجد عقد موحد لمفتاح CAPTCHA القديم | lazy conversion ثم delete | migration test |
| Game registry | mutable class attribute غير معلن | `ClassVar` صريح | F821/E9/F401/RUF012 gate |
| Shop admin | `OrderValidationError` غير مستورد، F821 | import canonical من `order_engine` | full static gate |
| Shop tests | flaky حسب وقت UTC | daytime clock داخل test module فقط | 5 shop tests |
| Ruff | safe auto-fixes متاحة | طُبقت دون unsafe semantic fixes | selected + critical checks |

## الاختبارات والنتائج

| الفحص | النتيجة |
|---|---|
| focused lifecycle/settings suite | **55 passed** |
| suite كاملة `python -m pytest tests/ -q -W error` | **270 passed** |
| `python -m compileall -q -f .` | ناجح |
| `pip check` | `No broken requirements found` |
| `pip-audit -r requirements.txt` | `No known vulnerabilities found` |
| Ruff correctness على الملفات المعدلة | `All checks passed` |
| Ruff critical على كامل `src tests config` (`F821,E9,F401,RUF012`) | `All checks passed` |

لم تُعتبر mocks أو استدعاءات Telegram الحية اختبارات فعلية؛ اختبارات Redis المحلية الحقيقية بقيت ضمن حدودها، ولم يُعلن نجاح PostgreSQL أو Telegram أو providers خارجية.

## sweep الأوسع والدين المتبقي

طُبق `ruff --fix` الآمن على `src tests config`، ونجحت الاختبارات بعده. بقيت مخالفات Ruff العامة الدلالية أو التاريخية خارج correctness gate، وتشمل رسائل استثناء طويلة، أسطر طويلة، Unicode ambiguous، `TRY` logging/raise patterns، random usage في بعض السياقات، وبعض import placement التاريخي. لم تُطبق unsafe fixes آلياً على هذه المواضع لأن ذلك قد يغير semantics في moderation أو payments أو provider boundaries دون اختبار إضافي. هذا دين جودة موثق، وليس ادعاءً بأن كل فحص أسلوبي عام صار صفراً.

## الأعمال الخارجية التي لا يمكن تنفيذها داخل البيئة

| العمل | السبب | الحالة الصحيحة |
|---|---|---|
| Telegram API وstaging group | لا يوجد token حقيقي أو مجموعة وصلاحيات admin | غير منفذ، يحتاج staging آمن وDRY_RUN حيث يلزم |
| PostgreSQL migration/integration | البيئة تستخدم SQLite للاختبارات ولا توفر PostgreSQL خارجي | غير منفذ حياً |
| Celery broker/worker/beat | لا توجد عملية broker/worker تشغيلية للتحقق من delivery وredelivery | task logic موجودة، live topology غير مثبتة |
| PyTgCalls وyt-dlp وpayment provider | credentials وخدمات تنفيذ غير متاحة | لا mock success ولا instant fulfillment |
| Docker build | Docker daemon غير متاح | غير منفذ |
| Mafia scoring | لا يوجد scoring contract معتمد | scoreboard فارغ عمداً |
| performance/staging rollout | لا توجد مجموعة نشطة أو traffic حقيقي | غير منفذ |

> التنفيذ الصحيح لا يعني اختلاق نجاح لهذه الحدود. ما يمكن اختباره محلياً نُفذ واختُبر، وما يحتاج بيئة خارجية بقي معلناً كعمل تشغيلي مؤجل.

## الملفات

التغيير الرئيسي في `src/layers/captcha_gate.py` و`src/management/group_settings.py`. كما عُدّل `src/games/manager.py` و`src/shop/handlers/admin_handler.py`، وأضيفت `tests/test_round21_lifecycle.py`. الخطة في `tasks/round21-plan.md`، وسجل التحقق في `tasks/round21-final-validation.txt`.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html "SQLAlchemy Asyncio Documentation"
[3]: https://docs.celeryq.dev/en/stable/userguide/tasks.html "Celery Tasks Documentation"


## الأرشيف

تم تنظيف cache و`.pyc` و`.pyo` و`.db` و`.coverage` وبناء `Guardian-bot-round21-full-sweep.zip`. يحتوي الأرشيف على **312 ملفاً**، واجتاز `unzip -tq` وفحص المدخلات الممنوعة. SHA-256:

```text
0e894e002c58d95ab091e28e789de489a4742a9a793860d99beed6c94c0381ba
```
