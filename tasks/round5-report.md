# تقرير الجولة الخامسة: توحيد توجيه الأوامر وتقوية الاتساق

## الملخص التنفيذي

تمت متابعة المشروع من حالته الفعلية، وليس من افتراضات نظرية. أظهر الفحص أن suite الحالية تمر، لكن تجميع handlers يحتوي تعارضاً وظيفياً حقيقياً: `voice_chat` كان يسجل `/play` للموسيقى، بينما `message_handler` يسجله للألعاب. هذا يجعل نتيجة الأمر تعتمد على ترتيب handlers، وقد يؤدي إلى حجب أحد الاستخدامين. كما أظهر الفحص أن وثيقة الألعاب لا تزال تصف Mini Apps وألعاباً محذوفة، وأن `requirements.txt` يحتوي إعلانين متعارضين جزئياً لـ`python-telegram-bot`.

تم إصلاح هذه النقاط دون إعادة بناء المشروع أو إضافة dependency جديدة. أصبح `message_handler` dispatcher الوحيد لـ`/play`: يبدأ Mafia أو Chameleon عندما يكون الوسيط الوحيد اسماً مسجلاً، ويفوض بقية الاستعلامات إلى music handler. أضيف `/music` كمدخل صريح للموسيقى، وأزيل التسجيل المكرر من voice_chat. كما تمت مزامنة وثيقة الألعاب وإزالة dependency declaration المكرر.

> لا تعني نتيجة الاختبارات المحلية أن Bot API حي أو مجموعة Telegram حقيقية قد اختُبرت؛ هذا القيد موثق صراحة في التقرير وفي وثائق المشروع.

## الفحص الذي سبق التنفيذ

تم جرد نقطة التشغيل `main.py`، وتجميع handlers في `src/handlers/message_handler.py`، وسجل الميزات في `src/features/register.py`، ومشغل الصوت في `src/features/voice_chat.py`، وregistry الألعاب والجلسات، وملفات dependency، والاختبارات، ووثائق الألعاب. كان خط الأساس قبل التعديل: `compileall` ناجح، و166 اختباراً ناجحاً مع `pytest -W error`، و`pip check` ناجح، و`pip-audit -r requirements.txt` لم يجد ثغرات معروفة في نتيجة الفحص الحالية.

أظهرت مراجعة توثيق [python-telegram-bot] الرسمية أن handlers تنظم في مجموعات، وأن اختيار handler داخل المجموعة يعتمد على أول handler مطابق، بينما يمكن تقييم handler واحد من كل مجموعة [1]. لذلك فإن تسجيل `/play` مرتين ليس آلية دمج آمنة لمساري الألعاب والموسيقى.

## المشكلات المثبتة

| الأولوية | المشكلة | الأثر قبل الإصلاح | الدليل |
|---|---|---|---|
| عالية | تسجيل `/play` في `voice_chat` و`message_handler` | تضارب ownership واحتمال حجب مسار الألعاب أو الموسيقى | `src/features/voice_chat.py` و`src/handlers/message_handler.py` |
| متوسطة | بحث موسيقي يبدأ باسم لعبة، مثل `/play mafia song` | يمكن أن يُفسر خطأً كبدء لعبة إذا فُحص أول وسيط فقط | منطق dispatcher السابق |
| متوسطة | `Game_System_Documentation.md` يصف Mini Apps وألعاباً محذوفة | توثيق لا يعكس الحالة الفعلية | الأقسام القديمة 5 و6 و8 |
| متوسطة | إعلانان لـ`python-telegram-bot` في `requirements.txt` | غموض في قيد الإصدار أثناء التثبيت من requirements | السطران السابقان 1 و11 |
| منخفضة/خارج النطاق | 623 مخالفة في `ruff check .` عند خط الأساس | لا يمكن وصف المشروع بأنه lint-clean | سجل baseline |

## التعديلات المنفذة

### توحيد ownership لـ`/play`

أصبح `cmd_play` في `src/handlers/message_handler.py` نقطة الدخول الوحيدة للأمر. إذا كانت الوسائط تساوي وسيطاً واحداً هو `mafia` أو `chameleon`، يبدأ dispatcher اللعبة عبر `_start_game`. خلاف ذلك، يفوض الطلب إلى `src.features.voice_chat.cmd_play`.

هذا الشرط يمنع الحالة الحدية `/play mafia song` من بدء Mafia؛ فهي تمرر إلى بحث الموسيقى. كما أن `/play` بلا وسائط يعرض شرحاً موحداً للمسارين بدلاً من اختيار handler عشوائي.

