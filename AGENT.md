# Guardian Bot — Project Instructions

## Overview

Guardian Bot هو بوت Python غير متزامن لحماية مجموعات Telegram عبر سلسلة دفاع متعددة الطبقات تشمل التطبيع، القواعد السريعة، كشف flood والسلوك، تحليل الروابط والوسائط، الذكاء الاصطناعي الاختياري، تقدير المخاطر، القرار، التنفيذ، والتدقيق.

## Stack

يستخدم المشروع Python 3.11+ و`python-telegram-bot` v22 وRedis وPostgreSQL عبر SQLAlchemy async وAlembic وCelery وstructlog. نماذج Transformers اختيارية وثقيلة وتُحمّل عند الحاجة فقط.

## Run and Verify

```bash
cp .env.example .env
# املأ TELEGRAM_BOT_TOKEN وبيانات Redis/PostgreSQL الحقيقية
python -m compileall -q -f .
python -m pytest tests/ -q
python -m pytest tests/ --cov=src --cov=config --cov-report=term-missing
pip check
pip-audit -r requirements.txt
ruff check .
# In a disposable database, validate the migration chain:
# alembic upgrade head && alembic check && alembic downgrade base
python main.py
```

استخدم `ENVIRONMENT=development` و`DRY_RUN=true` أثناء التجربة. في development يسمح `AUTO_CREATE_TABLES=true` بالتهيئة المريحة، أما production وstaging فيفرضان `AUTO_CREATE_TABLES=false` وتشغيل `alembic upgrade head` قبل بدء البوت. يجب أن يكون token صالحاً، وأن يكون Redis وPostgreSQL متاحين. عند تفعيل webhook يجب استخدام HTTPS وسر لا يقل عن 16 محرفاً URL-safe.

## Architecture Entry Points

نقطة التشغيل هي `main.py`. تسجيل handlers يتم في `src/handlers/message_handler.py`، والمنسق الرئيسي في `src/pipeline/orchestrator.py`. طبقات الإشراف موجودة في `src/layers/`، النماذج والجلسات في `src/db/`، الميزات الاختيارية في `src/features/`، والألعاب في `src/games/`، والمتجر في `src/shop/`.

## Security Rules

لا تُستخدم قيمة token افتراضية قابلة للتشغيل في production. لا يُسمح لأمر إداري حساس بالاعتماد على Telegram user ID وحده؛ يجب أن ينجح أيضاً تحقق `get_chat_member` من رتبة `administrator` أو `creator` داخل المجموعة. لا تضع token في URL أو السجلات أو رسائل الإدارة. كل حد للمعدل أو dedup يعتمد على Redis يجب أن يكون ذرّيًا قدر الإمكان، وأي إجراء Telegram أمني لا يجوز إسقاطه عشوائياً لأغراض محاكاة سلوك بشري.

## Testing Policy

اختبارات الوحدات لا تُنزل نماذج AI ولا تستدعي Telegram Bot API المدمرة. اختبارات Redis التكاملية يجب أن تستخدم Redis محلياً حقيقياً عندما تكون متاحة. أي اختبار حي للحظر أو الحذف يحتاج مجموعة Telegram مخصصة وtoken يقدمه المشغل صراحة، ويجب تشغيله أولاً مع `DRY_RUN=true`.

## Change Guidelines

حافظ على المنسق متعدد الطبقات، وفضّل إصلاح الحدود الواضحة على إعادة كتابة المعمارية. لا تضف اعتماديات ثقيلة قبل التحقق من الحاجة. عند إضافة handler جديد، اختبر المجموعة والترتيب والـ callback pattern. عند تعديل قرار أمني، أضف اختباراً يثبت السلوك الإيجابي والسلبي وحالة الفشل.

## Guardian-owned games

