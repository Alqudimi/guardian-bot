# مرجع الإعدادات

## إعدادات المجموعة

تخزن `smart_responses` و`leave_enabled` و`leave_msg` و`lang_policy` و`anti_raid` و`warn_limit` عبر `src/management/group_settings.py`. هذه هي source of truth التي يجب أن يقرأها `/settings` والـpipeline معاً.

عند وجود legacy key صالح، تنفذ القراءة lazy migration ثم تحذف المفتاح القديم. لا تبقِ مصدرين متضاربين.

## إعدادات الحماية

| الفئة | الإعدادات |
|---|---|
| flood | `FLOOD_WINDOW_SECONDS`, `FLOOD_MAX_MESSAGES`, `BURST_WINDOW_SECONDS`, `BURST_MAX_MESSAGES` |
| duplicate | `DUPLICATE_WINDOW_SECONDS` |
| scoring | `SPAM_SCORE_THRESHOLD`, `PHISHING_THRESHOLD`, `TOXICITY_THRESHOLD`, `NSFW_THRESHOLD` |
| anti-ban | `ACTION_RATE_LIMIT_PER_MINUTE`, `ACTION_COOLDOWN_PER_USER_SECONDS`, `BAN_HOURLY_LIMIT`, `DELETE_RATE_PER_MINUTE` |
| raid | `RAID_JOIN_WINDOW_SECONDS`, `RAID_JOIN_THRESHOLD` |

لا ترفع threshold في الإنتاج دون مراجعة false positives. لا تحول الإشارة الاحتمالية إلى ban دائم بلا calibration.

## Redis namespace

كل key جديد يستخدم `settings.redis_prefix`. يجب أن يحتوي كل key التنافسي على TTL مناسب، وتجب atomicity في reservation وdedup وcooldown. عند إضافة setting، أضف read/write/reset/migration tests.

## account intelligence

`account_age` هو `unknown` أو `unavailable_via_bot_api` عندما لا توجد بيانات canonical. لا يستخدم user ID أو username لاستنتاج العمر أو maliciousness، ولا يدخل risk score.

## payment settings

`PAYMENT_PROVIDER_TOKEN` الفارغ يعني deposits disabled. `PAYMENT_CURRENCY` يجب أن يطابق invoice وsuccessful payment. لا يعتمد الرصيد إلا بعد تحقق payment الحقيقي.

## مراجع

[1]: https://core.telegram.org/bots/api#user "Telegram User object"
[2]: https://core.telegram.org/bots/api#successfulpayment "Telegram SuccessfulPayment"
[3]: https://redis.io/docs/latest/develop/using-commands/keyspace/ "Redis keyspace and expiration"