### مدخل موسيقى صريح

أزيل `CommandHandler("play", cmd_play)` من `voice_chat.register_handlers`، وأضيف `CommandHandler("music", cmd_play)`. بقيت صيغة `/play <url أو بحث>` متوافقة عبر dispatcher المركزي، وأصبح `/music <url أو بحث>` مدخلاً مباشراً واضحاً للموسيقى. لم تتم إضافة dependency أو backend جديد.

### مزامنة التوثيق والاعتماديات

أعيدت كتابة `Game_System_Documentation.md` ليصف Mafia وChameleon فقط، وGameSessionManager، وRedis persistence، وصيغة callbacks، والأوامر الحالية. أزيل الإعلان المكرر لـ`python-telegram-bot` من `requirements.txt`، وأضيفت قواعد ownership الجديدة إلى `AGENT.md`، كما حدث `README.md`.

## الاختبارات المضافة

أضيفت إلى `tests/test_hardening_regressions.py` اختبارات تتحقق من وجود تسجيل واحد فقط لـ`/play`، ووجود تسجيل واحد لـ`/music`، وأن callback الخاص بـ`/play` يملكه `message_handler` بينما callback الخاص بـ`/music` يملكه `voice_chat`. كما تختبر أن `/play mafia` يوجه إلى اللعبة، وأن `/play lofi mix` و`/play mafia song` يفوضان إلى الموسيقى.

هذه الاختبارات لا تستبدل اختبار Telegram حي؛ إنها تتحقق من wiring الفعلي داخل كائن Application ومن dispatching الفعلي للدوال، مع عزل الاستدعاءات الخارجية غير المناسبة لاختبار محلي.

## نتائج التحقق

| الفحص | النتيجة |
|---|---:|
| `python -m compileall -q -f .` | ناجح |
| `python -m pytest tests/ -q -W error` | **168 ناجحاً** |
| `pip check` | لا توجد متطلبات مكسورة |
| `pip-audit -r requirements.txt` | لا توجد ثغرات معروفة في نتيجة الفحص الحالية |
| ownership scan لـ`CommandHandler("play")` | تسجيل واحد |
| ownership scan لـ`CommandHandler("music")` | تسجيل واحد |
| duplicate dependency check | إعلان واحد لـ`python-telegram-bot` |
| stale deleted-game scan في Game_System_Documentation | لا توجد أسماء الألعاب المحذوفة |
| Ruff لملف الاختبار المعدل | ناجح |

## القيود والمشكلات المتبقية

فحص `ruff check .` العام ما زال يفشل بمخالفات تاريخية موزعة على أجزاء كثيرة من المشروع، وقد تم تجنب إصلاحها عشوائياً لأن ذلك خارج نطاق تعارض الأوامر وقد يغير ملفات غير مرتبطة. ملف الاختبار المعدل يمر Ruff، بينما يحتوي `voice_chat.py` و`message_handler.py` مخالفات سابقة متعددة لا تتعلق كلها بالتعديل الحالي.

لم يُنفذ Bot API حي، ولم تُختبر جلسة صوت حقيقية عبر PyTgCalls، لعدم توفر token حقيقي ومجموعة Telegram وبيئة voice backend مناسبة. تم اختبار wiring والـ dispatching محلياً، وتم تشغيل suite كاملة مع Redis المحلي حيث تتطلب الاختبارات ذلك.

## الملفات المعدلة أو المنشأة

| الملف | التغيير |
|---|---|
| `src/handlers/message_handler.py` | dispatcher مركزي لـ`/play` وتفويض الموسيقى |
| `src/features/voice_chat.py` | إزالة تسجيل `/play` وإضافة `/music` وتحديث الاستخدام |
| `tests/test_hardening_regressions.py` | اختبارات ownership وdispatching والحالة الحدية |
| `requirements.txt` | إزالة إعلان PTB المكرر |
| `Game_System_Documentation.md` | مزامنة كاملة مع نظام الألعاب الحالي |
| `README.md` | توثيق الجولة والأوامر الجديدة |
| `AGENT.md` | قاعدة ownership للأوامر |
| `tasks/round5-analysis.md` | الأدلة والتحليل وقرار التصميم |
| `tasks/round5-ptb-routing-research.md` | نتائج البحث الرسمي |
| `tasks/round5-final-validation.txt` | سجل التحقق النهائي |

## المراجع

[1]: https://docs.python-telegram-bot.org/en/v22.2/telegram.ext.application.html "python-telegram-bot Application v22.2"

[2]: https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.commandhandler.html "python-telegram-bot CommandHandler v22.5"
