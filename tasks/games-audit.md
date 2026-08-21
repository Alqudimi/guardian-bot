# تدقيق منظومة الألعاب — قبل الجولة الحالية

## التصنيف المثبت من الكود

| التصنيف | الألعاب | الدليل |
|---|---|---|
| ألعاب داخلية ذات تدفق حقيقي لكنه ناقص | `mafia`, `chameleon` | تحتوي join/callbacks/رسائل وأدوار أو clues/votes داخل البوت، لكن Mafia يحوي `asyncio.sleep(5)` كمحاكاة لليل ويفتقد import لـ `random`، وChameleon يفتقد import لـ `random` وحفظ state الكامل. |
| Wrappers خارجية وليست ألعاباً من البوت | `space_invaders`, `pacman`, `flappy_bird`, `chess`, `maze`, `crash_game`, `token_giver`, `insta_quiz`, `math_quiz`, `ers` | التسجيل يمرر روابط GitHub/ChessNow إلى `MiniAppGame`، و`MiniAppGame.start()` لا يفعل إلا إرسال `WebAppInfo`; `handle_callback` و`handle_message` فارغان. |
| Placeholders غير مكتملة | `z5`, `conversational`, `worldwar`, `geosensei`, `codymaze`, `jigsaw` | start يرسل generic message فقط، وcallback/message handlers فارغان، وstate لا يحوي إلا status. |

## فجوات الاختبارات الحالية

`tests/test_all_games.py` كان يثبت تسجيل wrappers الخارجية ويكتفي بإنشاء الكائنات، ولا يثبت gameplay أو ملكية الكود أو callbacks أو state transitions. لذلك كانت الألعاب الخارجية والـ placeholders تمر suite رغم عدم وجود منطق لعب.

## قرار الجولة

إزالة Mini Apps والـ placeholders من قائمة الألعاب المتاحة بدلاً من إبقائها كوظائف وهمية. إبقاء Mafia وChameleon وإعادة بنائهما كتدفقات Telegram داخلية كاملة قابلة للاختبار، ثم تحديث registry والاختبارات لتتحقق من أن كل registered game module يقع تحت `src/games` ولا يملك `web_url` خارجياً.


## بعد التنفيذ

أصبح registry يسجل `mafia` و`chameleon` فقط. أزيلت حزمة `mini_apps` وملفات `z5` و`conversational` و`worldwar` و`geosensei` و`codymaze` و`jigsaw`، ولم يعد المسح يجد `MiniAppGame` أو `WebAppInfo` أو روابط الألعاب الخارجية داخل `src` أو الاختبارات أو README.

أعيد بناء Mafia بحيث لا تستخدم `asyncio.sleep` كمحاكاة: الأدوار الليلية تصل إلى اللاعبين الحقيقيين عبر Telegram DM، وكل إجراء يُسجل عبر callback ويُحسم عند اكتمال الإجراءات المطلوبة. وأعيد بناء Chameleon بحيث يختار الموضوع عبر DM، يوزع الكلمة سراً، يستقبل clue فعلياً من كل لاعب بالترتيب، ثم ينفذ التصويت داخل المجموعة.

اختبارات الألعاب المركزة: 5 ناجحة، والـ suite الكاملة: 165 ناجحة مع `pytest -W error`. العدد الكلي انخفض مقارنة بالجولة السابقة لأن الاختبارات السطحية للألعاب الخارجية والـ placeholders حُذفت واستبدلت باختبارات gameplay حقيقية.