الألعاب المسجلة حالياً هي **Mafia** و**Chameleon** فقط. يجب أن يكون منطق أي لعبة جديد داخل المستودع، وأن يستخدم Telegram messages وcallbacks أو آليات البوت الداخلية، وألا يفتح `WebAppInfo` أو رابطاً إلى لعبة خارجية أو يعتمد على بوت آخر. لا تُسجّل لعبة جديدة قبل وجود تدفق فعلي قابل للاختبار، وحالة قابلة للحفظ والاستعادة، ومعالجة واضحة للأخطاء والنهاية.

الأوامر المدعومة هي `/games` و`/play mafia` و`/play chameleon` و`/mafia_start` و`/cham_start` و`/music` و`/stopgame`. يبدأ `/play` من خلال dispatcher واحد: يوجه أسماء الألعاب المسجلة إلى GameSessionManager، ويفوض استعلامات الموسيقى إلى voice_chat. لذلك لا يجوز لأي feature أخرى تسجيل `CommandHandler("play", ...)`؛ يجب استخدام اسم صريح مثل `/music` أو إضافة routing مركزي مبرر. تبدأ Mafia مراحل التسجيل والليل والنهار والتصويت، بينما تبدأ Chameleon اختيار الموضوع وتوزيع الكلمة سراً وإرسال clues والتصويت.

عند تعديل callback يجب التحقق من payload قبل فهرسته، والتحقق من أن اسم اللعبة مسجل فعلاً. Callbacks الخاصة برسائل DM قد تحمل `chat_id` الجلسة في آخر payload، ولذلك يجب الحفاظ على صيغة `game:{game_name}:{action}:{target}:{chat_id}` عند الحاجة. يجب تمرير حالة اللعب عبر `GameSessionManager` وعدم إنشاء تخزين موازٍ داخل اللعبة.

قبل اعتبار تعديل الألعاب مكتملاً، شغّل:

```bash
python -m compileall -q -f .
python -m pytest tests/test_all_games.py tests/test_game_session.py -q -W error
python -m pytest tests/ -q -W error
```

اختبارات الألعاب يجب أن تثبت تدفقاً فعلياً للحالة، لا مجرد استدعاء placeholder. عند تعديل Redis، يجب إضافة أو تحديث اختبار تكاملي باستخدام Redis محلي حقيقي، مع حذف الجلسة في نهاية الاختبار. لا تدّعِ اختبار Bot API حي في البيئة المعزولة عند عدم توفر token ومجموعة Telegram حقيقية.


## الجولة السادسة — قواعد العمليات والـlifecycle

يجب أن يكون لكل backend اختياري lifecycle واضح داخل `main.post_init` و`main.post_shutdown`، وأن يفشل بشكل معزول دون تعطيل حماية المجموعات. لا يجوز اعتبار feature مفعلة لمجرد تسجيل handler؛ يجب التحقق من أن initialization والاستدعاء والتنظيف موصولون فعلياً.

عند تفعيل raid lockdown، يجب أن تتطابق مدة مفتاح Redis مع مهمة JobQueue التي تعيد صلاحيات Telegram. يجب استخدام اسم مهمة ثابت لكل مجموعة وإزالة المهمة السابقة قبل إنشاء مهمة جديدة، مع تسجيل degradation إذا لم يكن JobQueue متاحاً.

تقارير `/report` لا توثق إلا المؤشرات التي تُكتب وتُقرأ فعلياً من Redis أو قاعدة البيانات. أي metric جديد يحتاج writer من مسار الحدث، reader في `generate_report`، formatter، واختبار roundtrip حقيقي، ولا يجوز الإعلان عن delivery مجدول أو risk distribution دون worker/scheduler ومسار بيانات مثبت.

أي تعديل على عملية خلفية يجب أن يوضح هل هي جزء من bot process أم تتطلب Celery worker/beat منفصلين. لا تُرسل مهام إلى broker في مسار hot path دون سياسة retry، وfeature flag أو degradation واضح، واختبار يثبت عدم تأثير فشل broker على قرار الحماية.


## تدقيق الوظائف الحقيقية — المتجر والمدفوعات

