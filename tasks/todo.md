# قائمة تنفيذ Guardian Bot

## خط الأساس
- [x] استخراج الأرشيف وفحص البنية
- [x] تشغيل compileall
- [x] تشغيل الاختبارات: 119 نجاحاً، 36 فشلاً
- [x] حفظ تقرير التدقيق الأولي

## الأمان والأساسيات
- [x] إصلاح `telegram_admin_ids` validator
- [x] تشديد إعدادات token وwebhook وenvironment
- [x] التحقق من صلاحيات الإدارة داخل المجموعة
- [x] مراجعة redaction للأسرار والـ DSN
- [x] جعل حصص Redis والإجراءات قابلة للتدقيق والذرية
- [x] تقوية Docker/Compose

## الوظائف والمعمارية
- [x] مراجعة ترتيب handlers وتداخل الألعاب مع الإشراف
- [x] تحديد حدود الإدخال والمهل للروابط والوسائط
- [x] تحسين أخطاء Telegram و429 وsafe-mode
- [x] مراجعة degraded mode للطبقات الاختيارية
- [ ] إضافة health/diagnostics آمنة — لم تُنفذ لعدم وجود متطلب مثبت في المشروع

## الاختبارات
- [x] اختبارات إعدادات وأمان
- [x] اختبارات Redis تكاملية حقيقية عند توفره
- [ ] اختبارات PostgreSQL تكاملية عند توفره — PostgreSQL غير متاح في البيئة
- [ ] اختبارات end-to-end غير مدمرة لمسار pipeline — تحتاج تكاملات خارجية فعلية
- [x] coverage/lint/type/dependency checks
- [ ] Docker build/validation عند توفر daemon

## الجولة الرابعة — الألعاب المملوكة للبوت
- [x] تدقيق جميع game plugins وتحديد wrappers الخارجية والـ placeholders
- [x] حذف الألعاب الخارجية والوهمية من المصدر والregistry
- [x] إعادة بناء Mafia داخل Telegram مع أدوار وأفعال وتصويت وحسم فعلي
- [x] إعادة بناء Chameleon داخل Telegram مع موضوع وكلمة سرية وclues وتصويت فعلي
- [x] تقوية session persistence وDM callback routing
- [x] تسجيل `/mafia_start` و`/cham_start` كأوامر صريحة
- [x] إضافة اختبارات gameplay وRedis persistence وcommand routing
- [x] تشغيل compileall و`pytest -W error`: **166 اختباراً ناجحاً**

## التسليم
- [x] تحديث README و`.env.example` وAGENT.md
- [x] كتابة `tasks/games-audit.md` و`tasks/games-report.md`
- [x] توثيق المتطلبات الخارجية وخطوات التشغيل
- [x] تجهيز `Guardian-bot-games-pass.zip` دون `__pycache__` أو `.pyc` أو `.db`

## الجولة الخامسة — توحيد command routing
- [x] فحص wiring الفعلي للميزات والألعاب والاختبارات والاعتماديات
- [x] توثيق تعارض التسجيل المكرر لـ`/play`
- [x] جعل `message_handler` المالك الوحيد لـ`/play`
- [x] إضافة `/music` كمدخل صريح لمشغل الصوت
- [x] حماية edge case مثل `/play mafia song`
- [x] إزالة dependency declaration المكرر
- [x] مزامنة `Game_System_Documentation.md` مع الحالة الفعلية
- [x] إضافة regression tests للـ ownership والـ dispatching
- [x] تشغيل compileall و`pytest -W error`: **168 اختباراً ناجحاً**
- [x] كتابة `tasks/round5-report.md` وسجل التحقق النهائي
- [ ] إصلاح جميع مخالفات Ruff العامة — خارج نطاق الجولة، وعددها 623 في خط الأساس
- [ ] اختبار Bot API وvoice backend بشكل حي — يحتاج token ومجموعة وبيئة خارجية فعلية

