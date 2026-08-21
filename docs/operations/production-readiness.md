# تقييم جاهزية الإنتاج

## تعريف الجاهزية

لا تعني عبارة production-ready أن كل providers متاحة. يجب تصنيف كل capability إلى implemented، locally verified، externally verified، أو intentionally disabled.

| capability | الحالة الحالية | ما يلزم للترقية |
|---|---|---|
| moderation pipeline | implemented ومختبر وحدياً | staging Telegram مع مجموعة مملوكة |
| PostgreSQL | local staging verified | production endpoint وTLS وbackup/restore |
| Redis | local verified | deployment عالي الاعتمادية وACL ومراقبة |
| Celery | local worker/beat verified | broker production، monitoring، redelivery drills |
| Telegram | غير مختبر live في البيئة المعزولة | token، group، admin permissions، allowed updates |
| payments | fail-closed | provider token، invoice flow، pre-checkout وpayment tests |
| instant fulfillment | disabled | executor/provider وعقد idempotency وتسليم مثبت |
| Mafia scoring | intentionally empty | scoring contract، migration، tests، product approval |
| AI models | optional degraded | model cache/egress/latency budget ومعايرة |

## بوابات الإطلاق

قبل الإطلاق، يجب نجاح compileall وpytest مع `-W error` وpip check وpip-audit وفحص Ruff للملفات المعدلة. بعد ذلك نفذ smoke على PostgreSQL وRedis وCelery، ثم Telegram staging محدوداً مع dry-run أولاً.

لا تُجرى mutations إنتاجية في أول تشغيل. ابدأ بمجموعة اختبار، ثم فعّل feature flags تدريجياً، وراقب action rate وTelegram errors وRedis latency وDB pool وfalse positives.

## rollback

احتفظ بإصدار image سابق وmigration plan قابل للتراجع. لا تنفذ downgrade قاعدة البيانات عشوائياً؛ افهم أثره على البيانات. عطّل feature ذات الخلل من canonical settings أو configuration، ثم أوقف bot إذا كان الخلل يهدد mutation أو المال.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.celeryq.dev/en/stable/userguide/monitoring.html "Celery monitoring"
[3]: https://docs.docker.com/compose/ "Docker Compose"
