# خطة الجولة الثانية والعشرون — التثبيت المحلي والتكاملات الحقيقية المتاحة

## الهدف

تثبيت وربط كل ما يمكن توفيره داخل البيئة الحالية دون credentials خارجية: PostgreSQL وRedis وCelery worker/beat وDocker/Compose، ثم اختبار مسارات التطبيق الحقيقية. تبقى Telegram live وproduction PostgreSQL والـproviders وstaging performance وinstant fulfillment وMafia scoring خارج التنفيذ عند غياب الوصول أو العقد.

## التنفيذ

| المكوّن | الإجراء |
|---|---|
| PostgreSQL staging | تثبيت PostgreSQL 16، إنشاء قاعدة ومستخدم محليين، وتشغيل Alembic إلى `head` |
| Redis | استخدام Redis المحلي الحقيقي في round-trip وCelery broker/result backend |
| Celery worker | تشغيل worker على Redis، وإرسال `recalculate_trust_scores` فعلياً واستلام النتيجة |
| Celery beat | تشغيل beat محلياً والتحقق من process وschedule |
| Docker | تثبيت Docker daemon، تثبيت Compose v2، بناء image، وتشغيل runtime smoke داخل الحاوية |
| Application runtime | إثبات SQLAlchemy async إلى PostgreSQL وRedis namespace من داخل التطبيق |
| Provider boundaries | تشغيل tests fail-closed للدفع والصوت والوسائط دون تفعيل provider غير موجود |
| Celery loop | إصلاح إعادة استخدام AsyncEngine بين مهام Celery عبر event loop ثابت لكل worker process |

## القبول

نجاح migration وruntime smoke وCelery ping/task smoke وDocker image build وDocker runtime smoke، ثم suite كاملة مع PostgreSQL وRedis و`-W error`، وcompileall وpip check وpip-audit وRuff correctness.