## الجولة السادسة — الوظائف والعمليات والـlifecycle
- [x] جرد handlers والميزات وpipeline وDB وRedis وCelery والمتجر والألعاب
- [x] إثبات فجوة voice backend startup/shutdown
- [x] ربط voice backend بدورة lifecycle مع degradation آمن
- [x] إثبات فجوة raid TTL دون Telegram cleanup
- [x] إضافة JobQueue auto-release حقيقي للـraid lockdown
- [x] إضافة metrics فعلية للـraids وcircuit suppressions وtop offenders
- [x] إضافة اختبار Redis roundtrip حقيقي للتقارير
- [x] تحديث report contract لإزالة الادعاءات غير الموصولة
- [x] تشغيل compileall و`pytest -W error`: **175 اختباراً ناجحاً**
- [x] تشغيل `pip check` و`pip-audit`: ناجحان
- [x] كتابة `tasks/round6-report.md` وملفات التحليل والتحقق
- [ ] ربط Celery tasks غير الموصولة بالـhot path — مؤجل حتى تعريف سياسة enqueue/retry/monitoring
- [ ] اختبار Telegram وvoice backend حياً — يحتاج token وsession ومجموعة فعلية

## تدقيق الوظائف الحقيقية — المتجر والوسائط والصوت
- [x] كشف الإيداع الفوري الوهمي في المتجر
- [x] تحويل الإيداع إلى Telegram Payments invoice/pre-checkout/successful_payment
- [x] تعطيل الإيداع بأمان عند غياب provider token
- [x] فصل adjustment الإداري عن user deposit
- [x] منع instant fulfillment دون executor حقيقي
- [x] إصلاح إرسال الوسائط عبر Bot API بدلاً من Chat methods غير المدعومة
- [x] منع voice queue/playback الوهمي عند غياب PyTgCalls/Pyrogram
- [x] إضافة اختبارات الدفع والوسائط والـvoice: **182 اختباراً ناجحاً**
- [x] كتابة `tasks/real-functionality-report.md` وسجلات التدقيق والتحقق
- [ ] اختبار دفع حي ومزود دفع حي — يحتاج provider token ومجموعة/حساب خارج البيئة
- [ ] تنفيذ instant fulfillment — مؤجل حتى توفير provider executor موثق وقابل للتدقيق

## الجولة الثامنة — مراجعة شاملة للأقسام والوظائف
- [x] جرد جميع الأقسام والميزات والhandlers والاعتماديات والتدفقات الفعلية
- [x] حفظ `tasks/round8-full-inventory.txt` و`tasks/round8-analysis.md`
- [x] إضافة runtime diagnostics حقيقية إلى `/status` لقاعدة البيانات وRedis وvoice والدفع والألعاب
- [x] إصلاح رجوع قائمة `/games` وإغلاقها بشكل صحيح
- [x] إضافة recommendations إلى storefront باستخدام backend الموجود فعلياً
- [x] تسجيل layer failures من pipeline داخل Redis وتقارير المجموعة
- [x] تقوية shop callbacks ضد payloads غير الصالحة
- [x] إضافة اختبارات diagnostics وrecommendations وcallback validation وRedis report roundtrip
- [x] تشغيل `compileall` و`pytest -W error`: **187 اختباراً ناجحاً**
- [x] تحديث README وAGENT
- [ ] اختبارات Telegram وpayment provider وvoice backend حية — تحتاج credentials وبيئة خارجية
- [ ] instant fulfillment — لا يُنفذ قبل بناء executor/provider موثق وقابل للتدقيق

## الجولة التاسعة — التنفيذ والملكية وحالات الفشل
- [x] تثبيت baseline الجولة التاسعة: 187 اختباراً ناجحاً قبل التعديل
- [x] جرد فجوات CAPTCHA وcallback وaction execution والدعم
- [x] جعل CAPTCHA fail-safe عند فشل Redis أو Telegram
- [x] منع استهلاك challenge قبل نجاح استعادة الصلاحيات
- [x] إدارة وإلغاء auto-kick tasks واستخدام SystemRandom
- [x] منع cross-chat CAPTCHA callbacks
- [x] إضافة execution_status وexecution_error إلى moderation context والتدقيق
- [x] منع نجاح escalation بلا مستلم وraid lockdown بلا Telegram mutation
- [x] منع action غير المدعوم من التسجيل كنجاح
- [x] فرض ملكية support ticket داخل engine
- [x] تقوية support callbacks ومنع تسريب الاستثناءات والادعاءات غير الموثقة
- [x] إضافة 11 اختباراً تنفيذياً جديداً وتشغيل suite: **198 اختباراً ناجحاً**
- [x] كتابة `tasks/round9-report.md` وتحديث README وAGENT
- [ ] اختبار Telegram API وCAPTCHA والدفع وvoice provider بشكل حي — يحتاج credentials وبيئة خارجية
- [ ] تنفيذ instant fulfillment وCelery hot-path — يحتاج provider/executor وسياسة تشغيل مستقلة

