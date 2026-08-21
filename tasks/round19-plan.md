# خطة الجولة التاسعة عشرة — تعويض فشل raid الجزئي

## الهدف

تقليل أثر فشل Telegram بعد نجاح خطوة أو أكثر أثناء `_activate_lockdown`، دون الادعاء بأن Telegram يوفر transaction أو rollback تلقائياً.

## القرار

تتبع `_activate_lockdown` ما إذا كان slow mode وdefault permissions قد طُبقا فعلياً. عند فشل Telegram لاحق، ينفذ تعويض best-effort: يعيد default permissions التي يعرّفها البوت، ثم يعطل slow mode. فشل التعويض يسجل داخلياً ولا يحول العملية إلى نجاح. لا يُحفظ lockdown marker عند الفشل، وتبقى reservation الخارجية مسؤولة عن منع duplicate activation وفق عقد الجولة السابقة.

## معايير القبول

| المعيار | الاختبار |
|---|---|
| فشل إشعار المجموعة بعد نجاح mutation | يعيد permissions وslow mode إلى baseline |
| فشل permissions بعد نجاح slow mode | يعطل slow mode فقط ولا يرسل إشعاراً |
| compensation failure | لا يعلن نجاحاً ولا يرمي تفاصيل داخلية للمستخدم |
| عدم الانحدار | suite كاملة وquality gates |

## الحدود

التعويض يعيد baseline الذي يحدده البوت، ولا يستعيد تخصيصات تاريخية غير مقروءة. فشل الإشعارات الإدارية الثانوية يبقى best-effort ولا يلغي primary lockdown إذا نجحت خطوات Telegram الأساسية.
