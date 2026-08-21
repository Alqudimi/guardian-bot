# خطة تنفيذ الجولة العاشرة — Guardian Bot

## النطاق

تستهدف الجولة مراجعة شاملة للأقسام الموجودة فعلياً مع تنفيذ أعلى التحسينات قيمة وقابلية للتحقق، لا إضافة وظائف عشوائية. baseline الحالي هو 198 اختباراً ناجحاً، و`compileall` و`pip check` و`pip-audit` ناجحة.

## الجرد الفعلي

| المجال | مكونات موجودة فعلياً | ملاحظة الجولة |
|---|---|---|
| Moderation pipeline | orchestrator و17 layer تقريباً، action execution، audit، raid، reports | الأساس قوي من الجولة التاسعة؛ يراجع فقط ما يتصل بالمعاملات والحالات الفاشلة |
| Group management | settings، rules، welcome، modlog، reports، admin commands | توجد tasks حذف/إشعارات غير مركزية وبعض callbacks تحتاج تحققاً |
| Games | GameManager/Session، Mafia، Chameleon | يراجع lifecycle والـsession persistence، مع الحفاظ على الألعاب الداخلية |
| Shop | catalog/pricing، orders، wallet/payments، coupons، referrals، support، notifications | أعلى فجوة مؤكدة: create_order يثق في unit_price من user_data، وrefund لا يفرض ملكية المستخدم، وسجل coupon usage غير مربوط بإنشاء الطلب |
| Features | Azkar، Quran، quotes، media/Instagram/SoundCloud، smart detect، voice chat، rate limiting | توجد background tasks مباشرة وfallbacks خارجية؛ يراجع fail-closed والـtask lifecycle دون اختراع provider |
| Security | sanitizer، SSRF guard، human behavior، webhook hardening | يستكمل اختبار canonicalization وDNS/redirect وحالات الإدخال |
| Persistence/tasks | SQLAlchemy async، Redis، Alembic، Celery | يراجع حدود AsyncSession وعدم مشاركة state، ويترك أي تكامل حي غير متاح كقيد موثق |

## الأولويات التنفيذية

### Task 1 — سلامة الطلب والسعر والكوبون

**القبول:** يعيد `create_order` جلب الخدمات من قاعدة البيانات ويستخدم السعر المحسوب من server-side، ويتحقق من active/stock/min/max/VIP/required level، ولا يثق بسعر أو كمية من `user_data`. يُسجل استعمال الكوبون في المعاملة نفسها وبحدود المستخدم والخدمات والوقت، وتوجد اختبارات لسعر قديم وكوبون غير صالح وفشل المعاملة.

**التحقق:** اختبارات focused ثم suite كاملة وcompileall.

### Task 2 — ملكية واستقرار مسارات الطلب

**القبول:** يفرض refund ownership وحالات الانتقال المسموح بها ويمنع تكرار refund أو الدفع المتوازي عبر `with_for_update`، وتتعامل callbacks مع malformed IDs دون 500. يرسل مسار الفشل إشعاراً للمستخدم فقط بعد نجاح تغيير الحالة.

**التحقق:** اختبارات authorization وidempotency وinvalid callback.

### Checkpoint A

يجب أن تبقى suite كاملة ناجحة، وأن تثبت اختبارات المتجر الجديدة invariants الرصيد والطلب والكوبون.

### Task 3 — إدارة background tasks في الميزات والمجموعة

**القبول:** لا تُنشأ tasks طويلة العمر دون registry/cleanup أو callback logging، وتُحفظ tasks اللازمة للحذف/التنزيل/الاستجابة التلقائية مع إلغاء آمن عند shutdown أو الفشل. لا يتحول فشل إشعار ثانوي إلى نجاح كاذب.

**التحقق:** اختبارات lifecycle وcancellation وexception isolation.

### Task 4 — تدقيق الأمن والتكاملات القائمة

**القبول:** تغطي الاختبارات input sanitizer وSSRF redirect/DNS/canonicalization وcallbacks العابرة للسياق، مع إصلاح ما يثبت أنه خلل حقيقي فقط. لا تُضاف dependency جديدة دون حاجة.

**التحقق:** security tests وsuite كاملة، مع توثيق أي تكامل خارجي لم يُختبر حياً.

### Checkpoint B

compileall وpytest مع `-W error` وpip checks وruff على الملفات المعدلة.

### Task 5 — التوثيق والتقرير والأرشيف

يُحدّث README وAGENT وtodo، ويُكتب تقرير الجولة العاشرة بالمكونات التي روجعت، التغييرات، الاختبارات، القيود المتبقية، وSHA-256 للأرشيف.

## المخاطر والقيود

| الخطر | الأثر | المعالجة |
|---|---|---|
| تغيّر السعر بين العرض والتأكيد | خصم/تحصيل غير صحيح | إعادة التسعير والتحقق داخل transaction عند إنشاء الطلب |
| سباق دفع أو refund | تضاعف خصم/رد الرصيد | row lock وحالات انتقال صريحة واختبارات idempotency |
| Tasks غير مُدارة | تسريب موارد أو رسائل مكررة | registry أو cleanup callback مع logging |
| غياب Telegram/مزودات حية | لا يمكن إثبات external side effects | اختبار fail-closed وتوثيق الحاجة إلى credentials/بيئة حقيقية |
| اتساع النطاق | تغييرات كثيرة غير قابلة للمراجعة | تنفيذ vertical slices عالية القيمة والتوقف عند اكتمال معيار الجودة |
