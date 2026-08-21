# مسار الإشراف والقرار

## الترتيب التنفيذي

يمر كل update قابل للإشراف عبر normalization ثم fast rules ثم flood/behavior ثم link/media/AI ثم risk scoring ثم decision ثم action execution ثم audit. لا يجوز لطبقة لاحقة أن تعيد القرار إلى `allow` إذا أثبتت طبقة سابقة إشارة عالية الثقة.

| المرحلة | الوظيفة | قاعدة السلامة |
|---|---|---|
| normalization | Unicode، invisible chars، homoglyphs، URLs، fingerprint | لا تنشئ fingerprint نصياً فارغاً للرسائل media-only |
| fast rules | whitelist/blacklist، regex، patterns، links، mentions، media | القواعد الحتمية عالية الثقة short-circuit |
| flood/behavior | sliding windows، burst، entropy، trust | exact duplicate user-scoped؛ coordinated بين المستخدمين |
| link/media/AI | phishing، SSRF-safe fetch، NSFW، toxicity | provider failure degraded لا ينتج ban تلقائياً |
| risk scoring | تجميع الإشارات | لا يخلط account age غير المتاح مع risk |
| decision | allow/log/delete/warn/mute/ban/escalate | يحترم high-confidence overrides |
| action execution | Telegram mutation مع rate limits | لا تسجل نجاحاً قبل نجاح mutation |
| audit | PostgreSQL/modlog/metrics | secondary failure لا يكسر الإجراء الأساسي |

## high-confidence signals

تشمل blacklist، phishing المؤكد، crypto/Arabic scam المؤكد، group patterns المؤكدة، RLO/null-byte/decimal-IP، ومخالفة language policy المؤكدة. هذه الإشارات لا تُستبدل بتقييم احتمالي لاحق.

## التكرار والتنسيق

التكرار الذاتي exact duplicate يحجز Redis key داخل `chat_id/user_id`. أما near-duplicate أو coordinated spam فمسؤولية إشارات بين المستخدمين. لا تستخدم fingerprint النصي الفارغ لتصنيف media-only كنسخة نصية.

## التنفيذ والفشل

تعرض `PipelineContext` حالة التنفيذ والسبب الداخلي للـaudit فقط. رسالة المستخدم عامة ولا تحتوي exception internals. إذا فشل Telegram mutation الأساسي، لا يكتب النظام false success. إذا فشل modlog أو metrics، يسجل degradation ويترك mutation الناجحة كما هي.

## معايرة

أي تغيير في thresholds أو action mapping يحتاج positive/negative/failure tests ومراجعة false positives. لا يحول score احتمالي وحده إلى حظر دائم دون دليل عالي الثقة أو سياسة معايرة معتمدة.

## مراجع

[1]: https://core.telegram.org/bots/api#restrictchatmember "Telegram Bot API — restricting members"
[2]: https://core.telegram.org/bots/api#banchatmember "Telegram Bot API — banning members"
