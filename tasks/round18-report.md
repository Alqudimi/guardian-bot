# تقرير الجولة الثامنة عشرة — atomic raid reservation

**المشروع:** Guardian Bot — TelegramBot  
**النطاق:** `src/pipeline/raid_detector.py` ومسار concurrent join lockdown  
**الحالة:** مكتملة داخل البيئة المعزولة، مع حدود Telegram وstaging موثقة  
**الكاتب:** Manus AI

## الملخص التنفيذي

تابعت الجولة الثامنة عشرة أولوية race التي بقيت من المراجعات السابقة. كان `check_raid` يفحص `lockdown:{chat_id}` ثم ينفذ `_activate_lockdown` ثم يكتب marker. عند وصول تحديثي انضمام متزامنين، كان كلاهما يستطيع رؤية عدم وجود marker وتنفيذ Telegram mutations نفسها قبل أن يكتب أي منهما marker.

تمت إضافة reservation ذرية باسم `raid_activation:{chat_id}` عبر `SET NX EX`. فحص `exists` السابق بقي fast path فقط، بينما NX هو الضمان الذري الذي يسمح بمسار activation واحد. لا يثبت النظام `lockdown:{chat_id}` إلا بعد أن تعيد `_activate_lockdown` نجاحاً فعلياً. عند فشل Telegram تُحذف reservation ولا يعلن المسار نجاحاً. عند فشل transaction التي تثبت state بعد نجاح Telegram، لا تُعاد نتيجة نجاح ولا تُحذف reservation، فتظل TTL حاجزاً مؤقتاً يمنع duplicate mutation أثناء degradation.

> ارتفعت suite من **257 اختباراً ناجحاً** في الجولة السابقة إلى **260 اختباراً ناجحاً**، مع اختبارات concurrent joins وفشل Telegram وفشل Redis state commit، إضافة إلى compileall و`pip check` و`pip-audit` وRuff المحدد.

## التغيير المنفذ

| العنصر | قبل | بعد |
|---|---|---|
| منع duplicate activation | `exists` ثم Telegram mutation | `SET NX EX` reservation ذرية |
| active marker | بعد استدعاء لا يعيد contract نجاح صريحاً | بعد `activated is True` فقط |
| Telegram failure | لم يكن هناك contract واضح للنجاح | `_activate_lockdown` تعيد false عند TelegramError |
| Redis state failure | قد يترك المسار marker غير متسق أو يعلن success | النتيجة false، وتبقى reservation حتى TTL |
| concurrent joins | كل مسار قد ينفذ mutation | activation واحدة فقط في الاختبار الحقيقي |
| release | `release_lockdown` ما زال يحذف active marker ويعيد صلاحيات Telegram | لم يتغير contract release في هذه الجولة |

تم تغيير annotation لـ`_activate_lockdown` إلى `bool`، وأصبحت تعيد `False` عند TelegramError و`True` بعد اكتمال المسار الأساسي. فشل إرسال إشعار إداري ثانوي لا يلغي lockdown الأساسي لأن هذه الإشعارات best-effort كما كان المسار السابق، بينما فشل slow mode أو set permissions يمنع نجاح activation.

## الاختبارات والنتائج

| الفحص | النتيجة |
|---|---|
| focused raid suites | **24 passed** |
| concurrent joins على Redis حقيقي | **نجح**؛ خمس join updates أنتجت activation واحدة |
| Telegram failure | **نجح**؛ reservation حُذفت ولم يُثبت active marker |
| Redis state commit failure | **نجح**؛ النتيجة false ولم يُعلن lockdown success |
| `python -m pytest tests/ -q -W error` | **260 passed** |
| `python -m compileall -q -f .` | ناجح |
| `pip check` | `No broken requirements found` |
| `pip-audit -r requirements.txt` | `No known vulnerabilities found` |
| Ruff `E9,F401,RUF012` على الملفات المعدلة | `All checks passed` |

## حدود التنفيذ

لا تُثبت هذه الجولة نجاح Telegram API الحي أو صلاحيات البوت أو وصول `chat_member` updates، لأن البيئة لا تحتوي token حقيقياً أو staging group. كما أن Telegram mutations المتعددة داخل `_activate_lockdown` ليست transaction قابلة للrollback تلقائياً؛ إذا نجحت خطوة وفشلت خطوة لاحقة، لا يستطيع Redis وحده إعادة Telegram إلى الحالة السابقة. لذلك بقيت compensation/rollback الجزئية بنداً منفصلاً، ولم يُقدّم التقرير حماية مطلقة من raid أو lockdown.

## الملفات

التغيير الأساسي في `src/pipeline/raid_detector.py`. تمت إضافة `tests/test_round18_raid.py`، وتحديث `tests/test_round15_groups.py` لعقد reservation الجديد. توثق `tasks/round18-plan.md` القرار ومعايير القبول، بينما يسجل `tasks/round18-final-validation.txt` الأوامر والنتائج النهائية.

## المراجع

تعتمد دلالة `SET NX EX` وtransaction state على Redis semantics المستخدمة في المشروع، بينما تبقى حدود mutation والصلاحيات خاضعة لـTelegram Bot API [1].

[1]: https://core.telegram.org/bots/api "Telegram Bot API"


## الأرشيف

تم تنظيف cache و`.pyc` و`.pyo` و`.db` و`.coverage` وبناء `Guardian-bot-round18-raid-reservation.zip`. يحتوي الأرشيف على **287 ملفاً**، واجتاز `unzip -tq` وفحص المدخلات الممنوعة. SHA-256:

```text
652fad4ea767cdc85a1b01d1133dec4624688fe5cec8915cb29af9e8023446fb
```


## مرجع حدود compensation

يوضح قسم `setChatPermissions` في Telegram Bot API أن العملية تضبط default chat permissions لجميع الأعضاء، وتتطلب أن يكون البوت administrator في المجموعة أو supergroup [1]. التوثيق لا يقدم snapshot أو transaction rollback للصلاحيات السابقة؛ لذلك يقتصر التعويض الآمن على إعادة القيم القياسية التي يحددها البوت، وليس استعادة تخصيصات تاريخية غير معروفة.
