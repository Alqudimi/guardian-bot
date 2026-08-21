# تحليل الجولة الثامنة: مراجعة شاملة للأقسام والوظائف

## قاعدة التحليل

تم بناء هذا التحليل من الجرد الفعلي للمشروع، وليس من أسماء متوقعة أو تصميم افتراضي. نقطة الدخول هي `main.py`، حيث يُبنى `Application` ويُربط `post_init` و`post_shutdown` ثم تُسجل منظومة handlers. الحماية الجماعية تمر عبر `run_pipeline`، والمتجر يسجل نفسه عبر `register_shop_handlers`، والميزات الاختيارية والألعاب تسجل عبر `register_all_features`. كل قرار أدناه يميز بين وظيفة موصولة فعلياً، ووظيفة موجودة لكنها محدودة، ووظيفة تحتاج تكاملاً خارجياً لا يجوز ادعاء وجوده.

## مصفوفة الأقسام الفعلية

| القسم | المسارات الموصولة فعلياً | فجوات أو فرص مثبتة | الأولوية | قرار الجولة |
|---|---|---|---|---|
| التشغيل وlifecycle | polling/webhook، DB/Redis startup/shutdown، voice lifecycle | لا يوجد health/readiness command أو فحص تشغيلي موحد للمشرف، وبعض أخطاء optional features تُسجل فقط | عالية | تحسين status/diagnostics ووضوح degradation دون تغيير نمط التشغيل |
| حماية المجموعات وpipeline | 17-layer pipeline مع DoS، normalization، rules، flood، behavior، intelligence، risk، decision، execution، audit | `_safe` يعزل فشل الطبقة، لكن بعض الإخفاقات قد تبدو كـallow؛ تحتاج observability وfail policy لكل layer، كما يجب اختبار الترتيب والshort-circuit | عالية | تدقيق قرارات fallback والـmetrics وإضافة اختبارات ترتيب/فشل |
| أوامر الإدارة | rules، welcome، modlog، language، captcha، warns، mute/ban/kick، patterns، reports، safe mode | يحتاج توحيد authorization/validation ورسائل الفشل، ومراجعة أن كل أمر يقرأ ويكتب نفس إعدادات المجموعة | عالية | مراجعة مسارات الإدارة والصلاحيات والحالات الحدية |
| games | Mafia وChameleon داخل البوت مع Redis sessions وcallbacks/DM | يحتاج توسيع اختبارات restart/expiry/unauthorized callback، مع إبقاء الألعاب الداخلية فقط | متوسطة | تقوية lifecycle والـsecurity دون إضافة لعبة شكلية |
| الميزات الدينية | azkar، quran، quotes، جداول JobQueue وfallback محلي لبعض المصادر | بعض API/fallback paths تحتاج إظهار مصدر البيانات وفشل الجدولة، ومراجعة duplicate jobs وtimezone | متوسطة | اختبار جداول JobQueue وfallback والرسائل الفعلية |
| تنزيل الوسائط | yt-dlp وInstaloader ومسارات Telegram إرسال حقيقية بعد الإصلاح | تكاملات خارجية، limits، cleanup، timeouts، وrate limit تحتاج اختبار failure وfile cleanup | عالية | تحسين الحدود والتعامل مع فشل subprocess/API دون رسائل نجاح زائفة |
| voice chat | Pyrogram/PyTgCalls lifecycle وqueue وأوامر music/pause/resume/skip/stop | يحتاج backend credentials حقيقية؛ لا يجوز ادعاء تشغيل حي في البيئة الحالية | متوسطة | إبقاء fail-closed وإضافة readiness diagnostics فقط |
| المتجر والدفعات | catalog، profiles، coupons، orders، wallet، Telegram Payments، support، referrals، admin dashboard | instant fulfillment غير موصول، بعض workflows الإدارية/manual، ويجب مراجعة state consistency والـidempotency | عالية | تحسين state transitions والـfinancial invariants، وعدم بناء executor وهمي |
| referrals/analytics | commissions، referral stats، recommendations، fraud/revenue insights محلياً | التوقيت والارتباط بين أول شراء وcommission يحتاج assertions، والتوصيات غير معروضة بشكل كامل في UI | متوسطة | ربط الوظائف الموجودة ذات القيمة قبل إضافة نظام جديد |
| intelligence | adaptive thresholds وcross-group intelligence | يحتاج اختبار lifecycle للـthresholds وattribution ومنع التلوث بين المجموعات | متوسطة | إضافة عزل واختبارات cross-group |
| security cross-cutting | API sentinel، circuit breaker، SSRF، input sanitizer، token guard، webhook hardening، anti-ban، DoS | تجميع status موحد، والتأكد أن كل outbound operation يسجل success/failure، ومراجعة fail-open layer policy | عالية | تحسين diagnostics واختبارات regression دون تغيير سياسة الحماية عشوائياً |
| background tasks | Celery worker/beat وثلاثة moderation tasks وجدولة trust scores | tasks محدودة ولا توجد enqueue paths واسعة من hot path؛ لا ينبغي ربطها عشوائياً | متوسطة | توثيق topology، اختبار task transaction semantics، وربط آمن فقط إذا ثبتت الحاجة |
| persistence/migrations | SQLAlchemy async، SQLite tests، PostgreSQL target، Alembic baseline، Redis | يحتاج consistency checks، indexes/constraints مراجعة، واختبارات migration upgrade/downgrade العملية | عالية | مراجعة transaction boundaries وschema/runtime parity |
| الاختبارات | 182 اختباراً ناجحاً سابقاً، تغطية security/games/management/operations/shop | تغطية بعض handlers وexternal failures وfull Application wiring محدودة، ولا يوجد Telegram live environment | عالية | إضافة اختبارات integration محلية حقيقية، مع فصل ما يتطلب credentials |

