# تقرير الجولة التاسعة عشرة — تعويض فشل raid الجزئي

**المشروع:** Guardian Bot — TelegramBot  
**النطاق:** `_activate_lockdown`، تعويض Telegram mutations الجزئية، واستقرار reservation  
**الحالة:** مكتملة داخل البيئة المعزولة، مع حدود Telegram الحية موثقة  
**الكاتب:** Manus AI

## الملخص التنفيذي

تابعت الجولة التاسعة عشرة بند compensation الذي بقي بعد تقوية reservation في Round 18. كان `_activate_lockdown` ينفذ slow mode ثم default permissions ثم إشعار المجموعة. إذا فشلت خطوة لاحقة، كان يعيد `False` لكن يترك أي mutation سابقة دون محاولة استعادة، بينما لا يوفر Telegram Bot API transaction rollback تلقائياً.

تمت إضافة تتبع صريح لنجاح كل mutation أساسية. إذا فشل إشعار المجموعة بعد نجاح slow mode وpermissions، ينفذ البوت تعويضاً best-effort يعيد default permissions ثم يعطل slow mode. وإذا فشلت permissions بعد نجاح slow mode، يعطل slow mode فقط. فشل التعويض يسجل داخلياً ولا يحول العملية إلى نجاح، كما لا يُثبت `lockdown` marker لأن مسار `check_raid` لا يثبت marker إلا بعد `True` من `_activate_lockdown`.

> ارتفعت suite من **260 اختباراً ناجحاً** في الجولة السابقة إلى **262 اختباراً ناجحاً**، مع اختبارين جديدين لفشل إشعار المجموعة وفشل permissions، ونجاح جميع quality gates.

## التغيير

| المرحلة | السلوك بعد التعديل |
|---|---|
| slow mode | تُسجل كـapplied بعد نجاح `set_chat_slow_mode_delay(30)` |
| permissions | تُسجل كـapplied بعد نجاح `set_chat_permissions` الخاص بالـlockdown |
| فشل لاحق بعد الاثنين | تعويض permissions إلى baseline ثم slow mode إلى 0 |
| فشل permissions | تعويض slow mode إلى 0 فقط |
| فشل compensation | log داخلي باسم الخطوة، دون نجاح زائف أو exception مستخدم |
| marker | لا يُكتب إلا إذا أعاد `_activate_lockdown` true |

الدالة `_standard_group_permissions` تمثل baseline الذي يحدده البوت نفسه. هذا مقصود ولا يدعي استعادة إعدادات تاريخية مخصصة للمجموعة. Telegram يعرّف `setChatPermissions` كعملية لتعيين default permissions لجميع الأعضاء، ويتطلب أن يكون البوت administrator؛ التوثيق لا يقدم snapshot أو rollback تلقائياً للصلاحيات السابقة [1].

## الاختبارات والنتائج

| الفحص | النتيجة |
|---|---|
| focused raid suites | **20 passed** |
| فشل إشعار المجموعة بعد نجاح mutations | نجح؛ permissions وslow mode عادا إلى baseline |
| فشل permissions بعد slow mode | نجح؛ slow mode عُطل ولم يُرسل إشعاراً |
| suite كاملة `-W error` | **262 passed** |
| compileall | ناجح |
| `pip check` | `No broken requirements found` |
| `pip-audit -r requirements.txt` | `No known vulnerabilities found` |
| Ruff `E9,F401,RUF012` على الملفات المعدلة | `All checks passed` |

## الحدود

لم تُنفذ Telegram API حية أو staging group، لذلك لا يثبت الاختبار صلاحيات bot administrator أو السلوك الفعلي في مجموعة production. التعويض best-effort؛ إذا فشل Telegram في التعويض نفسه، تُسجل التفاصيل الداخلية وتبقى الحالة الخارجية بحاجة إلى تدخل أو retry تشغيلي. كما أن إشعارات admins الثانوية تبقى best-effort ولا تلغي primary lockdown إذا نجحت slow mode وpermissions وإشعار المجموعة.

## المراجع

[1]: https://core.telegram.org/bots/api#setchatpermissions "Telegram Bot API — setChatPermissions"


## الأرشيف

تم تنظيف cache و`.pyc` و`.pyo` و`.db` و`.coverage` وبناء `Guardian-bot-round19-raid-compensation.zip`. يحتوي الأرشيف على **292 ملفاً**، واجتاز `unzip -tq` وفحص المدخلات الممنوعة. SHA-256:

```text
77f7fe1b604897e276722bd8d0db1a8bb029bd980885f1098a00311692f16ed5
```


## مرجع مزامنة DB

يوضح توثيق SQLAlchemy أن AsyncSession يوفر وظائف ORM كاملة، وأن transaction commit/rollback يجب أن تكون ضمن حدود session/context المناسبة [2]. يتوافق ذلك مع `db_session` الحالي الذي يلتزم عند الخروج ويرجع rollback عند exception. لذلك سيبقى تحديث DB بعد نجاح Telegram الأساسي، ولن يُستخدم DB كدليل نجاح قبل mutation الخارجية.

[2]: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html "SQLAlchemy Asyncio Documentation"
