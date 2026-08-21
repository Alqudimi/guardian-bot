# المساهمة

## قبل البدء

اقرأ `AGENT.md` وتعليمات المشروع الدائمة، ثم راجع `README.md` وملفات الجولة الأحدث في `tasks/`. لا تعِد كتابة المعمارية من الصفر ولا تضف dependency ثقيلة قبل إثبات الحاجة.

## دورة العمل

1. حدد gap قابل للإثبات وملف owner الحالي.
2. اكتب خطة صغيرة ومسار التنفيذ المتوقع.
3. نفذ أقل تغيير معماري مناسب.
4. أضف اختبار نجاح واختبار رفض واختبار فشل.
5. شغل بوابات التحقق كاملة.
6. حدّث التوثيق وسجل الحدود الواقعية.
7. راجع diff والأسرار والملفات المضافة قبل commit.

## قواعد مهمة

لا تستخدم user ID لاستنتاج account age أو maliciousness. لا تستخدم `exists` ثم `set` في race-sensitive path. لا تستخدم raw `asyncio.create_task` لمسار طويل. لا تسجل secrets أو arguments الحساسة. لا تسجل نجاح Telegram mutation قبل نجاح API. لا تضف لعبة أو provider أو instant fulfillment كـmock.

## نمط commit وpull request

استخدم رسائل commit وصفية، واجعل كل PR محدود النطاق. اشرح المشكلة، التغيير، الاختبارات، والوظائف التي لم تُختبر حياً. أرفق migration أو rollback notes عند تعديل schema. لا تخلط refactor واسعاً مع تغيير سلوكي حرج.

## مراجعة الأمان

أي أمر إداري أو callback أو payment path يحتاج مراجعة authorization وownership وfailure behavior وredaction. أي endpoint خارجي يحتاج timeout وretry محدوداً وidempotency وحالة degradation.
