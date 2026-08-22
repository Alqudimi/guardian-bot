# جرد قدرات Guardian Bot

هذا الجرد يصف الوظائف الموجودة في الكود ومصادر الحقيقة الخاصة بها. لا يعني وجود العمود أن التكامل الخارجي مُهيأ أو مختبر حياً.

| المجال | القدرة الحالية | المسار أو المالك | مصدر الحقيقة | حدود حقيقية |
|---|---|---|---|---|
| التشغيل | بدء bot عبر polling أو webhook | `main.py` | settings وTelegram transport | webhook وpolling متنافيان؛ التشغيل الحي يحتاج token وعنوان صالحين |
| الصحة | probes محلية لـDB وRedis وvoice وpayments والألعاب | `/status` في handler | اتصالات runtime وsettings | لا تثبت Telegram live أو provider خارجي بمفردها |
| الإشراف | pipeline من normalization حتى audit | `pipeline/orchestrator.py` و`layers/` | context وRedis وPostgreSQL | القرار مقيد بالصلاحيات ووصول update وrate limits |
| spam/flood | flood وburst وduplicate وcoordinated signals | `layers/flood_detection.py` | Redis TTL وreservations | لا يمثل حماية مطلقة من spam |
| المحتوى | blacklist وpatterns وlanguage وlinks وmedia وAI اختياري | fast rules وmanagers والطبقات | Redis/PostgreSQL/models optional | فشل AI/provider لا ينتج نجاحاً أو حظراً وهمياً |
| المجموعة | CAPTCHA وanti-forward وraid وwelcome وleave وrules | `management/*` | `group_settings` canonical في Redis | leave/update يحتاج chat_member وصلاحية bot |
| الإعدادات | profiles وlimits وwarnings وsmart replies وsilent mode | `group_settings.py` | Redis hash `group_settings:{chatId}` | lazy migration للمفاتيح القديمة فقط؛ لا مصدر موازٍ |
| الإدارة | mute/unmute/ban/unban/kick/undo/unlock | `admin_commands.py` وaction execution | Telegram mutation و`ModerationEvent` | النجاح بعد mutation فقط؛ undo لا يعيد permissions تاريخية مجهولة |
| العضوية | trust/risk/warnings/whitelist/blacklist/mute | `GroupMember` و`User` | PostgreSQL عند توفره | لا account age مستنتج من user ID أو username |
| moderation data | events والإشارات والقرار والتنفيذ | `ModerationEvent` | PostgreSQL | يعتمد على حفظ event وإتاحة DB |
| التقارير | counts وraids وCAPTCHA وoffenders | `management/reports.py` | Redis counters | on-demand موجود؛ delivery دوري غير مدعى حالياً |
| الألعاب | Mafia وChameleon وsessions وscoreboards | `GameSessionManager` | Redis session وsorted set | Mafia بلا scoring contract، فلا نقاط اصطناعية |
| smart/downloads | smart responses وtokens مؤقتة | `features/` وRedis | Redis prefixed keys | raw URL لا يوضع في callback data |
| الصوت | voice backend اختياري | `features/voice_chat.py` | backend lifecycle/settings | unavailable إذا غابت credentials أو dependency |
| المتجر والدفع | transactions وTelegram payments | shop modules | PostgreSQL وprovider callbacks | deposit معطل بلا provider؛ instant fulfillment غير مكتمل بلا executor |
| Celery | recalculation/maintenance tasks | `src/tasks/` | Redis broker وworker | يحتاج worker/broker حقيقيين؛ idempotency مطلوبة |
| Docker | image وcompose محليان | Dockerfile/Compose | Docker runtime | إثبات محلي لا يساوي rollout إنتاجياً |
| التدقيق | admin command وmoderation audit | audit/logging/modlog | PostgreSQL/Redis وTelegram best-effort | فشل modlog ثانوي لا يزيف نتيجة mutation |

## catalogue عمليات الإدارة المعروفة

تشمل أوامر الإدارة الموجودة حالياً القواعد ورسائل الترحيب والمغادرة وmodlog واللغة وCAPTCHA وanti-raid وanti-forward والإعدادات والتصفية وحدود المحتوى والوضع الصامت والمستخدمين والتحذيرات والكتم والحظر والتراجع والـpatterns والتقارير. المرجع الخام المستخرج من source محفوظ في `guardian-command-catalog.txt` داخل مجلد التوثيق.

## أثر الجرد على اللوحة

تحتاج لوحة الإدارة بوابة تحكم للعرض أو الكتابة؛ لا يمكن للـbrowser الوصول مباشرةً إلى Redis أو PostgreSQL البوت أو Telegram token. كل عنصر UI يعرض المصدر والحالة وشروط الإذن، ويُعطل عندما تكون capability غير موصولة أو غير متاحة.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.celeryq.dev/en/stable/ "Celery documentation"
