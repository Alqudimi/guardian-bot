# Guardian Admin Console — خريطة التنفيذ والحالة

## الخريطة التشغيلية

```text
Manus OAuth user
  -> tRPC protected / role / group-scope guard
  -> Admin database: operator profile, grants, audit, health, alert, schedule records
  -> server-only Guardian Control Gateway client (HTTPS + shared secret)
  -> Guardian Bot gateway: allowlist + get_chat_member + bot-rights verification
  -> canonical manager / Redis / PostgreSQL / Telegram mutation
  -> verified response -> admin audit + health/alert records -> UI
```

لا يستطيع المتصفح تجاوز backend أو إرسال shared gateway token. لا تعتمد الواجهة على وجود environment variable وحده لإظهار `AVAILABLE`؛ تعتمد فقط على نتيجة probe أو نتيجة البوابة.

## ما نُفّذ

| المجال | التنفيذ الحالي | حماية وحالة حقيقية |
|---|---|---|
| الهوية | Manus OAuth، أدوار `owner/admin/operator/analyst/user`، operator profile وgroup access grants | حراسة tRPC خادمية وowner-only لتعديل الربط والمنح |
| البوابة | `AdminGateway` اختياري داخل lifecycle البوت | معطل افتراضياً، bind محلي، token قوي، ولا تشغيل بلا إعداد صريح |
| التشغيل | `/v1/status` يفحص Telegram وRedis وSQL `SELECT 1` | Celery وDocker يظهران `DISABLED` إلى أن يضاف probe حقيقي |
| المجموعات | قائمة DB وsettings canonical | القراءة/الكتابة تتطلب scope وربط Telegram operator و`get_chat_member` |
| المحتوى | group patterns وvalidation وcache invalidation والتقارير | لا manager موازٍ، والـregex يخضع للـcompile validation |
| moderation | events من `ModerationEvent` وmember mutations المحددة | mutation محروس بصلاحية operator وbot rights ونتيجة Telegram |
| التدقيق | جدول audit خادمي لكل mutation موصول | outcome لا يعلن النجاح قبل response البوابة |
| التنبيه | health rows وdeduplicated system alerts وتنبيه owner عند نشوء إنذار جديد | فشل تنبيه المالك لا يلغي السجل التشغيلي الدائم |
| الجدولة | handler محروس في `/api/scheduled/readiness` وسجل run يستعمل task UID | لا توجد مهمة Heartbeat منشأة قبل النشر؛ هذا مقصود |

## ما بقي غير متاح عمداً

| المجال | السبب | سلوك اللوحة |
|---|---|---|
| Telegram live/staging | لا يوجد token أو مجموعة staging معتمدان لهذه اللوحة | لا تنفذ mutations ولا تعرض نجاحاً |
| Gateway HTTPS | لا يوجد `GUARDIAN_GATEWAY_URL` و`GUARDIAN_GATEWAY_TOKEN` كأسرار مشروع | تظل الحالة غير متاحة ويظهر runbook |
| Celery probe | worker endpoint أو health contract غير متاحين للبوابة | `DISABLED` بدلاً من تخمين حالة worker |
| Docker probe | لا يوجد runtime endpoint آمن | `DISABLED` |
| payments/voice/fulfillment | provider/executor موثق غير مهيأ | capability boundary وfail-closed |
| Mafia scoring | لا يوجد scoring contract فعلي | لا يتم إنشاء scoreboard وهمي |
| Heartbeat live | يتطلب checkpoint ونشر عنوان production قبل إنشاء schedule | handler والاختبارات جاهزة، والمهمة غير منشأة |

## مسار activation الآمن

تبدأ عملية التفعيل بتهيئة البوابة في بيئة البوت وفق `control-gateway-deployment.md`، ثم حفظ عنوان HTTPS والسر عبر الأسرار الخادمية للوحة. يلي ذلك فحص status، ربط operator grants، قراءة إعدادات مجموعة staging، ثم تعديل قابل للتراجع مع مراجعة Redis canonical وسجل التدقيق. بعد حفظ checkpoint ونشر لوحة الإدارة فقط، تُنشأ مهمة Heartbeat وتُحفظ `taskUid` داخل `scheduled_jobs`.

## التحقق الحالي

تغطي اختبارات لوحة الإدارة الحراسة الدورّية، فشل البوابة fail-closed، router للمجموعات والـpatterns والـmoderation، readiness/notification dedup، وscheduled callback. تغطي اختبارات Guardian Bot إعدادات البوابة وتنقية الأسرار ومعرفات supergroup السالبة. يُشغّل التكامل الحي فقط عندما تتاح credentials ومجموعة staging حقيقية.

## مراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/v22.8/ "python-telegram-bot v22.8"
[3]: https://docs.celeryq.dev/en/stable/ "Celery documentation"
