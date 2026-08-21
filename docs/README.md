# توثيق Guardian Bot

هذا المجلد هو المرجع العملي للمشروع. صُمم بحيث يستطيع مشغل جديد تشغيل نسخة محلية، ويفهم المطور مسار التحديث، ويستطيع مسؤول المجموعة تفعيل الوظائف دون افتراضات غير مدعومة.

## خريطة التوثيق

| الفئة | المحتوى |
|---|---|
| البدء | التثبيت المحلي، الإعداد، Docker، أول تشغيل |
| المعمارية | شكل الطبقات، lifecycle، Redis، PostgreSQL، Celery |
| التشغيل | production readiness، runbooks، المراقبة، النسخ الاحتياطي |
| الأمان | threat model، الصلاحيات، الأسرار، حدود Telegram |
| المرجع | الأوامر، الإعدادات، الألعاب، حالات الميزات |
| التطوير | onboarding، الاختبارات، الإضافة، أسلوب المراجعة |
| استكشاف الأعطال | أخطاء startup، Redis، PostgreSQL، Celery، Telegram |

## مسارات موصى بها

للمشغل الجديد: [`getting-started/quickstart.md`](getting-started/quickstart.md) ثم [`getting-started/configuration.md`](getting-started/configuration.md) ثم [`runbooks/local-stack.md`](runbooks/local-stack.md).

لمسؤول المجموعة: [`reference/commands.md`](reference/commands.md) ثم [`reference/settings.md`](reference/settings.md) ثم [`runbooks/telegram-staging.md`](runbooks/telegram-staging.md).

للمطور: [`architecture/overview.md`](architecture/overview.md) ثم [`architecture/moderation-pipeline.md`](architecture/moderation-pipeline.md) ثم [`development/contributing.md`](development/contributing.md) و[`development/testing.md`](development/testing.md).

للاستجابة لحادث: [`operations/runbook.md`](operations/runbook.md) ثم [`troubleshooting/common-issues.md`](troubleshooting/common-issues.md).

## مبدأ التوثيق

كل عبارة عن حالة تشغيلية يجب أن تميز بين **موجود في الكود**، و**اختُبر محلياً**، و**اختُبر مع خدمة خارجية حقيقية**. لا تعني قيمة `configured` أن provider نفذ عملية ناجحة، ولا تعني اختبارات mocks أو الوحدات أن Telegram mutation اختُبرت حياً.

## مراجع خارجية

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/v22.8/ "python-telegram-bot v22.8"
[3]: https://docs.celeryq.dev/en/stable/ "Celery 5.6 documentation"
[4]: https://redis.io/docs/latest/ "Redis documentation"
[5]: https://docs.docker.com/compose/ "Docker Compose documentation"