لا يجوز أن يزيد رصيد المستخدم من callback زر أو إدخال مبلغ. الإيداع الحقيقي يجب أن يبدأ بـpending transaction، ثم Telegram invoice عند وجود `PAYMENT_PROVIDER_TOKEN`، ثم تحقق pre-checkout، ثم اعتماد واحد فقط بعد `successful_payment` مع مطابقة payload والمستخدم والعملة والمبلغ وcharge ID. إذا لم يوجد provider token، يجب تعطيل الإيداع وإظهار ذلك للمستخدم دون أي تغيير مالي.

لا يجوز أن تنتقل خدمة `instant` إلى `processing` أو `completed` دون executor/provider فعلي يستخدم endpoint موثقاً، timeout وretry وidempotency ونتيجة تسليم مثبتة. إلى أن يُبنى هذا المسار، تُرفض الخدمة الآلية برسالة صريحة، وتبقى الخدمات اليدوية في مسار paid/manual الذي ينفذه المشرف من لوحة الإدارة.

كل رسالة نجاح في المتجر يجب أن تكون مبنية على تغيير حالة أو حدث خارجي تحقق فعلياً، وليس على إنشاء سجل داخلي فقط. يجب أن تغطي اختبارات كل عملية مسارات النجاح والفشل والتكرار وعدم توفر التكامل الخارجي.


## الجولة الثامنة — شمولية الوظائف والعمليات

عند مراجعة قسم موجود، يجب تتبع مساره من handler إلى engine إلى persistence أو provider ثم إلى رسالة النتيجة. وجود callback أو انتقال حالة لا يثبت تنفيذ العملية وحده. يجب أن تكون كل رسالة نجاح مرتبطة بنتيجة فعلية، وأن يُرفض payload غير الصالح قبل الوصول إلى قاعدة البيانات أو محرك العملية.

يعرض `/status` مؤشرات runtime فقط بعد probe فعلي لقاعدة البيانات وRedis، ويميز بين configured وready وunavailable. لا تُسمى credentials الموجودة readiness، ولا تُخفى أعطال optional backend خلف رسائل نجاح. عند إضافة metric تشغيلية، يجب أن يوجد writer من نقطة الحدث، reader في التقرير، formatter، واختبار roundtrip.

يسجل `PipelineContext.layer_failures` أسماء طبقات moderation التي فشلت داخل `_safe`، وتُحفظ في Redis وتظهر في تقارير المجموعة. لا تُستخدم هذه telemetry لتغيير قرار الحماية عشوائياً، لكنها تمنع اختفاء degradation داخل allow fallback وتوفر دليلاً قابلاً للتدقيق.

ميزات المتجر مثل recommendations يجب أن تستخدم engine الموجود فعلياً وأن تعرض حالات عدم وجود بيانات بوضوح. لا تُضاف واجهة لbackend غير موصول، ولا يُكرر محرك قائم لمجرد إضافة زر جديد.


## الجولة التاسعة — التنفيذ والملكية وحالات الفشل

لا يُستهلك أي state أمني قبل نجاح العملية الخارجية الأساسية. في CAPTCHA يجب أن تنجح استعادة صلاحيات Telegram قبل حذف challenge، ويجب استعادة العضو إذا فشل تخزين challenge بعد تقييده. كل `asyncio.create_task` طويل العمر يحتاج reference وإلغاء وتنظيفاً عند النجاح أو الانتهاء.

يجب أن يستخدم CAPTCHA مصدراً عشوائياً مناسباً للغرض الأمني، وأن يتحقق callback من user ownership ومن chat ownership، لا من payload وحده. يجب عزل فشل metrics والإشعارات الثانوية عن العملية الأساسية، مع إبقاء فشل Telegram الأساسي ظاهراً في النتيجة.

كل action moderation يحتاج `execution_status` واضحاً يميز القرار غير التنفيذي، suppression، التنفيذ الناجح، والفشل. لا يُسجل action غير معروف أو escalation بلا مستلم أو lockdown فاشل كنجاح. يجب أن تحمل audit events حالة التنفيذ والخطأ، لا القرار فقط.

