# ملاحظات بحث الجولة الثانية عشرة

## مصادر Telegram الرسمية

1. [Telegram Bot API](https://core.telegram.org/bots/api) — المرجع الأساسي لحدود `deleteMessage` و`restrictChatMember` و`banChatMember` و`getChatMember` وحقوق المشرفين. القرار: لا ينفذ البوت عقوبة إلا بعد التحقق من صلاحياته ومن توافق الإجراء مع نوع المجموعة وحقوقه الفعلية.

2. [Telegram Bots: Working with bots](https://core.telegram.org/api/bots) — يوضح سياق إضافة البوتات وحقوق الإدارة. القرار: لا يكفي وجود الأمر أو اسم المستخدم؛ يجب فحص عضوية المشرف وصلاحية البوت في الدفق الفعلي.

3. [python-telegram-bot v22 documentation](https://docs.python-telegram-bot.org/en/v22.5/index.html) — مرجع دورة تحديث المكتبة وأنواع Telegram objects. القرار: الحفاظ على async handlers و`ChatMemberHandler` وواجهات PTB v22 الحالية وعدم تعديل callback objects بطريقة غير مدعومة.

4. [python-telegram-bot ChatPermissions](https://docs.python-telegram-bot.org/en/v22.6/telegram.chatpermissions.html) — يوضح بناء صلاحيات التقييد ورفع التقييد. القرار: مسارات mute/unmute يجب أن ترسل صلاحيات صريحة وتتعامل مع فشل Telegram كفشل تنفيذ، لا كنجاح شكلي.

## قرارات هندسية

- لا يوجد مؤشر واحد موثوق يسمح للبوت بإثبات أن الحساب وهمي؛ تستخدم المجموعة مؤشرات قابلة للوصول فقط مثل account flags المتاحة، message rate، تكرار المحتوى، join burst، وسجل المخالفات.
- منع الحظر أو إغلاق المجموعة غير مضمون؛ الهدف هو تقليل المخاطر وتسجيل قرارات moderation بوضوح.
- إعدادات مكافحة spam يجب أن تبقى per-group، مع حدود محافظة وfail-safe عند تعطل Redis أو طبقة الكشف.
- أي توسعة يجب أن تعبر من pipeline/action execution/audit بدلاً من تنفيذ Telegram mutation من handler مباشرة.