## الجولة العاشرة — تكامل المتجر والمهام والأمن
- [x] تثبيت baseline الجولة العاشرة: 198 اختباراً ناجحاً
- [x] جرد الأقسام الفعلية ومسارات commands/callbacks والمهام الخارجية
- [x] كتابة `tasks/round10-plan.md` و`tasks/round10-research-notes.md`
- [x] جعل create_order يعيد جلب الخدمات ويستخدم التسعير server-side بدلاً من السعر الموجود في user_data
- [x] التحقق من active/stock/min/max/required level ومنع تكرار الخدمة داخل الطلب
- [x] فصل حساب الخصم عن استهلاك الكوبون وتسجيل CouponUsage فقط بعد الدفع الناجح
- [x] حماية الدفع بـrow locks وإعادة التحقق من السعر والكوبون والمخزون والرصيد
- [x] فرض ملكية تفاصيل الطلب والاسترداد ومعالجة malformed callbacks
- [x] تقوية complete/fail/refund transitions ورد الرصيد تلقائياً عند الفشل النهائي
- [x] تقوية admin order callbacks ومنع تسريب الأخطاء وإشعار المستخدم بالفشل
- [x] إضافة registry للمهام الخلفية وربطه بـpost_shutdown
- [x] تحويل تنزيلات media/Instagram/SoundCloud وsmart responses وwelcome deletion إلى registry
- [x] استبدال raw URLs في smart callback بـRedis tokens قصيرة مرتبطة بـchat/user وTTL
- [x] إصلاح InlineKeyboardMarkup mutation غير المدعوم في PTB v22
- [x] منع SSRF عبر redirect وسيط في safe_fetch وlink expansion
- [x] إضافة اختبارات تكامل المتجر وlifecycle وsmart token وSSRF redirects
- [x] نتيجة suite: **209 اختباراً ناجحاً**
- [x] compileall وpip check وpip-audit وRuff correctness checks ناجحة
- [ ] اختبار Telegram API وPostgreSQL وRedis وyt-dlp وvoice provider بشكل حي — يحتاج بيئة credentials وخدمات خارجية
- [ ] إجراء rollout production ومراقبة معاملات المتجر بعد النشر — خارج sandbox

## الجولة الحادية عشرة — welcome، callbacks، الصوت، Celery، وحماية الإدارة
- [x] تثبيت baseline الجولة الحادية عشرة: 209 اختباراً ناجحاً
- [x] إعادة جرد الأقسام ومسارات الألعاب والhandlers والمهام الخارجية
- [x] حفظ `tasks/round11-recon.txt` و`round11-games-audit.txt` و`round11-research-notes.md`
- [x] إكمال placeholders الموثقة في welcome: `{count}` و`{rules}`
- [x] جعل welcome fail-safe عند تعطل Redis/settings مع جلب عدد الأعضاء عند الحاجة فقط
- [x] منع cross-chat rules acknowledgment وshow-rules callbacks
- [x] إصلاح سباق voice `/skip` الذي كان يمكن أن ينشئ player loops متوازية
- [x] ربط player loops الصوتية بالـbackground task registry
- [x] جعل Celery batch logging idempotent عند إعادة تسليم نفس message داخل group/user
- [x] إضافة retry/backoff لمسار recalculate trust وbatch logging
- [x] منع تسريب TelegramError وتفاصيل الأخطاء الداخلية من أوامر الإدارة والمتجر والدعم
- [x] مزامنة help الخاص بـ`/setwelcome` مع placeholders الفعلية
- [x] إضافة 7 اختبارات للجولة الحادية عشرة: welcome، callbacks، voice، Celery، وتسريب الأخطاء
- [x] نتيجة suite النهائية: **216 اختباراً ناجحاً**
- [x] compileall وpip check وpip-audit وRuff correctness ناجحة
- [ ] اختبار Telegram API وPostgreSQL وRedis/Celery worker وPyTgCalls وyt-dlp بشكل حي — يحتاج credentials وخدمات خارجية
- [ ] rollout production ومراقبة skip/queue وCelery retries وwelcome jobs في staging — خارج sandbox