يجب فرض ملكية التذاكر داخل support engine، وليس في الواجهة وحدها. أي reply غير إداري يحتاج أن يطابق `ShopUser.id` مع مالك التذكرة، ويجب رفض ticket references والتصنيفات غير الصالحة قبل كتابة user state. لا تُرسل نصوص الاستثناءات أو ادعاءات زمن استجابة غير مبنية على metric للمستخدم.

## الجولة العاشرة — المتجر والمهام وredirect security

يجب اعتبار أي سعر أو كمية أو coupon ID قادماً من Telegram state أو user_data غير موثوق. `create_order` ملزم بإعادة جلب الخدمة والتسعير والمخزون والقيود من قاعدة البيانات داخل transaction. `pay_order` ملزم بإعادة التحقق من السعر والكوبون والمخزون والرصيد مع row lock قبل الخصم، ولا يُستهلك coupon إلا بعد الدفع الناجح وتسجيل `CouponUsage` في نفس المعاملة.

يجب أن تفرض محركات order وsupport الملكية والحالات المسموحة، لا أن تعتمد على handler فقط. لا يجوز للـrefund أن يعمل لطلب غير مدفوع أو لمستخدم لا يملكه، ولا يجوز للفشل النهائي أن يترك رصيد المستخدم مخصوماً دون سياسة رد موثقة ومعاملة ledger مقابلة. لا تُعرض نصوص الاستثناءات الداخلية للمستخدم.

كل fire-and-forget task طويل العمر يجب أن يمر عبر `src/utils/background_tasks.py` أو registry مكافئ يحتفظ بمرجع، ويسجل الاستثناء، ويدعم الإلغاء في `post_shutdown`. لا تُستخدم raw URLs في Telegram callback data عندما يمكن تجاوز حد الحجم؛ استخدم token قصيراً محدود الصلاحية ومربوطاً بسياق chat/user في Redis.

يجب بناء `InlineKeyboardMarkup` قبل إرساله وعدم تعديل كائنات Telegram المجمدة بعد الإنشاء. في أي SSRF fetch أو redirect expansion يجب تعطيل auto-follow والتحقق من كل redirect وسيط قبل الطلب التالي، مع scheme/DNS/IP checks وحد redirect.

## الجولة الحادية عشرة — قواعد التشغيل الجديدة

يجب أن تطابق جميع rules callbacks chat الرسالة المصدر قبل قراءة القواعد أو إرسالها، ولا يكفي التحقق من أن chat ID رقم صحيح. يجب أن تستبدل welcome كل placeholders الموثقة، وأن تكون عمليات قراءة settings/rules وmember count fail-safe دون عرض tokens خام أو ادعاء count غير مؤكد.

يجب ألا ينشئ `/skip` player loop جديداً إذا كان loop الحالي يعمل. التخطي يمر عبر state مشتركة، ولا يُعلن نجاحه إلا بعد تأكيد backend الصوتي. كل player task طويل العمر يمر عبر background registry مع مرجع وإلغاء منظم.

Celery batch tasks يجب أن تكون idempotent أمام redelivery، وأن تستخدم retry/backoff للخطأ القابل لإعادة المحاولة. لا تُرسل تفاصيل Telegram/provider/database إلى المستخدم؛ سجّل الخطأ داخلياً وأرسل رسالة عامة، مع إبقاء أخطاء الإدخال المتوقعة واضحة.

## الجولة الثانية عشرة — قواعد قسم المجموعات

يجب رفض game callback إذا كان chat ID المضمن في vote/night/topic لا يطابق chat الرسالة الحالية، ولا يجوز الوصول إلى session اعتماداً على payload غير موثق. عند downgrade لأي عقوبة بسبب ban cap أو safety policy يجب تحديث `ctx.decision.action` قبل audit حتى يطابق القرار الفعل المنفذ.

