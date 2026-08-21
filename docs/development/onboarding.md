# دليل انضمام المطور

## أين يبدأ الطلب؟

نقطة التشغيل `main.py`. تسجيل handlers في `src/handlers/message_handler.py`. منسق moderation في `src/pipeline/orchestrator.py`. التخزين في `src/db/`، وإعدادات المجموعة في `src/management/group_settings.py`، والألعاب في `src/games/`.

## نمط التغيير

ابدأ بفهم owner الحالي قبل إضافة ملف. إذا كان manager قائماً، عدله بدلاً من إنشاء storage موازٍ. تتبع المسار من handler إلى service/layer ثم Redis أو PostgreSQL أو provider، ثم إلى نتيجة Telegram والتدقيق.

## conventions

يستخدم المشروع Python async/await، أسماء ملفات snake_case، وpytest مع fixtures async. الأخطاء الداخلية تسجل داخلياً، ورسائل المستخدم عامة. lifecycle للمهام الطويلة يمر عبر registry. أي تغيير في callback يحتاج ownership وchat checks.

## أول مهمة آمنة

شغل suite الحالية، اختر gap صغيراً قابلاً للإثبات، أضف positive/negative/failure tests، ثم نفذ suite كاملة. لا تعلن وظيفة حية دون credential/service حقيقيين.
