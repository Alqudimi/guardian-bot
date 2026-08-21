# تحليل الجولة السادسة: الوظائف والعمليات الفعلية

## نطاق الفحص

تم تتبع نقطة التشغيل `main.py`، وتجميع handlers، وسجل الميزات، ومسار رسائل المجموعات داخل `run_pipeline`، وRedis وSQLAlchemy، ومسار CAPTCHA والـ raid، والألعاب، والمتجر، ومشغل الصوت، وCelery، والتقارير، والاختبارات. الهدف كان التمييز بين الوظيفة الموجودة في الملفات والوظيفة التي تُستدعى فعلياً أثناء دورة تشغيل البوت.

## المسارات الموصولة فعلياً

رسائل المجموعات تمر عبر `handle_message` ثم `run_pipeline`، الذي ينفذ DoS pre-check، تسجيل النشاط، cross-group intake، التطبيع، fast rules، flood وbehavioral بالتوازي، account intelligence، evasion، near-duplicate وlink وmedia وanti-forward بالتوازي، language guard، AI عند السماح بالموارد، risk scoring، decision، action execution، ثم audit/modlog/statistics. أحداث انضمام الأعضاء تمر عبر `handle_new_member` إلى account intelligence وraid detection وCAPTCHA أو welcome. الأوامر والـ callbacks الأساسية والميزات الاختيارية والمتجر والألعاب مسجلة في Application فعلياً.

## الفجوات التشغيلية المثبتة

| الأولوية | الفجوة | الأثر الفعلي | الدليل |
|---|---|---|---|
| عالية | `start_voice_backend()` موجودة ولا يوجد caller في مسار startup | أوامر الموسيقى قد تدير queue فقط ولا تبدأ Pyrogram/PyTgCalls، وبالتالي لا يكون التشغيل الصوتي الحقيقي مفعلاً | `src/features/voice_chat.py:119` وغياب caller في `src` |
| عالية | raid lockdown يضع Redis TTL خمس دقائق لكن لا توجد آلية تستدعي `release_lockdown` عند انتهاء TTL | قد تبقى slow mode وصلاحيات المجموعة مقيدة بعد انتهاء مفتاح Redis | `src/pipeline/raid_detector.py:54-56` مع عدم وجود scheduler/caller تلقائي |
| متوسطة | التقارير تعلن raids وtop offenders وcircuit trips لكن `generate_report` لا يملأها | `/report` يعطي جزءاً من الصورة ولا يطابق العقد الموثق | `src/management/reports.py:41-54` و`82-134` |
| متوسطة | Celery tasks معرفة، وbeat يعرّف trust recalculation، لكن لا توجد enqueue calls من مسار link/audit ولا توثيق تشغيلي واضح للعامل المنفصل | تحديث domain reputation المؤجل وbatch logging غير داخلين في دورة البوت الحالية | `src/tasks/moderation_tasks.py` وغياب `delay/apply_async` في `src` |
| منخفضة | `_safe` يسجل فشل طبقة ويستمر بالقيم الافتراضية | يزيد الاعتمادية، لكنه قد يخفض detection إلى allow إذا فشلت طبقة دون signal fail-closed | `src/pipeline/orchestrator.py:208-232` وdefaults في `PipelineContext` |

## نطاق التنفيذ المختار

سيتم تنفيذ ثلاث تحسينات عملية قابلة للاختبار في هذه الجولة: تشغيل وإيقاف voice backend ضمن lifecycle مع degradation آمن عند غياب إعداداته، إضافة auto-release حقيقي لـraid lockdown مع تنظيف مهام المؤقت عند shutdown، وإكمال تقارير المجموعة بمؤشرات raids وtop offenders التي تُكتب من المسارات الفعلية. سيُوثق Celery كعملية منفصلة تتطلب worker/beat، ولن تُربط عشوائياً بمسار الإشراف قبل إضافة سياسة تشغيل وretry ومراقبة واضحة.

أما `_safe` فسيُضاف له اختبار/توثيق في هذه الجولة إن أمكن، لكن لن يُحوّل بالكامل إلى fail-closed دون تحليل كل طبقة حتى لا يؤدي فشل خدمة اختيارية مثل AI إلى حظر جماعي غير مبرر.

## قيود الفحص

الاختبارات المحلية لا تتصل بـTelegram Bot API حي ولا توفر Pyrogram session أو مجموعة اختبار حقيقية. يمكن اختبار lifecycle wiring، Redis keys، المؤقتات، التقارير، وقرار التدهور محلياً؛ أما الانضمام الصوتي الفعلي، صلاحيات Telegram، وتسليم رسائل المجموعة فتحتاج بيئة خارجية مخصصة.
