# Runbook Telegram staging

## المتطلبات

تحتاج token فعلياً، مجموعة staging مملوكة، bot administrator بالصلاحيات اللازمة، Redis/PostgreSQL staging، وقائمة `allowed_updates` صحيحة. لا تستخدم مجموعة الإنتاج في التجربة الأولى.

## خطة الاختبار

1. شغل `DRY_RUN=true` وراقب signals دون mutations.
2. اختبر `/status` و`/settings` وauthorization من owner/admin/member/private.
3. اختبر رسالة spam وduplicate وlink وmedia وraid في حدود المجموعة.
4. فعّل mutation واحداً في كل مرة، وتحقق من Telegram result قبل رسالة النجاح.
5. اختبر `/undo` بعد mute/ban حقيقيين، ثم تحقق من failure path.
6. اختبر `chat_member` وleave message مع `allowed_updates` والصلاحيات.
7. امسح بيانات التجربة وأوقف bot بعد انتهاء الاختبار.

## حدود Telegram

`getUpdates` وwebhook متنافيان، والتحديثات لا تبقى إلى الأبد. `chat_member` يتطلب bot administrator وأن يطلب update type صراحة. صلاحيات Telegram وrate limits قد تمنع الإجراء حتى لو كان قرار البوت صحيحاً [1].

## سجل الاختبار

سجل timestamp، environment، chat identifier غير العام، الأمر أو السيناريو، Telegram method، النتيجة، وأي degradation دون token أو بيانات حساسة. لا تكتب claims عن live verification ما لم ينفذ الاختبار فعلياً.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.chatmemberhandler.html "ChatMemberHandler v22.8"
