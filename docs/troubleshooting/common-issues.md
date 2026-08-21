# استكشاف الأعطال

| العرض | الفحص الأول | الإجراء |
|---|---|---|
| `ModuleNotFoundError` | `PYTHONPATH` وvirtualenv | فعّل `.venv` وثبت requirements |
| فشل startup بسبب schema | `alembic current` و`alembic upgrade head` | أصلح migration قبل تشغيل bot |
| Redis unavailable | `redis-cli ping` و`REDIS_URL` | أصلح الاتصال؛ الوظائف التي تعتمد عليه قد تعمل degraded |
| bot لا يرى أعضاء المجموعة | Bot API permissions و`allowed_updates` | اجعل bot administrator وفعّل `chat_member` عند الحاجة |
| `/undo` لا يعلن النجاح | Telegram unban/unrestrict فشل | راجع صلاحيات bot ولا تمسح event أو marker يدوياً |
| ردود smart مكررة | Redis prefix وcooldown TTL | تحقق من reservation الذري وعدم وجود Redis namespace متضارب |
| Celery task يفشل ثانياً | worker logs وevent loop ownership | لا تعِد استخدام AsyncEngine عبر loops؛ راجع round22 fix |
| payment لا يزيد الرصيد | provider token أو successful_payment | هذا fail-closed مقصود؛ لا تعدل الرصيد يدوياً من callback |
| `/gamescores mafia` فارغ | scoring contract | هذا سلوك مقصود حتى إضافة عقد نقاط حقيقي |
| Docker build يفشل مساحة | `docker system df` | نظف artifacts غير المستخدمة بعد مراجعة volumes |

## جمع الأدلة

اجمع الإصدار، environment غير السري، آخر logs redacted، نتيجة `git rev-parse --short HEAD`، ونتائج الاختبارات. لا ترفق `.env` أو token أو payment payload أو dump أعضاء كامل.

## التصعيد

إذا كان الخلل يسبب false success أو mutation غير مقصودة، أوقف feature أو bot فوراً. إذا كان الخلل degraded في provider اختياري، وثق السبب واترك moderation الأساسي يعمل.
