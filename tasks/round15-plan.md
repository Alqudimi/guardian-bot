# خطة الجولة الخامسة عشرة — ربط anti-raid بإعدادات المجموعة

## الملخص

بدأت الجولة من نسخة Round 14 المعتمدة بعد فحص read-only لمسار أحداث الأعضاء في المجموعة. أظهر الفحص أن `group_settings.py` يعلن `anti_raid` كإعداد per-group، وأن `/settings` يعرضه، بينما كان `check_raid` يعتمد فقط على إعدادات global الخاصة بعتبة الانضمامات ونافذتها. نطاق الجولة هو إصلاح هذا الانفصال بأصغر تغيير موصول بالمسار الفعلي، دون إعادة بناء detector أو تغيير آلية lockdown الحالية.

## قرار التصميم

يقرأ `check_raid` قيمة `anti_raid` من manager القائم قبل الوصول إلى Redis join counter. القيمة `on` تسمح بمتابعة detector الحالي، والقيمة `off` توقف هذا المسار للمجموعة. إذا فشلت قراءة الإعداد، يتوقف المسار بأمان مع تسجيل نوع الاستثناء داخلياً، لأن تنفيذ lockdown على أساس قيمة غير مؤكدة قد يتجاوز اختيار المشرف. لا يُنشأ مخزن إعدادات جديد، ولا تتغير عتبة raid أو نافذته global settings.

أضيف `/setraid on|off` إلى command router الحالي، ويستخدم `_admin_only` الموجود الذي يرفض private chats ويتحقق من رتبة Telegram الفعلية. يعرض `/settings` القيمة نفسها لأن المصدر بقي `group_settings` canonical.

## خطة التنفيذ والقبول

| المهمة | القبول | التحقق |
|---|---|---|
| ربط detector بالإعداد | `check_raid` يقرأ `anti_raid` قبل join counter؛ `on` يستمر إلى lockdown و`off` لا يلمس Redis أو Telegram | اختبارات enabled وdisabled |
| معالجة فشل القراءة | فشل settings لا ينفذ lockdown ولا يعلن نجاحاً | اختبار failure مع منع `get_redis` و`_activate_lockdown` |
| إضافة أمر الإدارة | `/setraid` يرفض قيمة غير صالحة ويحفظ `on/off` عند نجاح التحقق | اختبار validation وpersistence مع audit wrapper |
| التوثيق والتسليم | README وAGENT وtodo والتقرير وسجل التحقق محدثة | compileall، pytest، pip check، pip-audit، Ruff، archive integrity |

## الحدود

لا تثبت اختبارات sandbox استقبال `chat_member` من Telegram أو تنفيذ `set_chat_permissions` و`set_chat_slow_mode_delay` حياً. نجاح الجولة يثبت wiring المحلي واختبارات المسارات الموجّهة فقط. تبقى الحماية مشروطة بصلاحيات البوت، وصول التحديثات، وrate limits الخاصة بـTelegram.

## مراجع البحث

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.chatmemberhandler.html "ChatMemberHandler — python-telegram-bot v22.5"