## الجولة الثانية عشرة — منظومة المجموعات
- [x] تثبيت baseline قسم المجموعات: 216 اختباراً ناجحاً
- [x] جرد Telegram entry points وhandlers وmiddleware وpipeline والصلاحيات والبيانات والألعاب
- [x] حفظ `tasks/round12-baseline.txt` و`round12-groups-recon.txt` و`round12-research-notes.md`
- [x] منع cross-chat game callbacks قبل الوصول إلى GameSessionManager
- [x] تصحيح audit drift عند downgrade من ban إلى mute بسبب hourly ban cap
- [x] إضافة moderation profiles per-group: light/moderate/strict عبر `/setmoderation`
- [x] ربط moderation profile بـadaptive thresholds وdecision ladder مع إبقاء overrides عالية الخطورة
- [x] إضافة `/setlimits` لحدود الروابط والمنشنات per-group مع validation 1–50
- [x] إضافة clamping داخل fast_rules لمنع الصفر والقيم الفاسدة من false positives جماعية
- [x] إضافة group-specific content patterns عبر Redis: `/groupaddpattern` و`/groupremovepattern` و`/grouppatterns`
- [x] دعم literal/regex، categories، حد 100 قاعدة، regex validation وcache invalidation وtimeout bounded search
- [x] ربط group patterns مع fast_rules وaction execution/audit pipeline
- [x] إضافة admin command audit trail إلى modlog دون تسجيل arguments حساسة
- [x] إضافة `/grouphelp` لأعضاء المجموعة مع تقليل الردود غير الضرورية
- [x] إضافة 9 اختبارات جديدة لقسم المجموعات؛ النتيجة النهائية: **225 اختباراً ناجحاً**
- [x] compileall وpip check وpip-audit وRuff correctness ناجحة
- [ ] اختبار Telegram API وPostgreSQL وRedis/Celery وPyTgCalls/yt-dlp بشكل حي — يحتاج credentials وخدمات خارجية
- [ ] staging rollout وقياس latency/throughput في مجموعة نشطة — خارج sandbox


## الجولة الثالثة عشرة — تعميق تكامل المجموعات
- [x] تثبيت baseline الجولة: 225 اختباراً ناجحاً قبل تعديلات الجولة
- [x] إضافة Redis distributed lock ذري حول إنشاء GameSession لمنع race condition
- [x] إضافة `smart_responses` per-group و`/setsmart` مع Redis cooldown للحجز قبل الرد التلقائي
- [x] إصلاح Chameleon private-topic callback عند اختلاف chat الجلسة عن private chat
- [x] إضافة `/undo <user_id>` لآخر mute/ban مسجل، مع تحقق DB ثم Telegram success قبل إعلان التراجع
- [x] إضافة `leave_enabled` و`leave_msg` و`/setleave` و`/leave` و`/testleave` وربطها بـChatMember update الفعلي
- [x] إضافة أرشفة نقاط الألعاب عبر Redis sorted sets وmarker idempotency و`/gamescores`
- [x] منع توليد نقاط مصطنعة للألعاب التي لا تملك scoring contract؛ Mafia ما زالت بلا scoring
- [x] إضافة اختبارات race/smart/callback/setsmart/undo/leave/score persistence
- [x] التحقق النهائي: compileall، **235 اختباراً ناجحاً** مع `-W error`، pip check، pip-audit، وRuff correctness
- [x] تحديث README وAGENT وهذه القائمة وكتابة `tasks/round13-report.md`
- [ ] اختبار Telegram API وPostgreSQL وRedis/Celery worker وPyTgCalls/yt-dlp بشكل حي — يحتاج credentials وخدمات خارجية
- [ ] staging rollout وقياس latency/throughput ومراجعة audit events في مجموعة نشطة — خارج sandbox
- [ ] تصميم scoring contract للعبة Mafia — مؤجل عمداً لعدم اختراع قواعد نقاط غير موجودة


## الجولة الرابعة عشرة — خطة تطوير منظومة المجموعات

مرجع الخطة التفصيلية: `tasks/round14-plan.md`، وملاحظات البحث الرسمي: `tasks/round14-research-notes.md`.

