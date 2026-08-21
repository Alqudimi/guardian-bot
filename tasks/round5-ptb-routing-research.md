# Round 5 routing research

تمت مراجعة توثيق `python-telegram-bot` v22 الرسمي في:

- https://docs.python-telegram-bot.org/en/v22.2/telegram.ext.application.html
- https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.commandhandler.html

الخلاصة المرتبطة بالمشروع: تُنظّم handlers داخل مجموعات رقمية، وتُقيّم المجموعات حسب ترتيبها. داخل المجموعة نفسها، عند وجود أكثر من handler قابل للتطبيق، يُستخدم أول handler مطابق فقط لذلك التحديث، بينما يمكن تقييم handler واحد من كل مجموعة. بناءً على ذلك، تسجيل `CommandHandler("play", ...)` مرتين لا يدمج سلوك music وgames؛ بل يجعل نتيجة `/play` معتمدة على ترتيب التسجيل والمجموعة، وقد يحجب أحد المسارين.

المصدر الرسمي: https://docs.python-telegram-bot.org/en/v22.2/telegram.ext.application.html
المصدر الرسمي: https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.commandhandler.html
