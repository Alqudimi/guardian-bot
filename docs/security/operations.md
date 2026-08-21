# التشغيل الآمن

## الأسرار

أدر الأسرار خارج GitHub، واستخدم secret manager في الإنتاج. صلاحيات `.env` المحلية `600`. عند الاشتباه بتسريب token، أوقف bot ودوّر token من BotFather، ثم افحص logs وGit history وبيئة CI.

## الصلاحيات

امنح bot أقل صلاحيات Telegram اللازمة، مع تذكر أن حذف الرسائل والكتم والحظر وإدارة الأعضاء تحتاج صلاحيات مناسبة. administrator allowlist ليست بديلاً عن فحص رتبة المستخدم داخل chat.

## السجلات

سجل chat ID وuser ID عند الحاجة التشغيلية، لكن لا تسجل token أو password أو callback raw URL أو payment payload الحساس أو arguments الإدارية الحساسة. رسائل المستخدم عامة؛ التفاصيل تبقى في logs داخلية redacted.

## قاعدة البيانات

استخدم مستخدماً محدود الصلاحيات، migrations محكومة، backup مشفراً، وTLS عند الاتصال خارج localhost. اختبر restore دورياً؛ نجاح backup دون restore test ليس دليلاً كافياً.

## Redis

ضع Redis خلف شبكة موثوقة وpassword/ACL، واستخدم prefix مميز لكل بيئة. لا تعتبر Redis cache بديلاً عن PostgreSQL للأحداث الدائمة. امسح test keys بعد التكامل.

## الاستجابة لتسريب

1. أوقف النشر أو bot المتأثر.
2. دوّر credential من المصدر الخارجي.
3. ألغِ sessions وkeys قصيرة العمر.
4. افحص Git history وCI artifacts وlogs.
5. حدّث السر خارج المستودع واختبر startup في بيئة آمنة.
6. وثق الحادث دون نسخ السر في التقرير.