## علاقات التشغيل الحرجة

يمر تحديث المجموعة من `message_handler.handle_message` إلى `run_pipeline` قبل أن تتدخل بعض feature handlers بحسب groups في Application. قرار `run_decision_engine` لا يغير Telegram مباشرة؛ التنفيذ يتم في `action_execution` مع API Sentinel وCircuit Breaker، ثم تسجل audit/modlog/stats. لذلك أي تغيير في layer منفردة يجب أن يحافظ على عقد `PipelineContext` ولا يرسل رسالة أو إجراءً خارج action boundary.

المتجر منفصل عن moderation pipeline لكنه يشترك في Application وDB وRedis. `/shop` يفتح الواجهة، callback router يوزع namespace، private-message router يتعامل مع search/coupon/custom deposit/support، وpayment handlers تتعامل مع pre-checkout وsuccessful payment. أي توسعة مالية يجب أن تظل داخل transaction boundaries ولا تستخدم `deposit` أو status mutation كبديل عن provider event.

الميزات الخارجية مثل yt-dlp وInstagram وvoice لا تُعد مكتملة بمجرد وجود handler. التنفيذ الحقيقي يتطلب subprocess أو backend/API واستقبال النتيجة، cleanup، ورسالة فشل صادقة. الألعاب بخلاف ذلك داخلية بالكامل ويجب أن تبقى persistence وauthorization وexpiry جزءاً من الاختبار.

## الأولويات التنفيذية المقترحة

الأولوية الأولى هي **سلامة العمليات**: التحقق من authorization، state transitions، transaction boundaries، وfail behavior في pipeline والمتجر والـcallbacks. الأولوية الثانية هي **observability**: status قابل للاستخدام، metrics مصدرها أحداث فعلية، وسبب واضح لأي feature غير مهيأة. الأولوية الثالثة هي **التكاملات الخارجية**: timeouts وcleanup وrate limits ومسارات failure الحقيقية. بعد ذلك تأتي توسعات عالية القيمة مثل تحسين التقارير والتوصيات والاختبارات التشغيلية، ولا تُضاف ميزات مستقلة بلا حاجة مثبتة.

## قرارات عدم التنفيذ

لن يتم إنشاء ميزات شكلية لـCelery أو instant fulfillment أو voice backend أو دفع حي دون credentials/provider/executor حقيقي. كما لن تُضاف لعبة جديدة أو API خارجي لمجرد زيادة عدد الملفات. أي قسم لا يملك تكاملاً خارجياً جاهزاً سيحصل على fail-closed وdiagnostics وتوثيق واضح بدلاً من محاكاة.
