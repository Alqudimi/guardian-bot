# سجل التغييرات

## Round 22 — Local infrastructure readiness

تم تثبيت وربط PostgreSQL وRedis وCelery وDocker محلياً، وتطبيق Alembic على قاعدة PostgreSQL، وتشغيل worker وbeat، وإصلاح event loop reuse في Celery، وبناء image `guardian-bot:round22` والتحقق من runtime smoke. انتهت suite بـ271 اختباراً ناجحاً مع `-W error`.

التكاملات الخارجية غير المتاحة — Telegram live، PostgreSQL production، providers، instant fulfillment، وMafia scoring — بقيت معطلة وموثقة.

## Rounds 15–21

شملت ربط anti-raid وwarn limits بالمصدر canonical، atomic warning history، atomic raid reservation، compensation للفشل الجزئي، اتساق raid state، وCAPTCHA lifecycle وcanonical settings.

## Rounds 1–14

شملت بناء وتعزيز منظومة المجموعات، moderation pipeline، anti-spam وflood، الألعاب الداخلية، smart interaction، الأمن، callbacks، المتجر fail-closed، والتوثيق الأساسي.

للتفاصيل، راجع ملفات `tasks/round*-report.md` و`tasks/round*-final-validation.txt`.
