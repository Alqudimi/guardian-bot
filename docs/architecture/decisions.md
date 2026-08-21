# قرارات تصميم موثقة

## مصدر إعدادات واحد

تستخدم إعدادات المجموعة manager واحداً وRedis hash canonical. lazy migration يحول legacy key صالحاً ثم يحذفه. إبقاء مصدرين متضاربين مرفوض لأنه ينتج فرقاً بين `/settings` والـpipeline.

## fail-closed للمال والإنفاذ

لا يزيد الرصيد من callback أو user state. لا تنتقل instant service إلى completed بلا executor/provider حقيقي. لا يسجل Telegram mutation نجاحاً قبل عودة API بنجاح.

## الحدود الواقعية للحساب

Telegram Bot API لا يقدم creation date للحساب ضمن message updates؛ لذلك account age `unknown` ولا يدخل risk. تقرير `/userinfo` يعرض حدود البيانات بدلاً من التخمين.

## الألعاب داخلية

اللعبتان المملوكتان Mafia وChameleon فقط. أزيلت wrappers الخارجية والواجهات الوهمية. لا توجد نقاط Mafia بلا contract مقصود.

## مراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://core.telegram.org/bots/api#payments "Telegram Payments"
