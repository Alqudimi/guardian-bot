# خطة الجولة السادسة عشرة — مراجعة شاملة وتوحيد إعدادات التحذير

## النطاق والهدف

طلبت الجولة مراجعة كل الأقسام والوظائف والعمليات الموجودة فعلياً في Guardian Bot، مع تطوير ما يثبت التحليل حاجته. التزمت المراجعة بجرد كامل للمستودع ومسارات التسجيل والتخزين والاختبارات، ثم طبقت سياسة المشروع التي تمنع تنفيذ تغييرات واسعة غير قابلة للتحقق في جولة واحدة. لذلك نُفذ أعلى gap موثق فقط، ووُثقت بقية الأولويات بدلاً من اختراع ميزات أو الادعاء بإكمال كل قسم.

## مراحل التنفيذ

| المرحلة | النتيجة المقبولة |
|---|---|
| الجرد وbaseline | خريطة فعلية للأقسام والملفات ومسارات lifecycle و249 اختباراً ناجحاً قبل التعديل |
| تحليل الفجوات | تحديد config drift بين `group_settings.warn_limit` و`smart_warn.warnlimit:{chat_id}` مع دليل من الكود والاختبارات |
| التنفيذ | جعل smart_warn يستخدم manager canonical، مع lazy migration للمفتاح القديم وحذفه بعد الترحيل |
| الاختبارات | نجاح default وcustom round-trip وlegacy migration وinvalid legacy وreset وvalidation failure، ثم suite كاملة |
| الجودة | نجاح compileall وpip check وpip-audit وRuff المحدد |
| التسليم | تقرير شامل يوضح جميع الأقسام، التغيير المنفذ، وأولويات العمل المتبقية مع حدود البيئة |

## قرار معماري

يبقى `src/management/group_settings.py` المصدر الوحيد لإعدادات المجموعة. يقرأ `smart_warn` قيمة `warn_limit` منه، ويكتبها عبر `set_setting`. عند غياب القيمة canonical، يبحث manager مرة واحدة عن مفتاح `warnlimit:{chat_id}` القديم، يتحقق من المجال 1–10، ينقل القيمة إلى hash، ثم يحذف المفتاح القديم. القيم القديمة غير الصالحة تُهمل ويُستخدم default 5. إعادة ضبط الإعدادات تحذف canonical والlegacy معاً حتى لا تعود قيمة قديمة بعد reset.

## أولويات لاحقة موثقة

أولوية لاحقة هي جعل إضافة warn history ذرية أو محمية بقفل Redis، لأن `add_warn` يقرأ ثم يكتب JSON history وقد يفقد تحديثاً عند وصول رسالتين متزامنتين. كما أن `raid_detector.check_raid` ما زال يحتاج reservation ذرياً قبل `_activate_lockdown` لمنع تكرار lockdown عند concurrent joins. وتبقى اختبارات Telegram/PostgreSQL/Celery/providers الحية خارج البيئة الحالية.

## المراجع

[1]: https://redis.io/docs/latest/commands/hset/ "Redis HSET"
[2]: https://redis.io/docs/latest/commands/hget/ "Redis HGET"
