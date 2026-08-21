# نظرة عامة على المعمارية

## النمط

Guardian Bot تطبيق Python async أحادي المستودع، لكنه مقسم إلى طبقات واضحة: Telegram handlers، pipeline moderation، management، games/features، persistence، وbackground tasks. هذا التقسيم يحافظ على حدود المسؤولية دون إدخال service mesh أو storage موازي غير ضروري.

## المكونات

| المكون | المالك | المسؤولية |
|---|---|---|
| `main.py` | startup/shutdown | إنشاء التطبيق، lifecycle، transport |
| `src/handlers/` | Telegram boundary | تحويل update إلى مسار domain والتحقق الأولي |
| `src/pipeline/` | moderation orchestrator | ترتيب الطبقات وحماية short-circuit |
| `src/layers/` | signal/action layers | استخراج الإشارات، القرار، التنفيذ، التدقيق |
| `src/management/` | group management | الإعدادات والأوامر الإدارية |
| `src/games/` | game domain | Mafia وChameleon وsessions |
| `src/db/` | persistence | SQLAlchemy async والنماذج والجلسات |
| Redis client | coordination/cache | settings، cooldown، dedup، locks، tokens، sessions |
| Celery | background | مهام طويلة أو دورية idempotent |
| PostgreSQL | durable state | moderation events، members، group state، shop state |

## مسار الرسالة

```text
Update
  -> message_handler
  -> authorization / chat-type validation
  -> PipelineContext
  -> normalization
  -> fast rules
  -> flood + behavior
  -> link + media + optional AI
  -> risk scoring
  -> decision engine
  -> action execution
  -> audit logging
  -> user/admin response
```

الطبقة اللاحقة لا تستبدل قراراً عالي الثقة. عند ضبط `ctx.short_circuit` و`decision.action`، يجب أن يحافظ orchestrator على القرار حتى نهاية التنفيذ والتدقيق.

## مصادر الحقيقة

| البيانات | المصدر canonical |
|---|---|
| إعدادات المجموعة | `src/management/group_settings.py` وRedis hash المسمى عبر `settings.redis_prefix` |
| warning limit | `group_settings.warn_limit` مع lazy migration للمفتاح القديم |
| anti-raid | group settings و`raid_detector.check_raid` |
| group patterns | manager المجموعة نفسه؛ لا manager موازٍ |
| moderation history | PostgreSQL `ModerationEvent` عند الحاجة، مع cache غير authoritative |
| game sessions | `GameSessionManager` |
| scoreboard | Redis sorted set بعد نجاح persistence وبـmarker idempotent |

## حدود التصميم

لا يستنتج النظام عمر الحساب من user ID أو username، ولا يعرض تاريخ إنشاء غير متاح عبر Bot API. لا يعتمد games على WebApp خارجية. لا يعرض provider أو payment أو instant fulfillment كأنه متاح ما لم يوجد executor وعقد اختبار حقيقي.

## startup وshutdown

يجب أن يبدأ التطبيق بقراءة الإعدادات والتحقق من dependencies، ثم يهيئ Redis وdatabase والـoptional backends. عند shutdown يغلق clients ويُلغي background registry ويوقف الموارد دون ترك tasks معلقة. فشل backend الاختياري يسجل degradation ويترك pipeline الأساسي متاحاً.

## مراجع

[1]: https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.application.html "python-telegram-bot Application"
[2]: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html "SQLAlchemy asyncio extension"
[3]: https://redis.io/docs/latest/develop/using-commands/transactions/ "Redis transactions and atomicity"
