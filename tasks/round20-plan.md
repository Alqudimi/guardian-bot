# خطة الجولة العشرون — اتساق raid state بين Telegram وRedis وDB

## الهدف

ضبط ترتيب state mutations بحيث لا تُسجل PostgreSQL lockdown قبل نجاح Telegram، ولا يُحذف Redis active marker قبل نجاح تحرير Telegram. كما تُعزل shop integrity tests عن وقت تشغيل sandbox حتى تبقى توقعات التسعير حتمية دون تغيير production pricing.

## القرار المعماري

يظل Telegram هو مصدر الحقيقة للعملية الخارجية. بعد نجاح Telegram وRedis active commit فقط، يحاول النظام mirror حالة `Group.raid_lockdown` و`Group.slow_mode_active` في PostgreSQL؛ فشل mirror يُسجل داخلياً ولا يعلن mutation خارجية غير ناجحة. في release، تُنفذ slow mode وpermissions أولاً، ثم notification best-effort، ثم DB mirror، ثم حذف Redis marker. عند فشل primary Telegram release يبقى marker وDB state كما هما لمنع إعادة التفعيل فوق حالة غير مؤكدة.

## الاختبارات

| المعيار | الاختبار |
|---|---|
| activation DB ordering | اختبار Round 15 يثبت استدعاء DB بعد state commit |
| release success | marker يُحذف بعد primary Telegram success |
| Telegram release failure | marker يبقى ولا يُستدعى DB mirror |
| partial release failure | slow mode يُعاد إلى 30 عند فشل permissions |
| DB mirror failure | Telegram release ينجح ويُحذف marker، مع تسجيل mirror failure |
| shop determinism | وقت النهار ثابت في integrity tests فقط، وتبقى production logic كما هي |

## الحدود

DB mirror ليس transaction مشتركة مع Telegram أو Redis. لذلك لا يمكن ضمان atomicity عبر الأنظمة الثلاثة، لكن لا يُعلن نجاح Telegram بناءً على DB، ولا يُحذف marker قبل primary release. تخصيصات permissions التاريخية غير معروفة، لذا baseline البوت هو ما يمكن استعادته.
