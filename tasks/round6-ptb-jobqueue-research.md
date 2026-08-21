# Round 6 PTB JobQueue research

تمت مراجعة توثيق python-telegram-bot الرسمي الخاص بـ JobQueue وCallbackContext:

- https://docs.python-telegram-bot.org/en/v22.2/telegram.ext.jobqueue.html
- https://docs.python-telegram-bot.org/en/v22.5/telegram.ext.callbackcontext.html

الخلاصة العملية: JobQueue يوفر `run_once` لتنفيذ callback مرة واحدة بعد مدة، وتصل بيانات المهمة إلى callback عبر كائن job في `CallbackContext`. سيُستخدم ذلك لتأجيل `release_lockdown` لخمس دقائق بعد تفعيل raid، مع تسمية المهمة وإمكان إلغائها/استبدالها عند الحاجة. يجب أن يبقى المسار آمناً إذا لم يكن JobQueue متاحاً أو لم تُهيأ ميزة APScheduler؛ عندها تُسجل حالة التدهور ولا يُدّعى أن auto-release يعمل.
