# البيانات ودورة الحياة

## Redis

Redis هو المصدر canonical للإعدادات per-group والـcooldowns والـdedup والـatomic reservations وgame sessions وdownload tokens القصيرة. كل key يستخدم `settings.redis_prefix`، وكل TTL موثق في owner الخاص به.

لا تستخدم `exists` ثم `set` المنفصلين لمسار تنافسي. استخدم `SET NX EX` أو Lua أو WATCH/MULTI/EXEC حسب نوع العملية. token smart interaction يربط بالـchat والـuser ويُستهلك عبر `getdel` لمرة واحدة؛ لا تضع raw URL في callback data.

## PostgreSQL

PostgreSQL هو التخزين الدائم للأحداث والملفات الشخصية وأعضاء المجموعة وحالات الإدارة والمتجر. تستخدم SQLAlchemy async، وتدار schema عبر Alembic. في production يجب تطبيق migration قبل startup وعدم إنشاء الجداول بصمت.

## Celery

Celery يعالج المهام الطويلة والدورية مثل إعادة حساب trust. يستخدم Redis broker، ويجب أن يكون كل task idempotent أمام redelivery، وأن يستخدم retry/backoff للخطأ القابل للإعادة. لا يرسل broker في hot path بلا degradation واضحة.

إصلاح الجولة 22 أنشأ event loop مناسباً لكل استدعاء task لتفادي إعادة استخدام AsyncEngine عبر loops مختلفة. يجب الاحتفاظ بهذا السلوك عند أي تعديل مستقبلي.

## background registry

المسارات طويلة العمر تمر عبر `src/utils/background_tasks.py` أو registry مماثل يحتفظ بالمرجع ويسجل الاستثناء ويدعم الإلغاء في shutdown. لا تستخدم `asyncio.create_task` خاماً لخدمة أو loop دائم.

## games

GameSessionManager هو المالك الوحيد لحالة Mafia وChameleon. أرشفة scoreboard تستخدم `BaseGame.get_scores()` و`persist_scores()`، وdistributed lock وtransaction وmarker وTTL. marker لا يثبت قبل نجاح scoreboard، والعملية idempotent عند stop المتكرر. يرفض `NaN` و`Infinity` والقيم غير المحدودة. Mafia scoreboard فارغ عمداً بلا scoring contract.

## lifecycle checklist

| المرحلة | تحقق |
|---|---|
| startup | config، Redis، DB، optional backends، migrations |
| runtime | handlers، pipeline، locks، action result، audit |
| background | registry، Celery retry، loop ownership |
| shutdown | إلغاء tasks، إغلاق clients، حفظ الموارد |
| recovery | إعادة تشغيل idempotent وعدم تكرار mutation أو scoreboard |

## مراجع

[1]: https://redis.io/docs/latest/develop/using-commands/transactions/ "Redis atomic transactions"
[2]: https://docs.celeryq.dev/en/stable/userguide/tasks.html "Celery tasks"
[3]: https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html "Celery periodic tasks"
[4]: https://alembic.sqlalchemy.org/en/latest/ "Alembic"
