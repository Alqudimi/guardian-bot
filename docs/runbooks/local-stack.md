# Runbook المكدس المحلي

## تشغيل الخدمات

```bash
docker compose up -d postgres redis
redis-cli ping
pg_isready -h 127.0.0.1 -p 5432
alembic upgrade head
```

شغل Celery worker وbeat من البيئة الافتراضية، ثم تحقق من logs وtask smoke. بعد ذلك شغل bot أو الاختبارات.

## تحقق readiness

| المكون | دليل الجاهزية |
|---|---|
| PostgreSQL | `pg_isready` و`alembic current` |
| Redis | `redis-cli ping` وnamespace اختبار |
| Celery worker | worker ping أو task نتيجة حقيقية |
| Celery beat | process وschedule logs |
| bot image | `docker run` أو Compose health/runtime smoke |

## الإيقاف

```bash
docker compose down
```

احتفظ بالـvolume إذا كانت البيانات مطلوبة. نظف test keys وCelery results بعد التحقق.

## الأدلة التاريخية

سجلات الجولة 22 في `tasks/round22-local-services-readiness.txt` و`tasks/round22-celery-fixed-smoke-1.txt` و`tasks/round22-docker-runtime-final.txt` تثبت التشغيل المحلي في وقتها فقط.