يجب أن تكون `moderation_level` per-group ومتصلة فعلياً بـdecision policy عبر adaptive threshold cache، مع إبقاء إشارات الخطر الصريحة مثل blacklist وphishing وNSFW وhate speech وcoordinated spam فوق profile الخفيف. لا تستخدم قيمة Redis صفرية أو فاسدة كحد يؤدي إلى اعتبار كل الرسائل مخالفات.

قواعد المحتوى الخاصة بالمجموعة تُدار عبر manager واحد مع حدود 100 قاعدة و512 حرفاً، compile validation، regex timeout، cache invalidation، ومرور النتيجة عبر fast_rules ثم action_execution وaudit. لا تسجل arguments الحساسة في admin audit؛ سجل group/admin/command فقط، وفشل modlog لا يكسر أمر الإدارة.


## الجولة الثالثة عشرة — تكامل منظومة المجموعات

يجب أن تكون إعدادات `smart_responses` و`leave_enabled` و`leave_msg` per-group عبر `group_settings`، وأن تمر الرسائل التلقائية عبر Redis cooldown أو member-update flow الفعلي. رسالة المغادرة تعتمد على `ChatMemberHandler.CHAT_MEMBER`؛ لا تُعلن نجاحها إذا فشل إرسال Telegram، ولا تُعد حماية أو إشعاراً مضموناً عندما لا تصل تحديثات `chat_member` أو لا يملك البوت صلاحية الإدارة.

يجب أن يبقى `/undo` محمياً بـ`_admin_only`، وأن يقرأ آخر `ModerationEvent` قابل للعكس داخل المجموعة والمستخدم قبل تنفيذ Telegram. لا يجوز التراجع عن حدث غير موجود، ولا اعتبار التراجع ناجحاً قبل نجاح `unban_chat_member` أو `restrict_chat_member`. لا يُفترض أن السجل الحالي يعيد بناء تخصيصات الصلاحيات التاريخية؛ استعادة mute تستخدم مجموعة الصلاحيات القياسية التي يحددها البوت.

حفظ نقاط الألعاب يتم عبر `BaseGame.get_scores()` و`GameSessionManager.persist_scores()` في Redis sorted set مع marker وTTL، ويجب أن يكون idempotent عند تكرار `stop` أو حذف session. لا تُولد نقاط للعبة لا تملك عقد scoring؛ Mafia حالياً لعبة فعلية بلا scoring contract، لذلك scoreboard الخاص بها فارغ بدلاً من بيانات مصطنعة. أي لعبة جديدة تضيف نقاطاً يجب أن تختبر الأرشفة والقراءة بعد حذف الجلسة.

في نهاية الجولة الثالثة عشرة تم التحقق من `compileall`، وsuite كاملة من **235 اختباراً ناجحاً**، و`pip check`، و`pip-audit -r requirements.txt`، وRuff correctness checks. لا يزال الاختبار الحي لـTelegram API وPostgreSQL وCelery وPyTgCalls وyt-dlp خارج البيئة المعزولة ويحتاج credentials وخدمات حقيقية.


## الجولة الرابعة عشرة — قواعد سلامة المجموعات والتكامل

Exact duplicate detection يجب أن يكون user-scoped داخل المجموعة، وأن يستخدم Redis atomic reservation (`SET ... NX`) بدلاً من `exists` ثم `set` المنفصلين. لا تستخدم fingerprint فارغاً للرسائل media-only؛ تنتمي هذه الرسائل إلى media-rate rules. التكرار بين مستخدمين والتنسيق الجماعي يمران عبر near-duplicate/coordinated signals المنفصلة.

لا يجوز استخدام Telegram user ID أو اسم المستخدم كدليل على عمر الحساب أو maliciousness. Telegram Bot API لا يعرّض creation date في message updates؛ لذلك تبقى account age `unknown/unavailable` ولا تدخل قرار moderation، ويجب أن يعرض userinfo هذا الحد بوضوح. تقارير trust تستخدم profile cache canonical ثم GroupMember fallback، ولا تعتمد على مفاتيح Redis قديمة غير موصولة بمسار الكتابة.

