# مصفوفة توفر القدرات

| القدرة | الحالة الحالية | الدليل أو المصدر | اعتماد مطلوب | قابلة للإدارة من اللوحة الآن |
|---|---|---|---|---|
| قراءة إعدادات المجموعة canonical | موجودة في البوت | `group_settings.get_all_settings` | Redis وبوابة التحكم | لا، حتى تشغيل البوابة |
| كتابة إعدادات المجموعة canonical | موجودة في البوت | `group_settings.set_setting` | Redis وoperator scope وبوابة التحكم | لا، حتى تشغيل البوابة |
| moderation event browser | البيانات موجودة | `ModerationEvent` | PostgreSQL وبوابة التحكم | لا، حتى تشغيل البوابة |
| member browser | البيانات موجودة جزئياً | `GroupMember` و`User` | PostgreSQL وبوابة التحكم | لا، حتى تشغيل البوابة |
| mute/ban/kick/unban/undo | موجودة في bot handlers | `admin_commands.py` | Telegram transport وbot rights وgroup authority | لا، لا تعرض كمتاحة قبل probe حي |
| whitelist/blacklist/warn reset | موجودة في bot | handlers/managers | Redis/DB حسب العملية وبوابة التحكم | لا، حتى تشغيل البوابة |
| group patterns | موجودة في bot | group pattern manager | Redis وvalidation وgateway | لا، حتى تشغيل البوابة |
| CAPTCHA/raid/anti-forward | موجودة في bot | canonical settings وpipeline | Redis وTelegram updates ذات الصلة | لا، حتى تشغيل البوابة |
| games sessions/scoreboards | موجودة | `GameSessionManager` | Redis وgateway | لا، حتى تشغيل البوابة |
| bot runtime status | probe محلي موجود | `/status` handler | bot runtime وبوابة التحكم | لا، حتى تشغيل البوابة |
| PostgreSQL health | قابل للفحص | bot startup/status | اتصال DB | لا، تظهر غير متصلة إلى أن تصل البوابة |
| Redis health | قابل للفحص | bot startup/status | اتصال Redis | لا، تظهر غير متصلة إلى أن تصل البوابة |
| Celery health | قابل للفحص جزئياً | worker/broker lifecycle | Redis broker وworker حقيقيان | لا، لا تفترض worker من configuration |
| Docker health | محلي فقط | Round 22 runtime smoke | Docker daemon أو remote probe | لا، ليس control-plane source افتراضياً |
| payments | fail-closed | provider token/payment flow | provider token وTelegram payment | لا، يعرض disabled عند غياب provider |
| instant fulfillment | معطل عمداً | project constraints | executor/provider موثق | لا، لا ينشأ زر تنفيذ |
| Mafia scoring | فارغ عمداً | game scoring contract | contract واختبارات | لا، لا تعرض نقاطاً |
| readiness schedules | لم تنفذ بعد | لا يوجد job حالي | scheduled handler منشور وtask UID | لا، ينفذ في مرحلة الجدولة |
| owner alerts | helper الويب متاح | `notifyOwner` | خدمة الإشعارات المدمجة ونتيجة true | لا، ينفذ في مرحلة التنبيهات |

## قواعد العرض

تستخدم الواجهة الحالات `AVAILABLE` و`DEGRADED` و`UNAVAILABLE` و`DISABLED`. قيمة `AVAILABLE` لا تُعرض إلا إذا أعاد probe حقيقي نتيجة صالحة ضمن مهلة محددة. لا تستخدم `configured` مرادفاً لـ`available`، ولا تُشتق حالة من sample data أو env presence وحدها.

## مسار الترقية

لتحويل صف من غير متصل إلى متاح: تُنفذ بوابة التحكم في البوت، ثم يضاف URL وsecret في server-side secrets للوحة، ثم يجرى probe حقيقي، ثم يختبر read path، ثم mutation مقيّد في staging مع audit. لا تقفز الواجهة مباشرة إلى mutation.
