# نتائج المراجع الخارجية الأولية

## Telegram Bot API

المصدر الرسمي يوضح أن `setWebhook` يدعم `secret_token`، وعند ضبطه تُرسل Telegram قيمة السر في header باسم `X-Telegram-Bot-Api-Secret-Token`. هذا يدعم اشتراط سر webhook في بيئة الإنتاج وعدم تشغيل endpoint مكشوف بلا تحقق.

المصدر: [Telegram Bot API](https://core.telegram.org/bots/api)

## python-telegram-bot

توثيق `python-telegram-bot` v22.8 يوضح أن `Updater.start_webhook` يمرر `secret_token` إلى `set_webhook`، وأن خادم webhook يرفض الطلب عندما يكون header مفقوداً أو خاطئاً باستجابة HTTP 403. لذلك يجب ربط إعداد التطبيق بسر webhook فعلي عند تشغيل webhook، والتحقق من التوافق بين إعدادات المشروع وواجهة المكتبة.

المصدر: [Updater — python-telegram-bot v22.8](https://docs.python-telegram-bot.org/en/stable/telegram.ext.updater.html)

## تحقق محلي من الإقلاع

تم بناء `Application` الفعلي في بيئة التطوير باستخدام token اختباري صالح شكلياً وRedis محلي حقيقي. سجّل التطبيق 87 handler ضمن المجموعات 0 و1 و2، وسُجلت الميزات الموجودة فعلياً: azkar وinstagram وmedia_downloader وquotes وquran وsmart_detect وsoundcloud وvoice_chat، إضافة إلى 18 لعبة ونظام المتجر. قبل الإصلاح كان السجل يحاول استيراد وحدات غير موجودة مثل anti_spam وmoderation وwelcome وrules وcaptcha؛ تم استبدال ذلك بتسجيل ديناميكي للوحدات الموجودة فقط مع فشل جزئي واضح.

هذه نتيجة تشغيل محلية وليست دليلاً على اتصال Telegram حي، لأن token الحقيقي ومجموعة الاختبار غير متاحين في بيئة العمل.


## إعادة التحقق في الجولة الثانية

تؤكد صفحة Telegram Bot API الرسمية أن `setWebhook` يستخدم HTTPS POST، ويعيد إرسال التحديث عند فشل الاستجابة، ويدعم `secret_token` عبر header `X-Telegram-Bot-Api-Secret-Token`. كما تؤكد وجود `getChatMember` وكائن administrator وطرق `deleteMessage` و`restrictChatMember` و`banChatMember` المستخدمة فعلياً في المشروع.

توضح الوثائق الحالية لـ `python-telegram-bot` أن النسخة المستقرة المعروضة هي v22.8، وأن المكتبة غير متزامنة بالكامل وتدعم polling وwebhooks وميزات rate limiting. يجب إبقاء قيود الاعتماديات متوافقة مع هذا النطاق وعدم إدخال APIs تخص إصدارات أخرى.

المراجع: [Telegram Bot API](https://core.telegram.org/bots/api)، [python-telegram-bot v22.8](https://docs.python-telegram-bot.org/en/stable/)
