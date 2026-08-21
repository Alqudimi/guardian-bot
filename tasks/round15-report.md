# تقرير الجولة الخامسة عشرة — ربط حماية Raid بإعدادات المجموعة

**المشروع:** Guardian Bot — TelegramBot  
**النطاق:** منظومة المجموعات، كشف join-flood، إعدادات المجموعة، وصلاحيات أوامر الإدارة  
**الحالة:** مكتملة داخل البيئة المعزولة مع حدود Telegram الخارجية موثقة  
**الكاتب:** Manus AI

## الملخص التنفيذي

بدأت الجولة من الأرشيف المعتمد لـRound 14. بعد تجهيز Redis محلياً ودعم SQLite async اللازم لاختبارات المشروع، نجح baseline غير المعدل في **245 اختباراً**. ركز الفحص على فجوة واحدة قابلة للإثبات: كان `anti_raid` معرفاً في `src/management/group_settings.py` ومعروضاً في `/settings`، لكن `src/pipeline/raid_detector.py::check_raid` لم يقرأه، ولذلك لم يكن للمشرف تحكم per-group فعلي في مسار join-flood.

تم إصلاح الفجوة بأصغر تغيير موصول بالمعمارية الحالية. يقرأ detector إعداد `anti_raid` canonical قبل الوصول إلى عداد Redis. عند `on` يستمر المسار إلى العتبة والنافذة global الموجودتين، وعند `off` يتوقف المسار دون لمس Redis أو Telegram. أضيف `/setraid on|off` إلى command router الحالي، وهو محمي بـ`_admin_only` الذي يفرض group/supergroup والتحقق من رتبة Telegram الفعلية. لم يُنشأ مخزن إعدادات موازٍ ولم تتغير آلية lockdown القائمة.

> النتيجة الفعلية: ارتفعت suite من **245 اختباراً ناجحاً** في baseline إلى **249 اختباراً ناجحاً** بعد التعديل، مع نجاح compileall و`pip check` و`pip-audit` وفحص Ruff المحدد.

## الفجوة المثبتة والمسار الفعلي

المسار الحقيقي هو `ChatMemberHandler.CHAT_MEMBER` ثم `handle_member_update` في `src/handlers/message_handler.py`، وبعد ذلك `check_raid` في `src/pipeline/raid_detector.py`. كان `group_settings.py` يعلن `anti_raid` بقيمتي `on/off` ويعرضها `/settings`، بينما كان detector يبدأ مباشرة في تحديث sorted set الخاص بالانضمامات ثم يقارن `raid_join_threshold` العام. بذلك كانت قيمة الإعداد مرئية لكنها غير مؤثرة في القرار.

يوضح توثيق python-telegram-bot أن `ChatMemberHandler.CHAT_MEMBER` يتعامل مع `Update.chat_member`، وهو مختلف عن `MY_CHAT_MEMBER` [2]. كما يوضح Bot API أن استقبال هذه التحديثات وتنفيذ تغييرات صلاحيات المجموعة مرتبطان بتكوين التحديثات وصلاحيات البوت administrator الفعلية [1]. لذلك اقتصر التغيير على wiring المحلي، ولم يُقدَّم كضمان لوصول كل join update أو لمنع raid بشكل مطلق.

## التغييرات المنفذة

| الملف | التغيير الفعلي |
|---|---|
| `src/pipeline/raid_detector.py` | قراءة `anti_raid` من `group_settings` قبل join counter؛ `off` يعيد نتيجة غير تنفيذية، وفشل القراءة يسجل degradation داخلياً ويتوقف بأمان |
| `src/handlers/admin_commands.py` | إضافة `cmd_setraid`، والتحقق من `on/off`، وتوثيق الأمر ضمن قائمة الإدارة |
| `src/handlers/message_handler.py` | تسجيل `/setraid` ضمن command router الموجود وإصلاح استيراد `cmd_setleave` الذي كشفه full-suite registration test |
| `tests/test_round15_groups.py` | اختبارات التفعيل، التعطيل، فشل قراءة الإعداد، والتحقق من الأمر والحفظ |
| `README.md` و`AGENT.md` | توثيق العقد الجديد وحدود Telegram وعدم الادعاء بالحماية المطلقة |
| `tasks/round15-recon.md` و`tasks/round15-plan.md` و`tasks/todo.md` | حفظ الأدلة والخطة وقائمة الإنجاز |

