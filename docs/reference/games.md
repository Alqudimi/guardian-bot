# الألعاب الداخلية

## الملكية والنطاق

الألعاب المسجلة والمملوكة للمشروع هي Mafia وChameleon فقط. منطق اللعب داخل `src/games/`، والحالة داخل GameSessionManager، والرسائل والـcallbacks تمر عبر Telegram handlers. لا توجد WebApp خارجية أو روابط لعبة بديلة.

## Mafia

تحتوي Mafia على تدفق فعلي للأدوار والتسجيل والأفعال الليلية والتصويت واستعادة session من Redis. لا تحتوي حالياً على scoring contract، ولذلك يبقى `/gamescores mafia` فارغاً عمداً. لا تضف نقاطاً اصطناعية؛ أضف العقد أولاً ثم migration واختبارات نهاية اللعبة والأخطاء.

## Chameleon

تحتوي Chameleon على اختيار الموضوع وتوزيع الكلمة والـclues والتصويت، وتستخدم نفس ownership وsession boundaries. يجب اختبار callbacks من المجموعة وDM، مع التأكد من تطابق chat ID session مع group chat الأصلي.

## callback security

قبل التنفيذ:

1. تحقق من اسم اللعبة وشكل payload.
2. طابق chat ID المضمن مع message chat، أو مع group chat session عند callback من DM.
3. تحقق من user ownership عندما يكون الزر مقيداً بمستخدم.
4. اقرأ الحالة من GameSessionManager فقط.
5. أعد رسالة عامة عند الفشل دون كشف exception.

## scoreboard

يستخدم الأرشيف `BaseGame.get_scores()` و`GameSessionManager.persist_scores()` عبر Redis sorted set وdistributed lock وtransaction وmarker وTTL. العملية idempotent عند تكرار stop أو حذف session، ولا يثبت marker قبل نجاح scoreboard. تُرفض `NaN` و`Infinity` والقيم غير المحدودة.

## مراجع

[1]: https://docs.python-telegram-bot.org/en/v22.8/telegram.inlinekeyboardbutton.html "Inline keyboard buttons"
[2]: https://redis.io/docs/latest/develop/data-types/sorted-sets/ "Redis sorted sets"
