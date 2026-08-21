# دليل الاستجابة التشغيلية

## لا يستجيب bot

تحقق من process وlogs و`TELEGRAM_BOT_TOKEN` وRedis وPostgreSQL. إذا كان webhook مضبوطاً، لا تشغل polling قبل فحص `getWebhookInfo`؛ الطريقتان متنافيتان. افحص آخر migration قبل إعادة التشغيل.

## ارتفاع الحذف أو الحظر

فعّل `DRY_RUN` أو عطّل feature المجموعة من الإعداد canonical، ثم راجع moderation events وthresholds وaction rate. لا ترفع limits لمجرد إسكات التنبيهات. افحص false positives وإشارات high-confidence.

## raid lockdown عالق

تحقق من Redis reservation وactive marker ثم Telegram permissions. لا تمسح marker قبل تنفيذ Telegram release بنجاح. إذا فشل release، نفذ المسار الإداري الموثق وسجل أن الاستعادة best-effort ولا تعيد permissions تاريخية مجهولة.

## Celery متوقف

تحقق من Redis broker، worker ping، beat schedule، ووجود task exception. أعد task idempotently فقط. لا ترسل retries بلا backoff ولا تنشئ event loop دائمًا مشتركاً مع AsyncEngine.

## فشل migration

أوقف bot، خذ نسخة احتياطية أو snapshot، اقرأ revision الحالية، ثم نفذ migration من بيئة تملك نفس dependencies. لا تستخدم `AUTO_CREATE_TABLES=true` كحل staging/production.

## حادث secret

اتبع [`../security/operations.md`](../security/operations.md). لا تلصق token في issue أو chat أو التقرير.

## ما يجب تسجيله بعد الحادث

سجل وقت الحادث، البيئة، الإصدار، الأثر، الإجراء الفعلي، نتيجة التحقق، وقرار المتابعة. احذف القيم السرية والبيانات غير الضرورية.
