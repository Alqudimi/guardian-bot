# تقرير الجولة العشرون — اتساق raid state بين Telegram وRedis وPostgreSQL

**المشروع:** Guardian Bot — TelegramBot  
**النطاق:** activation/release state ordering، DB mirror، Redis marker، واختبار shop time-sensitive  
**الحالة:** مكتملة داخل البيئة المعزولة مع الحدود الخارجية موثقة  
**الكاتب:** Manus AI

## الملخص التنفيذي

تابعت الجولة العشرون فحص اتساق الحالة بعد نجاح أو فشل raid lockdown. كان activation يحدّث PostgreSQL داخل `_activate_lockdown` قبل أن يثبت `check_raid` Redis active marker، بينما كان release يحذف Redis marker قبل تنفيذ Telegram release. هذا الترتيب لا يجعل DB أو Redis دليلاً موثوقاً على نجاح العملية الخارجية.

تم نقل DB mirror إلى ما بعد نجاح Telegram وRedis active commit. في release أصبحت slow mode وpermissions هما primary operations أولاً، ثم notification best-effort، ثم DB mirror، ثم حذف Redis marker. إذا فشل primary Telegram release يبقى marker ولا يُعلن cleanup ناجحاً. إذا فشل DB mirror بعد نجاح Telegram، تُحذف Redis marker لأن الحالة الخارجية تحررت فعلياً، مع تسجيل فشل المزامنة داخلياً.

أثناء إعادة suite الكاملة ظهر فشلان سابقان في `test_round10_shop_integrity.py` بسبب قاعدة تسعير ليلية تعتمد على وقت UTC الحالي؛ كانت الاختبارات تتوقع وقت النهار لكنها لم تثبته. عُزل ذلك في fixture اختبار فقط عبر وقت نهاري ثابت، دون تعديل production pricing. بعد الإصلاح نجحت **266 اختباراً**.

> لا توجد transaction مشتركة يمكنها جعل Telegram وRedis وPostgreSQL atomic عبر الشبكات. التحسين يضمن ترتيباً محافظاً وعدم إعلان نجاح زائف، ولا يدعي اتساقاً مطلقاً عند انقطاع متعدد الأنظمة.

## التغييرات الأساسية

| المسار | التغيير |
|---|---|
| activation | `_activate_lockdown` ينفذ Telegram فقط؛ `check_raid` يثبت Redis marker ثم يستدعي `_persist_raid_db_state(active=True)` |
| DB activation failure | mirror failure يسجل داخلياً ولا يغيّر حقيقة أن Telegram وRedis نجحا |
| release success | Telegram primary أولاً، notification best-effort، DB mirror، ثم Redis delete |
| release Telegram failure | لا DB mirror ولا Redis delete؛ marker يبقى لمنع state drift والتفعيل المتكرر |
| release partial failure | إذا نجحت إزالة slow mode وفشلت permissions، يعاد slow mode إلى 30 قدر الإمكان |
| release DB failure | Redis marker يُحذف بعد نجاح Telegram؛ DB stale state مسجل كفشل mirror لا كنجاح |
| shop test | fixture يثبت 12:00 UTC في `service_engine.datetime` داخل الاختبار فقط، لعزل overnight 5% discount المتوقع |

## الاتساق وقواعد النجاح

مصدر الحقيقة للعملية الخارجية هو Telegram mutation الناجحة. Redis marker يمثل state تشغيلية مؤقتة بعد نجاح primary activation، وPostgreSQL mirror تحليلي/تشغيلي ثانوي. لا تُستخدم نتيجة DB لإعلان Telegram success، ولا يُحذف marker عند فشل Telegram release. هذا الترتيب يقلل احتمال أن يرى join لاحق state غير مؤكدة.

`db_session` الحالي يلتزم عند الخروج ويرجع rollback عند exception، ولذلك يُستدعى mirror داخل helper مستقل بعد primary operations. توثيق SQLAlchemy يوضح استخدام AsyncSession والحدود المناسبة للـcommit/rollback [1].

## الاختبارات والنتائج

| الفحص | النتيجة |
|---|---|
| focused state/raid suites | **19 passed** |
| release Telegram failure | marker بقي وDB mirror لم يُستدعَ |
| release permission failure | slow mode عُوض إلى 30 وبقي marker |
| release DB mirror failure | Telegram نجح وRedis marker حُذف |
| shop integrity بعد تثبيت الوقت | **5 passed** |
| suite كاملة `python -m pytest tests/ -q -W error` | **266 passed** |
| `python -m compileall -q -f .` | ناجح |
| `pip check` | `No broken requirements found` |
| `pip-audit -r requirements.txt` | `No known vulnerabilities found` |
| Ruff `E9,F401,RUF012` على الملفات المعدلة | `All checks passed` |

## الحدود الخارجية

لم تُنفذ Telegram API حية أو staging group أو PostgreSQL production. فشل DB mirror بعد نجاح Telegram لا يمكن إصلاحه atomically من داخل Telegram؛ يحتاج retry/background reconciliation مستقل إذا كان مطلوباً. كما لا يضمن release استعادة تخصيصات permissions التاريخية، بل يعيد baseline الذي يحدده البوت. لم يتغير production pricing؛ تثبيت وقت النهار كان محصوراً في shop integrity tests.

## المراجع

[1]: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html "SQLAlchemy Asyncio Documentation"
[2]: https://core.telegram.org/bots/api#setchatpermissions "Telegram Bot API — setChatPermissions"


## الأرشيف

تم تنظيف cache و`.pyc` و`.pyo` و`.db` و`.coverage` وبناء `Guardian-bot-round20-state-consistency.zip`. يحتوي الأرشيف على **298 ملفاً**، واجتاز `unzip -tq` وفحص المدخلات الممنوعة. SHA-256:

```text
8fff2ec8a39276ffdfb3b51547f0df42b900c9679cb635437d18fd73d4f54958
```
