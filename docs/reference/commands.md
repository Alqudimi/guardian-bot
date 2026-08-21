# مرجع الأوامر

## قاعدة الصلاحيات

كل أمر يغير إعدادات المجموعة أو ينفذ moderation حساس يجب أن يعمل داخل `group` أو `supergroup`، ثم يمر عبر `is_authorized_admin` و`get_chat_member` للتحقق من `administrator` أو `creator`. لا يكفي وجود user ID في allowlist.

## أوامر الحالة والمساعدة

| الأمر | النطاق | الوظيفة |
|---|---|---|
| `/start` | private/group | بدء الواجهة الأساسية |
| `/help` | all | المساعدة العامة |
| `/grouphelp` | group | مساعدة خاصة بأعضاء المجموعة |
| `/status` | all/admin detail | diagnostics دون أسرار |
| `/settings` | group/admin detail | عرض الإعدادات canonical |

## أوامر الإدارة

| الأمر | الصيغة | ملاحظات |
|---|---|---|
| `/whitelist` | `/whitelist <user_id>` | يكتب audit بعد النجاح |
| `/blacklist` | `/blacklist <user_id>` | يتطلب group check والصلاحية |
| `/unlock` | `/unlock` | لا يعلن النجاح قبل Telegram release |
| `/undo` | `/undo [user_id]` | آخر event قابل للعكس داخل المجموعة والمستخدم |
| `/dryrun` | `/dryrun on\|off` | تشغيل إداري؛ لا يخفي فشل mutation |
| `/setmoderation` | `light\|moderate\|strict` | إعداد per-group |
| `/setlimits` | حسب parser الحالي | links وmentions بحدود validated |
| `/setraid` | `on\|off` | يتحكم في `check_raid` canonical |
| `/setwarnlimit` | قيمة موجبة bounded | مصدر warning ladder الوحيد |
| `/groupaddpattern` | `<category> <pattern>` | حد 100 قاعدة و512 حرفاً وcompile validation |
| `/groupremovepattern` | `<id>` | يحذف pattern بعد تحقق ownership |
| `/grouppatterns` | — | يعرض القواعد النشطة دون أسرار |
| `/setsmart` | `on\|off` | smart replies مع cooldown Redis |
| `/setleave` | `<text>` | يحدد النص؛ placeholders تستبدل قبل الإرسال |
| `/leave` | `on\|off` | يعتمد على ChatMember updates وbest-effort |

## الألعاب

| الأمر | الوظيفة |
|---|---|
| `/games` | عرض Mafia وChameleon فقط |
| `/play mafia` | بدء Mafia عبر dispatcher |
| `/play chameleon` | بدء Chameleon عبر dispatcher |
| `/mafia_start` | اختصار Mafia |
| `/cham_start` | اختصار Chameleon |
| `/stopgame` | إيقاف اللعبة وحذف session بعد الأرشفة |
| `/gamescores [game]` | قراءة scoreboard المحفوظ |

## الصوت والتنزيل

`/music <url أو بحث>` هو المدخل الصريح للصوت. `/play <url أو بحث>` يحافظ على التوافق؛ أسماء الألعاب المعروفة تذهب إلى game dispatcher، وباقي الاستعلامات إلى مسار الصوت. download tokens قصيرة العمر ولا تحتوي raw URL في callback data.

## أخطاء متوقعة

رسائل invalid input عامة وواضحة، أما تفاصيل Telegram أو provider أو database فتُسجل داخلياً فقط. فشل modlog أو metrics لا يلغي mutation الأساسية، لكن فشل Telegram mutation يمنع رسالة النجاح.

## مراجع

[1]: https://core.telegram.org/bots/api#chatmember "Telegram Bot API — chat members"
[2]: https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.chatmemberhandler.html "ChatMemberHandler v22.8"
