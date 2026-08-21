# Real shop payments research

تمت مراجعة المصادر الرسمية التالية قبل تعديل wallet deposit:

- https://core.telegram.org/bots/payments
- https://docs.python-telegram-bot.org/en/v22.5/examples.paymentbot.html
- https://core.telegram.org/bots/api

النتائج التشغيلية:

1. Telegram Payments تعتمد على provider token صادر من BotFather/مزود الدفع، ولا يجوز إضافة الرصيد بمجرد ضغط زر أو إدخال مبلغ.
2. المسار الصحيح هو `sendInvoice`، ثم الرد على `pre_checkout_query` خلال المهلة، ثم اعتماد الرصيد فقط بعد وصول `successful_payment`.
3. يجب ربط invoice داخلياً عبر payload فريد، والتحقق من user/payment/currency/amount، ومنع إعادة اعتماد نفس payload.
4. عند غياب provider token لا يوجد تدفق دفع حقيقي، ولذلك يجب تعطيل الإيداع الوهمي وإظهار أن الدفع غير مهيأ بدلاً من زيادة الرصيد فوراً.
5. نجاح invoice لا يعني تنفيذ خدمة المتجر؛ يجب أن يبقى fulfillment منفصلاً ولا تتحول حالة الطلب إلى completed دون executor أو تسليم مثبت.

المراجع الرسمية: Telegram Bot Payments، مثال paymentbot في python-telegram-bot v22.5، وBot API.