أي signal عالي الثقة يضبط `decision.action` إلى delete أو ban يجب أن يضبط أيضاً `ctx.short_circuit` عندما يكون استمرار الطبقات قادراً على استبدال القرار. ينطبق ذلك على fast rules، language policy، وcritical evasion attacks. أما الإشارات الاحتمالية فلا تُرفع إلى حظر مباشر دون مسار risk/decision قابل للتدقيق.

أوامر إدارة المجموعة لا تعمل في private chat حتى لو كان المستخدم allowlisted؛ يجب التحقق من `effective_chat.type` كـ`group` أو `supergroup` قبل تعديل group settings أو whitelist state. الأوامر الأمنية المباشرة التي لا تمر عبر decorator المشترك يجب أن تسجل audit باسم الأمر فقط بعد نجاح العملية، ولا تسجل arguments أو secrets.

`lang_policy` canonical داخل `group_settings`. عند قراءة legacy `lang_policy:{chat_id}` يجب ترحيله lazy إلى schema canonical ثم حذف المفتاح القديم. لا تُنشئ طبقات settings متوازية تعرض `/settings` قيمة مختلفة عن القيمة التي يقرأها pipeline.

أرشفة scores في الألعاب يجب أن تستخدم distributed lock وRedis transaction بحيث لا يُكتب marker قبل نجاح scoreboard، ويجب أن تكون قابلة لإعادة المحاولة بعد failure. `BaseGame.get_scores()` لا يقبل `NaN` أو `Infinity` أو القيم غير المحدودة. لا تُولد نقاط للعبة لا تملك scoring contract.

كل cooldown أو token Redis جديد في smart interaction يستخدم `settings.redis_prefix`. download tokens قصيرة العمر ومربوطة بالـchat والـuser وتُستهلك عبر `getdel` مرة واحدة. لا تُرسل raw URLs في callback data.


## الجولة الخامسة عشرة — ربط anti-raid بإعدادات المجموعة

`anti_raid` هو إعداد canonical داخل `group_settings`، ويجب أن يقرأه `src/pipeline/raid_detector.py::check_raid` قبل عدّ الانضمامات أو تنفيذ lockdown. الأمر `/setraid on|off` متاح فقط داخل `group` أو `supergroup` عبر `_admin_only`، ويجب أن يكتب إلى نفس Redis hash الذي يقرأه detector و`/settings`. عند فشل قراءة الإعداد، لا يجوز تنفيذ lockdown بناءً على قيمة غير مؤكدة؛ يجب تسجيل degradation داخلياً وإرجاع نتيجة غير تنفيذية. تبقى عتبة raid ونافذته global settings، ويبقى التنفيذ مشروطاً بتحديثات `chat_member` وصلاحيات Telegram الفعلية، ولا يجوز وصفه كمنع مضمون للـraid.


## الجولة السادسة عشرة — مصدر warn_limit canonical

يجب أن يبقى `group_settings.warn_limit` المصدر الوحيد لحد التحذيرات لكل مجموعة. `smart_warn.get_max_warns` و`set_max_warns` يمران عبر manager القائم، ولا يجوز إعادة إنشاء مفتاح `warnlimit:{chat_id}` كمصدر تشغيل مستقل. عند وجود legacy صالح يتم lazy migration إلى hash ثم حذف المفتاح القديم، وعند وجود قيمة غير صالحة يستخدم النظام default 5 مع تسجيل داخلي. `reset_settings` يحذف canonical وlegacy معاً. أي تعديل مستقبلي على إعدادات الإدارة يجب أن يختبر اتساق `/settings` مع القيمة التي يقرأها pipeline أو smart_warn فعلياً.


## الجولة السابعة عشرة — atomic warn history

