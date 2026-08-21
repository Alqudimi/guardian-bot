# تتبع طلب من Telegram إلى النتيجة

## الرسالة العادية

يستقبل `src/handlers/message_handler.py` التحديث ويحدد chat وuser وmessage. تُرفض مسارات الإدارة خارج group/supergroup عند الحاجة، ويُتحقق من admin عبر `is_authorized_admin` و`get_chat_member`، لا عبر allowlist وحدها.

ينشئ handler `PipelineContext` ويمرره إلى `src/pipeline/orchestrator.py`. تنفذ الطبقات الإشارات بالترتيب، وتكتب state المؤقت إلى Redis عند الحاجة، ثم يختار decision engine الإجراء. يمر الإجراء إلى `action_execution.py` حيث تطبق rate limits وcooldowns، ثم يستدعي Telegram API.

لا ترسل رسالة نجاح إلا بعد نتيجة Telegram الحقيقية. بعد ذلك يحاول audit logging حفظ الحدث في PostgreSQL أو modlog؛ فشل audit ثانوي لا يمحو نجاح mutation ولا يحوله إلى false failure.

## أمر إداري

```text
CommandHandler
  -> validate arguments
  -> require group/supergroup when group state is touched
  -> is_authorized_admin
  -> get_chat_member role check
  -> canonical manager write
  -> Telegram mutation if applicable
  -> concise audit event
  -> user confirmation only after success
```

لا يسجل audit arguments حساسة. لا تعرض تفاصيل provider أو database أو Telegram exception للمستخدم.

## game callback

يتحقق callback من اسم اللعبة والـpayload وchat ID. callbacks القادمة من DM تقارن chat ID الموجود في session group، ثم تمرر الحالة إلى GameSessionManager. لا ينشئ callback تخزيناً موازياً ولا يثق بـuser ID وحده دون ownership check.

## مراجع

[1]: https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.handlers-tree.html "python-telegram-bot handlers"
[2]: https://core.telegram.org/bots/api#chatmemberupdated "Telegram ChatMemberUpdated"
