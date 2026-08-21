# تقرير الجولة السابعة عشرة — تقوية atomic warn history

**المشروع:** Guardian Bot — TelegramBot  
**النطاق:** `smart_warn`، Redis concurrency، ومنع فقدان سجلات التحذير  
**الحالة:** مكتملة داخل البيئة المعزولة مع حدود الإنتاج الخارجية موثقة  
**الكاتب:** Manus AI

## الملخص التنفيذي

تابعت الجولة السابعة عشرة أولوية موثقة من مراجعة Round 16. كان `smart_warn.add_warn` ينفذ نمط read-modify-write على JSON history: قراءة key، إضافة السجل في الذاكرة، ثم `SET` و`EXPIRE`. عند وصول تحذيرين متزامنين للمستخدم نفسه داخل المجموعة، كان كلا المسارين يستطيع قراءة الحالة القديمة ثم يكتب فوق تحديث المسار الآخر.

تم استبدال المسار بمعاملة Redis optimistic locking باستخدام `WATCH/MULTI/EXEC` على history key نفسها. كل محاولة تقرأ الحالة بعد `WATCH`، تبني history الجديدة، ثم تكتب `SET` و`EXPIRE` داخل transaction. عند `WatchError` يعاد المحاولة أربع مرات بحد أقصى مع تأخير متزايد صغير. عند فشل Redis أو استنفاد التعارضات لا تُعاد نتيجة نجاح ولا يُسجل `warn_added`، بل يُرفع الخطأ للمسار الأعلى ليتعامل معه وفق degradation الموجود.

> النتيجة الفعلية: ارتفعت suite من **254 اختباراً ناجحاً** في حالة Round 16 إلى **257 اختباراً ناجحاً**، مع نجاح اختبارات التزامن وretry والفشل، إضافة إلى compileall و`pip check` و`pip-audit` وRuff المحدد.

## المشكلة والمسار المتأثر

المشكلة كانت محصورة في `src/layers/smart_warn.py::add_warn`. أما إعداد `warn_limit` فبقي يمر عبر `group_settings` canonical كما تم توحيده في الجولة السابقة. لذلك لم يُنشأ storage جديد ولم تتغير صيغة Redis key؛ التعديل يضيف حماية transaction حول history الحالية فقط.

يوثق Redis أن `WATCH` يوفر optimistic locking شبيهاً بـCAS، وأن transaction تُلغى إذا تغيرت key المراقبة قبل `EXEC` [1]. كما يوضح توثيق redis-py نمط استخدام `async with` مع `pipeline(transaction=True)` في العميل غير المتزامن [2]. استُخدم هذا النمط بدلاً من lock key إضافية لتقليل state الجديد والحفاظ على المعمارية الحالية.

## التغييرات المنفذة

| الملف | التغيير |
|---|---|
| `src/layers/smart_warn.py` | إضافة `_decode_warn_history` و`_warn_status`، واستخدام `WATCH/MULTI/EXEC` مع أربع محاولات وحد retry delay، وعدم تسجيل النجاح قبل commit |
| `tests/test_management.py` | مواءمة pipeline mocks لاختبار السلم القديم مع transaction contract الجديد |
| `tests/test_round16_full_review.py` | إضافة اختبار Redis حقيقي لتحذيرين متزامنين، واختبار WatchError retry، واختبار Redis failure safety |
| `tasks/round17-plan.md` | حفظ قرار التصميم ومعايير القبول |

## سلوك النجاح والفشل

في النجاح، يُعاد `WarnStatus` من history التي تم commit لها فعلياً، وليس من قراءة سابقة قديمة. في تعارض optimistic locking، تُهمل المحاولة المتعارضة ويعاد بناء الحالة من قراءة جديدة. في فشل الاتصال أو استنفاد retries، لا يصل التنفيذ إلى logger الخاص بـ`warn_added` ولا يرسل نتيجة نجاح من هذه الدالة.

الـtransaction تكتب `SET` و`EXPIRE` معاً داخل EXEC. كما بقي الاحتفاظ بآخر 50 سجلّاً، واحتساب decay، وcontract التصعيد، و`warn_limit` canonical دون تغيير.

## الاختبارات والنتائج

| الفحص | النتيجة |
|---|---|
| حالة Round 16 قبل التعديل | **254 passed** |
| focused suite: `test_round16_full_review.py` و`test_management.py` | **42 passed** |
| اختبار concurrency Redis حقيقي | نجح وحافظ على سجلين مختلفين |
| اختبار WatchError retry | نجح وأثبت محاولتين |
| اختبار Redis connection failure | نجح؛ رُفع الخطأ ولم تُعلن نتيجة نجاح |
| `python -m pytest tests/ -q -W error` | **257 passed** |
| `python -m compileall -q -f .` | ناجح |
| `pip check` | `No broken requirements found` |
| `pip-audit -r requirements.txt` | `No known vulnerabilities found` |
| Ruff `E9,F401,RUF012` على الملفات المعدلة | `All checks passed` |

## ما لم يُنفذ

لم تُنفذ اختبارات Telegram الحية أو PostgreSQL production أو Celery worker أو providers الخارجية. كما لم تُعالج في هذه الجولة race منفصلة في `raid_detector.check_raid`، حيث ما زال ذلك يحتاج reservation ذرية مرتبطة بنتيجة Telegram mutation وrollback واضح. لا يدعي هذا الإصلاح منع كل أخطاء التزامن في النظام؛ نطاقه هو history key للتحذيرات داخل Redis.

## المراجع

[1]: https://redis.io/docs/latest/develop/using-commands/transactions/ "Redis Transactions and WATCH"
[2]: https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html "redis-py Asyncio Examples"


## الأرشيف

تم تنظيف `.git` وcache و`.pyc` و`.pyo` و`.db` و`.coverage` وبناء `Guardian-bot-round17-warn-atomicity.zip`. يحتوي الأرشيف على **281 ملفاً**، واجتاز `unzip -tq` وفحص المدخلات الممنوعة. SHA-256:

```text
49cb085dcf20868afdad97b5cbee162b26ea31cf2fe6600b07db35574a2b8b33
```
