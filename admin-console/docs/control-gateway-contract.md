# عقد Guardian Bot Control Gateway

## الهدف والنطاق

يفصل هذا العقد بين **لوحة الإدارة** و**عملية Guardian Bot**. لا تتصل الواجهة مباشرةً بـRedis أو PostgreSQL الخاصين بالبوت، ولا تتلقى token Telegram. تتصل backend اللوحة فقط ببوابة تحكم Python مصادق عليها، وتتحقق البوابة من صلاحية operator ومن سلطة Telegram قبل أي mutation.

## المصادقة

تستخدم كل طلبات اللوحة إلى البوابة HTTPS وheader سرياً مخصصاً للربط بين الخدمتين، مع request ID وtimestamp ونطاق قصير للمهلة. لا يمرر browser هذا السر. ترفض البوابة أي طلب لا يطابق السر أو النسخة أو schema المتوقعة، ولا تكشف استثناء داخلياً.

## استجابات موحدة

```json
{
  "ok": true,
  "requestId": "uuid",
  "data": {},
  "availability": "AVAILABLE"
}
```

وعند الرفض أو التعذر:

```json
{
  "ok": false,
  "requestId": "uuid",
  "error": {
    "code": "TELEGRAM_UNAVAILABLE",
    "message": "The requested action is not currently available."
  },
  "availability": "DEGRADED"
}
```

الأكواد المرئية هي `VALIDATION_ERROR` و`UNAUTHENTICATED` و`FORBIDDEN` و`NOT_FOUND` و`CONFLICT` و`TELEGRAM_UNAVAILABLE` و`DEPENDENCY_UNAVAILABLE` و`EXECUTION_FAILED`. لا تعرض البوابة secrets أو stack traces أو تفاصيل provider للمستخدم.

## موارد القراءة

| المورد | العملية | المصدر الحقيقي |
|---|---|---|
| `/v1/status` | حالة transport وDB وRedis وCelery وsettings | probes البوت ونتائجها |
| `/v1/groups` | قائمة المجموعات وحالة raid | PostgreSQL/Redis عند توفرهما |
| `/v1/groups/{id}/settings` | قراءة الإعدادات | `group_settings.get_all_settings` canonical |
| `/v1/moderation-events` | بحث وتصفية وصف التفاصيل | `ModerationEvent` دائم |
| `/v1/groups/{id}/members` | أعضاء وحالات policy | `GroupMember`/`User` مع حدود Telegram |
| `/v1/games` | sessions وscoreboards | `GameSessionManager` وRedis |
| `/v1/reports` | تقارير counters الفعلية | `management.reports` |

## عمليات الكتابة

| المجال | العملية | شروط التنفيذ |
|---|---|---|
| settings | تحديث أو reset إعداد group | operator policy + group scope + manager validation + audit |
| members | warn/reset warn/whitelist/blacklist | operator policy + group scope + action owner + audit |
| Telegram actions | mute/unmute/ban/unban/kick/undo/unlock | اتصال Telegram + bot rights + group scope + confirmed mutation + audit |
| patterns | add/remove group pattern | bounded validation + manager الوحيد + audit |
| games | stop session وقراءة scoreboard | owner/session validation + idempotency |
| schedules | إنشاء/إيقاف readiness cleanup reports | admin policy + deployed scheduled handler + durable task UID |

## تفويض الويب

تتحقق لوحة الويب من OAuth role، ثم من scope محفوظ لكل group، ثم ترسل `operatorTelegramId` فقط بعد التحقق من ربط الهوية. تتحقق بوابة البوت من أن user في `TELEGRAM_ADMIN_IDS` ومن `get_chat_member` وأن status هو `administrator` أو `creator` للمجموعة المستهدفة. صلاحية web لا تتجاوز هذه الحراسة.

## التوفر وحالات التدهور

إذا لم تكن البوابة مشغلة أو URL/secret غير مضبوطين، تظهر لوحة الإدارة حالة **غير متصلة** وتبقى عمليات البوت المعتمدة على الاتصال الخارجي معطلة. إذا كان Redis أو PostgreSQL متعذراً، تعيد البوابة حالة **degraded** مع إمكانات القراءة أو الكتابة التي توقفت، ولا تعوضها بنسخة cache مجهولة أو بيانات مصطنعة.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/v22.8/ "python-telegram-bot v22.8"