- [x] قراءة متطلبات الجولة الرابعة عشرة وحفظها ضمن سياق التنفيذ
- [x] تنفيذ reconnaissance read-only وحفظ `tasks/round14-recon.txt`
- [x] مراجعة Telegram Bot API وpython-telegram-bot v22.8 وحفظ المصادر
- [x] تثبيت خطة التنفيذ ومعايير القبول قبل تعديل الكود
- [x] تثبيت baseline الاختبارات قبل تعديلات الجولة: 235 اختباراً ناجحاً
- [x] تقوية spam/flood/duplicate/coordinated behavior مع Redis NX، user-scoped fingerprints، واختبارات Redis/concurrency
- [x] مراجعة وإصلاح account heuristics ومنع اتخاذ قرار من user ID وحده؛ userinfo يوضح حدود Bot API
- [x] تحسين media fingerprint وfast-rule/language/evasion precedence مع short-circuit للإشارات عالية الثقة
- [x] توحيد lang_policy مع group_settings، وإضافة group-only authorization وaudit للأوامر الأمنية المباشرة
- [x] تقوية score persistence transaction/lock، والتحقق من finite scores، وتوحيد Redis namespace للتفاعل الذكي
- [x] تشغيل الاختبارات المركزة ثم suite كاملة وcompileall وpip check وpip-audit وRuff؛ النتيجة النهائية 245 اختباراً ناجحاً
- [x] تحديث README وAGENT وكتابة `tasks/round14-report.md`
- [x] تجهيز `Guardian-bot-round14-groups-pass.zip` وSHA-256 وفحص integrity؛ 242 ملفاً، artifacts الممنوعة غائبة
- [x] توثيق Telegram/PostgreSQL/Celery/provider tests غير المنفذة إن بقيت خارج البيئة في التقرير


## الجولة الخامسة عشرة — ربط حماية raid بإعدادات المجموعة

- [x] فحص baseline ومسار group member إلى `check_raid` مع 245 اختباراً ناجحاً قبل التعديل
- [x] إثبات أن `anti_raid` كانت معروضة في `group_settings` و`/settings` دون قراءة في detector
- [x] ربط `anti_raid` canonical بمسار `check_raid` قبل عدّ الانضمامات أو تنفيذ lockdown
- [x] إضافة `/setraid on|off` عبر `_admin_only` والتسجيل في command router القائم
- [x] إضافة اختبارات enabled/disabled/settings failure/command validation
- [x] تشغيل compileall وsuite كاملة مع `-W error`: **249 اختباراً ناجحاً**
- [x] تشغيل `pip check` و`pip-audit -r requirements.txt` وRuff correctness checks: ناجحة
- [x] تحديث README وAGENT وكتابة `tasks/round15-recon.md` و`tasks/round15-plan.md` و`tasks/round15-report.md`
- [ ] اختبار Telegram API الحي وraid lockdown في staging — يحتاج token ومجموعة وصلاحيات حقيقية


## الجولة السادسة عشرة — مراجعة شاملة وتوحيد warn_limit

- [x] جرد جميع الأقسام الفعلية ومسارات التسجيل والتخزين والمهام والاختبارات
- [x] تثبيت baseline الجولة: compileall ناجح و**249 اختباراً ناجحاً** مع `-W error`
- [x] حفظ `tasks/round16-baseline-inventory.txt` و`tasks/round16-full-recon.txt`
- [x] إثبات انفصال `group_settings.warn_limit` عن `smart_warn.warnlimit:{chat_id}`
- [x] توحيد القراءة والكتابة عبر `group_settings` canonical
- [x] lazy migration للمفتاح القديم الصالح وحذفه، وإهمال legacy غير الصالح
- [x] جعل reset يحذف canonical وlegacy وإضافة validation مركزي 1–10
- [x] إضافة اختبارات default/round-trip/migration/invalid/reset/failure
- [x] تشغيل focused suite: **49 اختباراً ناجحاً**
- [x] تشغيل suite كاملة: **254 اختباراً ناجحاً** مع `-W error`
- [x] تشغيل compileall وpip check وpip-audit وRuff المحدد: ناجحة
- [x] كتابة `tasks/round16-plan.md` و`tasks/round16-report.md`
- [ ] إصلاح atomicity لتحديث warn history وraid lockdown concurrency في جولة مستقلة
- [ ] اختبارات Telegram/PostgreSQL/Celery/providers الحية وstaging rollout — خارج البيئة الحالية