يجب أن يمر تحديث `warns:{chat_id}:{user_id}` عبر Redis `WATCH/MULTI/EXEC` أو آلية ذرية مكافئة تمنع read-modify-write المتوازي. يجب أن تكون retries محدودة، وألا يسجل `warn_added` أو يعاد `WarnStatus` كنجاح قبل نجاح EXEC. عند فشل Redis أو استنفاد التعارضات يجب رفع degradation للمسار الأعلى دون إعلان نجاح للمستخدم. هذا العقد لا يغطي raid-lockdown الذي يحتاج reservation مستقلة.


## الجولة الثامنة عشرة — raid activation reservation

يجب أن يستخدم مسار raid lockdown reservation ذرية عبر `SET NX EX` على key namespaced لكل مجموعة قبل أي Telegram mutation. لا يجوز تثبيت `lockdown:{chat_id}` أو إعلان نجاح قبل نجاح `_activate_lockdown` الفعلي. عند فشل Telegram تُحذف reservation، وعند فشل state commit لا تُحذف reservation قبل انتهاء TTL حتى لا يسمح المسار بتكرار mutation أثناء degradation. هذا لا يعوض rollback تلقائياً للخطوات Telegram الجزئية.


## الجولة التاسعة عشرة — compensation للـraid الجزئي

يجب أن يتتبع `_activate_lockdown` mutations Telegram التي نجحت فعلياً. عند فشل خطوة لاحقة، يُسمح فقط بتعويض best-effort إلى baseline الصريح الذي يحدده البوت: default permissions ثم slow mode صفر. لا يجوز الادعاء باستعادة تخصيصات تاريخية غير مقروءة، ولا يجوز تثبيت Redis marker أو تسجيل نجاح إذا فشلت العملية الأساسية أو compensation. إشعارات admins الثانوية تبقى best-effort ولا تعطل primary lockdown الناجح.


## الجولة العشرون — اتساق Telegram وRedis وDB

يجب ألا يُستخدم PostgreSQL mirror لإثبات نجاح Telegram. في activation يُحدّث DB بعد نجاح Telegram وRedis marker، وفي release تُنفذ Telegram primary operations قبل حذف Redis marker. عند فشل Telegram release يجب إبقاء marker وعدم مسح DB mirror، وعند فشل DB بعد نجاح Telegram يُسجل فشل ثانوي وتُحافظ العملية على حقيقة Telegram الفعلية. لا توجد transaction عالمية عبر Telegram وRedis وPostgreSQL؛ لا تدّعِ atomicity مطلقة.


## sweep الشامل — CAPTCHA

يجب أن يمر كل timeout task في CAPTCHA عبر `create_background_task` حتى يُحتفظ به ويُسجل فشله ويُلغى في shutdown. مصدر إعداد CAPTCHA الوحيد هو `group_settings` canonical؛ أي legacy `captcha_enabled:{chat_id}` يُرحّل lazy إلى `captcha=on|off` ثم يُحذف، ولا يجوز إعادة إنشاء مصدر Redis موازٍ.


## الجولة الحادية والعشرون — sweep شامل

يجب أن تستخدم CAPTCHA timeout tasks سجل `create_background_task` المركزي، وأن تستخدم CAPTCHA إعداد `group_settings` canonical فقط مع lazy migration وحذف legacy. يجب إصلاح أخطاء الصحة الحرجة مثل F821 وRUF012 قبل التسليم. لا تُطبق إصلاحات Ruff غير الآمنة على moderation أو payments أو provider code دون مراجعة واختبارات؛ يجب توثيق الدين الأسلوبي المتبقي بدلاً من ادعاء اكتماله.


## الجولة الثانية والعشرون — البنية المحلية والتكاملات الخارجية

يجب اختبار Celery tasks التي تستخدم AsyncEngine على event loop ثابت لكل worker process، وعدم إنشاء loop ثم إغلاقه بعد كل task. PostgreSQL staging المحلي لا يساوي production؛ يجب إبقاء migration وبيانات production خارج الاختبار المحلي. Docker image وCompose readiness لا يثبتان Telegram أو providers، ولا يجوز تشغيل instant fulfillment أو voice playback أو Mafia scoring دون backend/credentials/contract حقيقي.
