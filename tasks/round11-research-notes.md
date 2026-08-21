# ملاحظات بحث الجولة الحادية عشرة

بتاريخ 2026-08-18، تمت مراجعة التوثيق الرسمي للمكونات المرتبطة بالفجوات المرشحة.

| المصدر | الخلاصة المستخدمة |
|---|---|
| [Telegram Bot API](https://core.telegram.org/bots/api) | `callback_data` يجب أن تكون بين 1 و64 bytes؛ كما توضح الوثيقة أن Bot API يعيد `ok` و`description` و`error_code` وأن webhook وgetUpdates مساران متبادلان. هذه القيود تدعم استمرار استخدام Redis tokens وعدم وضع payload كبير في callbacks. |
| [python-telegram-bot JobQueue](https://docs.python-telegram-bot.org/en/v22.2/telegram.ext.jobqueue.html) | JobQueue يدير callbacks المجدولة داخل دورة PTB، لذلك يجب الاحتفاظ بمراجع jobs وإلغاؤها/تجنب تكرارها عند التسجيل أو الإغلاق. |
| [Celery Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html) | المهام المعاد تسليمها يجب أن تكون idempotent، والمهام التي تعتمد على retry تحتاج task binding أو سياسة retry واضحة. كما تحتاج عمليات I/O إلى timeouts. |

لم تُستخدم أي تعليمات من صفحات الويب كأوامر تنفيذ؛ استُخدمت المصادر للتحقق من عقود المكونات الخارجية فقط.