## الجولة السابعة عشرة — atomic warn history

- [x] تثبيت baseline الجولة من حالة Round 16: 254 اختباراً ناجحاً
- [x] إثبات نافذة read-modify-write في `smart_warn.add_warn`
- [x] اعتماد Redis WATCH/MULTI/EXEC مع retries محدودة
- [x] منع تسجيل warn success قبل نجاح EXEC
- [x] إضافة اختبار Redis حقيقي لتحذيرين متزامنين
- [x] إضافة اختبار WatchError retry واختبار Redis failure safety
- [x] تشغيل focused suite: **42 اختباراً ناجحاً**
- [x] تشغيل suite كاملة: **257 اختباراً ناجحاً** مع `-W error`
- [x] تشغيل compileall وpip check وpip-audit وRuff المحدد: ناجحة
- [x] تحديث README وAGENT وكتابة `tasks/round17-plan.md` و`tasks/round17-report.md`
- [ ] تقوية reservation الخاصة بـraid lockdown عند concurrent joins — جولة مستقلة


## الجولة الثامنة عشرة — atomic raid reservation

- [x] إثبات race بين lockdown exists check وTelegram activation
- [x] إضافة `raid_activation:{chat_id}` reservation عبر `SET NX EX`
- [x] تثبيت active marker بعد نجاح `_activate_lockdown` فقط
- [x] تحرير reservation عند فشل Telegram
- [x] إبقاء reservation TTL عند فشل state commit لمنع duplicate mutation أثناء degradation
- [x] إضافة اختبار concurrent joins على Redis حقيقي
- [x] إضافة اختبارات Telegram failure وRedis state failure
- [x] تشغيل focused suite: **24 اختباراً ناجحاً**
- [x] تشغيل suite كاملة: **260 اختباراً ناجحاً** مع `-W error`
- [x] تشغيل compileall وpip check وpip-audit وRuff المحدد: ناجحة
- [x] تحديث README وAGENT وكتابة `tasks/round18-plan.md` و`tasks/round18-report.md`
- [ ] تصميم compensation للـTelegram mutations الجزئية واختبار staging حي


## الجولة التاسعة عشرة — compensation لفشل raid الجزئي

- [x] تتبع نجاح slow mode وpermissions قبل إشعار المجموعة
- [x] تعويض permissions إلى baseline وslow mode إلى 0 عند فشل لاحق
- [x] تعويض slow mode فقط عند فشل permissions
- [x] تسجيل فشل compensation داخلياً دون إعلان نجاح
- [x] إضافة اختبارات فشل إشعار المجموعة وفشل permissions
- [x] تشغيل focused suite: **20 اختباراً ناجحاً**
- [x] تشغيل suite كاملة: **262 اختباراً ناجحاً** مع `-W error`
- [x] تشغيل compileall وpip check وpip-audit وRuff المحدد: ناجحة
- [x] تحديث README وAGENT وكتابة `tasks/round19-plan.md` و`tasks/round19-report.md`
- [ ] اختبار Telegram staging وفشل compensation الحي — يحتاج token ومجموعة وصلاحيات حقيقية


## الجولة العشرون — اتساق raid state بين Telegram وRedis وDB

- [x] نقل DB activation mirror إلى ما بعد نجاح Telegram وRedis marker
- [x] إعادة ترتيب release ليحذف Redis marker بعد primary Telegram success
- [x] إبقاء marker وDB mirror عند فشل Telegram release
- [x] تعويض partial release بإعادة slow mode إلى 30 عند فشل permissions
- [x] إضافة اختبارات activation/release وDB failure وTelegram failure
- [x] تثبيت وقت النهار في shop integrity tests لعزل overnight pricing المقصود
- [x] تشغيل focused suite: **19 اختباراً ناجحاً**
- [x] تشغيل shop integrity: **5 اختبارات ناجحة**
- [x] تشغيل suite كاملة: **266 اختباراً ناجحاً** مع `-W error`
- [x] تشغيل compileall وpip check وpip-audit وRuff المحدد: ناجحة
- [x] تحديث README وAGENT وكتابة `tasks/round20-plan.md` و`tasks/round20-report.md`
- [ ] إضافة reconciliation background task بين DB وRedis وTelegram — يحتاج تصميم مستقل وstaging