## سلوك الفشل والسلامة

عند `anti_raid=off` لا يُستدعى Redis ولا `_activate_lockdown`، فلا يحدث تغيير في المجموعة. وعند تعطل قراءة settings، لا يفرض البوت lockdown اعتماداً على قيمة غير مؤكدة؛ يسجل اسم نوع الاستثناء فقط ويعيد `False`. هذا لا يعني أن النظام يتجاهل join telemetry الأخرى التي ينفذها `handle_new_member` قبل استدعاء detector؛ التغيير يخص قرار تفعيل raid lockdown فقط.

يظل تفعيل lockdown مشروطاً بنجاح Telegram API وصلاحيات البوت. لا يعلن هذا المسار نجاحاً للمستخدم النهائي؛ بل يحتفظ بالآلية الحالية التي تسجل فشل Telegram داخلياً. كما تبقى العتبة والنافذة global settings، لأن الجولة لم تضف thresholds جديدة أو مخزناً ثالثاً.

## الاختبارات والتحقق

| الفحص | النتيجة |
|---|---|
| `python -m compileall -q -f .` | ناجح |
| الاختبارات المركزة للـanti-raid وgroup operations | **24 passed** |
| `python -m pytest tests/test_hardening_regressions.py -q -W error` | **26 passed** |
| `python -m pytest tests/ -q -W error` | **249 passed** |
| `pip check` | `No broken requirements found` |
| `pip-audit -r requirements.txt` | `No known vulnerabilities found` |
| Ruff: `E9,F401,RUF012` على الملفات المعدلة | `All checks passed` |

واجه أول full-suite بعد التعديل فشلاً في استيراد `cmd_setleave` داخل قائمة التسجيل، وكشفه اختبار بناء التطبيق. أُصلح الاستيراد ثم أعيد تشغيل suite كاملة ونجحت بـ249 اختباراً. لم تُعدّل اختبارات قائمة لتخفي الفشل، ولم تُنفذ عمليات Telegram مدمرة.

## ما لم يُنفذ وسبب ذلك

لم تُنفذ تجربة حية على Telegram أو staging group، لعدم توفر token حقيقي ومجموعة وصلاحيات administrator وبيئة استقبال فعلية لـ`chat_member`. ولم تُختبر PostgreSQL أو Celery أو voice providers في هذه الجولة لأنها خارج نطاق الفجوة المختارة. اختبارات Redis المحلية حقيقية حيث يستخدمها المسار، لكن ذلك لا يثبت rate limits أو latency أو سلوك 429 في Telegram production.

لا يدعي هذا التغيير منع raid أو spam أو حظر المجموعة بشكل مضمون. Telegram Bot API، صلاحيات البوت، نوع المجموعة، وصول التحديثات، وrate limits تظل حدوداً تشغيلية حقيقية [1] [2].

## الملفات والآثار المسلّمة

يشمل التسليم `tasks/round15-plan.md` و`tasks/round15-recon.md` و`tasks/round15-report.md` وسجل التحقق النهائي، إضافة إلى أرشيف المصدر المنظف من `.git` وcache و`.pyc` و`.db`. سيُحفظ SHA-256 للأرشيف بعد بنائه للتحقق من سلامة التسليم.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.chatmemberhandler.html "ChatMemberHandler — python-telegram-bot v22.5"


## Archive verification

تم بناء `Guardian-bot-round15-groups-pass.zip` بعد حذف `.git` وcache و`.pyc` و`.pyo` و`.db` و`.coverage`. يحتوي الأرشيف على **268 ملفاً**، واجتاز `unzip -tq` دون أخطاء، ولم يحتوِ على أي مدخل ممنوع. قيمة SHA-256 هي:

```text
18a0b6acd7774695d9c3f52318f6eeda2507364b848e01c542992aaf8966bb52
```
