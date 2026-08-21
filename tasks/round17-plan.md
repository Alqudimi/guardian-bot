# خطة الجولة السابعة عشرة — atomic warn history

## الهدف

إصلاح نافذة race في `src/layers/smart_warn.py::add_warn` التي كانت تقرأ JSON history ثم تكتبها دون حماية. التغيير يحافظ على Redis وnamespace الحاليين، ولا يغير contract التصعيد أو إعداد `warn_limit` الذي أصبح canonical في الجولة السابقة.

## القرار

يُستخدم Redis `WATCH/MULTI/EXEC` على key الخاصة بـ`warns:{chat_id}:{user_id}`. كل محاولة تراقب key، تقرأ history، تضيف السجل، وتنفذ `SET` و`EXPIRE` داخل transaction واحدة. عند `WatchError` يعاد المحاولة حتى أربع مرات مع تأخير صغير متزايد. عند فشل Redis أو استنفاد التعارضات يُرفع الخطأ ولا يُسجل `warn_added` ولا تُعاد نتيجة نجاح.

## القبول والاختبارات

| المعيار | الاختبار |
|---|---|
| حفظ سجل واحد | اختبارات smart_warn الحالية بعد مواءمة pipeline mock |
| حفظ سجلين متزامنين | Redis حقيقي و`asyncio.gather` مع تحقق من history count والأنواع |
| retry بعد تعارض | fake pipeline يرفع `WatchError` ثم ينجح، مع التحقق من محاولتين |
| failure safety | fake pipeline يرفع Redis connection error، مع التحقق من رفع الخطأ وعدم نجاح العملية |
| عدم الانحدار | suite كاملة مع `-W error` وquality gates |

## الحدود

هذه الحماية تخص history key الواحدة لكل user/group. لا تعالج في هذه الجولة race منفصلة في raid lockdown أو أي transaction مالية أو PostgreSQL. الاختبار لا يثبت latency production أو Telegram live behavior.

## المراجع

[1]: https://redis.io/docs/latest/develop/using-commands/transactions/ "Redis Transactions and WATCH"
[2]: https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html "redis-py Asyncio Examples"