## sweep الشامل — CAPTCHA وlifecycle

- [x] جرد الأعمال المؤجلة والادعاءات غير المكتملة عبر كامل المشروع
- [x] إثبات raw `asyncio.create_task` في CAPTCHA timeout
- [x] نقل CAPTCHA timeout إلى `create_background_task` مع اسم task واضح
- [x] إثبات config drift بين `group_settings.captcha` و`captcha_enabled:{chat_id}`
- [x] إضافة lazy migration للقيمة القديمة `1/0/on/off/true/false` وحذف legacy key
- [x] جعل CAPTCHA gate يقرأ ويكتب عبر `group_settings` canonical
- [x] إضافة اختبارات lifecycle وcanonical read/write/migration/failure boundaries
- [x] تطبيق الإصلاحات الآلية الآمنة المتاحة من Ruff مع بقاء دين أسلوبي تاريخي موثق
- [x] تشغيل suite بعد sweep: **270 اختباراً ناجحاً** مع `-W error`
- [x] تشغيل quality gates المحددة: compileall وpip check وpip-audit وRuff correctness ناجحة
- [ ] اختبارات Telegram/PostgreSQL/Celery/providers وDocker/staging الحية — خارج البيئة الحالية
- [ ] تنفيذ instant fulfillment أو Mafia scoring دون provider/scoring contract — مرفوض عمداً حتى تتوفر عقود حقيقية


## الجولة الحادية والعشرون — sweep شامل وتنفيذ الأعمال القابلة للإثبات

- [x] جرد الأعمال المؤجلة والوظائف غير المكتملة فعلياً
- [x] نقل CAPTCHA timeout إلى lifecycle registry المركزي
- [x] توحيد CAPTCHA مع `group_settings` canonical وترحيل legacy key
- [x] إصلاح F821 في shop admin وRUF012 في GameManager
- [x] عزل overnight pricing داخل shop tests دون تعديل production logic
- [x] تطبيق safe Ruff auto-fixes مع إبقاء unsafe semantic debt موثقاً
- [x] إضافة اختبارات positive/negative/failure للجولة
- [x] تشغيل suite كاملة: **270 اختباراً ناجحاً** مع `-W error`
- [x] تشغيل compileall وpip check وpip-audit وRuff correctness: ناجحة
- [x] تحديث README وAGENT وكتابة `tasks/round21-plan.md` و`tasks/round21-report.md`
- [ ] Telegram/PostgreSQL/Celery/providers/Docker/staging الحية — تتطلب خدمات وcredentials خارجية
- [ ] instant fulfillment وMafia scoring — لا تُنفذ دون executor/provider وscoring contract حقيقيين


## الجولة الثانية والعشرون — local staging stack

- [x] تثبيت PostgreSQL 16 وتشغيل staging محلي مستقل
- [x] إنشاء قاعدة/user محليين وتطبيق `alembic upgrade head`
- [x] تشغيل Redis المحلي واختبار round-trip من التطبيق
- [x] تشغيل Celery worker وBeat على Redis
- [x] إرسال `recalculate_trust_scores` فعلياً واستلام النتيجة مرتين
- [x] إصلاح event loop reuse في Celery لمنع فشل AsyncEngine بين المهام
- [x] تثبيت Docker daemon وCompose v2
- [x] بناء image `guardian-bot:round22` بنجاح
- [x] تشغيل runtime smoke داخل Docker إلى PostgreSQL وRedis
- [x] تشغيل provider fail-closed tests دون payment/voice credentials
- [x] تشغيل PostgreSQL-focused suite: **51 passed** وprovider suite: **13 passed**
- [x] تشغيل full suite على PostgreSQL وRedis: **271 passed** مع `-W error`
- [x] تشغيل compileall وpip check وpip-audit وRuff correctness: ناجحة
- [x] كتابة `tasks/round22-plan.md` و`tasks/round22-report.md` و`tasks/round22-final-validation.txt`
- [ ] Telegram live/staging وproduction PostgreSQL وprovider executor وperformance rollout — غير متاحة، متروكة معطلة
- [ ] instant fulfillment وMafia scoring — غير منفذين لغياب executor وscoring contract
