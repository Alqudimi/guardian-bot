# تشغيل وربط Guardian Bot Control Gateway

## النتيجة المطلوبة

تتصل لوحة الإدارة ببوابة التحكم عبر HTTPS من backend فقط. لا يستطيع browser الوصول إلى token Telegram أو Redis أو PostgreSQL البوت أو shared gateway token.

## تهيئة Guardian Bot

تظل البوابة معطلة افتراضياً. تُفعل فقط في بيئة bot المقصودة، مع سر قوي مستقل وعدم حفظه في Git:

```env
ADMIN_GATEWAY_ENABLED=true
ADMIN_GATEWAY_HOST=127.0.0.1
ADMIN_GATEWAY_PORT=8765
ADMIN_GATEWAY_TOKEN=<32-256-char-url-safe-secret>
```

يبقى bind محلياً. يجب أن يقدمه reverse proxy موثوق عبر HTTPS على hostname مستقل، مع حظر الوصول العام إلا من خدمة لوحة الإدارة أو شبكة خاصة. لا يوضع token في URL أو frontend أو logs.

## تهيئة لوحة الإدارة

بعد وجود endpoint HTTPS فعلي وفحصه، يضاف سران للخادم عبر إدارة الأسرار فقط:

| المتغير | المعنى | لا يستخدم في browser |
|---|---|---|
| `GUARDIAN_GATEWAY_URL` | عنوان HTTPS لبوابة البوت، بلا slash أخير | نعم |
| `GUARDIAN_GATEWAY_TOKEN` | القيمة المطابقة لـ`ADMIN_GATEWAY_TOKEN` | نعم |

تسجل اللوحة العنوان فقط في connection record؛ لا تسجل token. يُنفذ owner بعدها `تسجيل الاتصال من الأسرار` ثم `فحص البوابة الآن`. إذا لم يرجع `/v1/status` envelope صالحاً، تبقى كل عمليات Telegram معطلة.

## تسلسل الاختبار

أولاً، اختبر `/v1/status` من خادم اللوحة فقط. ثانياً، أضف grant محدوداً لمشغل وحساب Telegram موثق. ثالثاً، اختبر قراءة إعدادات مجموعة staging. رابعاً، نفذ تعديل إعداد قابل للتراجع وتحقق من Redis canonical وسجل التدقيق. خامساً، اختبر Telegram mutation في staging مع bot rights مؤكدة، ثم تحقق أن Telegram أكد العملية قبل عرض النجاح.

## الحدود

البوابة لا تثبت قدرة Telegram لمجرد وجود token. كل عملية على مجموعة تتحقق من أن operator موجود في `TELEGRAM_ADMIN_IDS` ومن status الحالي في `get_chat_member`، ثم تتحقق من أن bot يملك `can_restrict_members` عندما يتطلب الإجراء ذلك. تظل Celery وDocker في حالة `DISABLED` إلى أن تضاف probes مخصوصة لها؛ لا يتحولان إلى `AVAILABLE` اعتماداً على إعدادات أو سجلات قديمة.

## الجدولة والتنبيهات

handler readiness موجود على `/api/scheduled/readiness`، لكنه لا يُجدول قبل نشر لوحة الإدارة. بعد النشر تنشأ مهمة Heartbeat باسم ثابت، تحفظ `taskUid` في `scheduled_jobs`، وتبحث callback عن المهمة بالـtask UID فقط. يستجيب handler بتفاصيل JSON عند الفشل لكي تظهر في التحقيق التشغيلي، وهو idempotent أمام تكرار callback.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.aiohttp.org/en/stable/web.html "aiohttp web server"
