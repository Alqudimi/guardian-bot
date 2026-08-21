# خطة الجولة الثامنة عشرة — atomic raid reservation

## الهدف

منع تكرار Telegram lockdown mutations عند وصول انضمامات متزامنة، مع إبقاء `lockdown:{chat_id}` marker دليلاً على نجاح التنفيذ الأساسي فقط.

## القرار المعماري

يستخدم `check_raid` key حجز قصيرة العمر باسم `raid_activation:{chat_id}` عبر `SET NX EX`. فحص `exists` السابق مجرد fast path، أما الضمان الذري فهو NX نفسه. لا ينفذ إلا مالك الحجز `_activate_lockdown`؛ عند فشل Telegram تُحذف reservation ولا يُكتب active marker. عند النجاح تُكتب `lockdown:{chat_id}` وتُحذف reservation داخل Redis transaction واحدة. إذا فشل state commit بعد نجاح Telegram، لا تُعلن الدالة نجاحاً ولا تُحذف reservation، فتظل TTL كحاجز degradation يمنع تكرار mutation حتى تنتهي.

## الاختبارات

| المعيار | الاختبار |
|---|---|
| نجاح activation | تحديث اختبار Round 15 ليثبت reservation ثم state commit |
| concurrent joins | Redis حقيقي وخمس join updates، مع activation واحدة فقط |
| Telegram failure | `_activate_lockdown` يعيد false، reservation تُحذف ولا active marker |
| Redis state failure | commit يفشل، النتيجة false ولا تُعلن عملية ناجحة |
| عدم الانحدار | suite كاملة وquality gates |

## الحدود

لا يثبت الاختبار Telegram API الحي أو صلاحيات البوت أو وصول `chat_member` updates. لا يضمن rollback للـTelegram mutations الجزئية داخل `_activate_lockdown`; هذا يحتاج transaction/compensation لا يوفرها Telegram Bot API تلقائياً.
