# تقرير تدقيق الوظائف الحقيقية

## النطاق

ركزت هذه الجولة على الوظائف والعمليات التي يمكن أن تُظهر للمستخدم نجاحاً بينما لا تنفذ العملية فعلياً. تم فحص handlers، callbacks، قاعدة البيانات، Redis، Bot API، تنزيل الوسائط، voice backend، المتجر، payment flow، وحالات الطلب. عُدّت fallback المحلية مقبولة فقط عندما تكون نتيجة حقيقية مستقلة، مثل بيانات الأذكار المحلية عند فشل API؛ أما إضافة رصيد أو تشغيل صوت أو إكمال خدمة دون حدث تنفيذي فاعتُبرت محاكاة غير مقبولة.

## النتائج المثبتة والإصلاحات

| المسار | المشكلة المثبتة | الإصلاح الفعلي |
|---|---|---|
| إيداع المتجر | كان callback المبلغ يستدعي `deposit` ويزيد الرصيد فوراً، مع رسالة `test mode` | أصبح المسار invoice حقيقياً عبر Telegram Payments: pending intent، provider token، pre-checkout validation، ثم credit واحد بعد `successful_payment` فقط |
| غياب مزود الدفع | كان ممكناً للمستخدم بدء مسار يوحي بإيداع فوري | عند غياب `PAYMENT_PROVIDER_TOKEN` يعرض البوت أن الدفع غير مهيأ ولا يغيّر الرصيد |
| إعادة الدفع | لم يكن هناك payload أو charge verification يمنع الاعتماد المكرر | payload مبني من transaction ref، مع مطابقة user وcurrency وminor amount وstatus، وcharge IDs محفوظة |
| إضافة الرصيد للإدارة | كانت تستخدم اسم ومسار `deposit` نفسه بعد تعطيل الإيداع المباشر | فُصلت إلى `admin_adjust_balance` مع `ADJUSTMENT` transaction صريحة، وبقيت محمية بـadmin handler |
| خدمات المتجر الآلية | كان `instant` ينتقل إلى `processing` دون executor أو provider أو تسليم | يُرفض checkout للخدمة الآلية برسالة صريحة حتى يوجد executor فعلي؛ manual/hybrid يبقيان في مسار paid/manual الذي ينفذه المشرف |
| تنزيل الوسائط | كانت الدوال تستخدم `effective_chat.send_audio/send_video/send_photo`، بينما الإرسال الحقيقي يجب أن يتم من Bot | أصبحت جميع الإرسالات تستخدم `bot.send_*` مع `chat_id`، ويمرر smart callback الـBot الحقيقي إلى downloader |
| voice chat | كان المسار يستهلك track ويرسل عبارة `playing in queue mode` عند غياب PyTgCalls/Pyrogram | أصبح fail-closed: لا يضيف المسار إلى قائمة تشغيل وهمية، ولا يسمح pause/resume/skip دون backend جاهز، ولا يعلن Now Playing دون تأكيد التشغيل |
| smart download adapter | الاسم `FakeUpdate` كان مضللاً رغم أن التنفيذ يعيد استخدام Telegram objects | أُعيدت تسميته `CallbackUpdateAdapter`، وهو adapter للسياق فقط، بينما كل الإرسال يمر عبر Bot API الحقيقي |

## قواعد الدفع الصحيحة

تتبع المنظومة الآن ترتيب Telegram الرسمي: إنشاء invoice باستخدام provider token، الرد على pre-checkout خلال مهلة Telegram، ثم متابعة التسليم أو اعتماد الرصيد بعد وصول `successful_payment`. لا تُعد transaction مكتملة بمجرد إرسال invoice أو الضغط على الزر. [1] [2]

> Telegram لا يعالج معلومات البطاقة بنفسه؛ مزود الدفع هو الذي يعالجها، ويجب على البوت استخدام provider token ثم متابعة pre-checkout وsuccessful payment قبل تنفيذ التسليم. [1]

## التحقق

| الاختبار أو invariant | النتيجة |
|---|---:|
| `python -m compileall -q -f .` | ناجح |
| suite الكاملة `pytest tests/ -q -W error` | **182 اختباراً ناجحاً** |
| اختبارات shop/payment/voice/media الجديدة | **9 اختبارات ناجحة** ضمن الملف المركّز |
| الإيداع المباشر القديم | مرفوض برسالة WalletError ولا يغير الرصيد |
| provider token فارغ | لا توجد فاتورة ولا credit تلقائي |
| invoice | يُرسل عبر `bot.send_invoice` مع payload وminor amount |
| pre-checkout غير صالح | يُرفض عبر `answer(ok=False)` |
| successful payment | يمر إلى confirm ويضيف الرصيد بعد Telegram receipt فقط |
| تحميل الوسائط | يستخدم Bot API `send_audio/send_video/send_photo` |
| voice backend غير جاهز | play يرفض الطلب ولا ينشئ queue تشغيل وهمية |
| direct user deposit callers | لا يوجد caller مباشر؛ المسار الإداري يستخدم adjustment منفصلاً |

## ما بقي غير مفعّل عمداً

الدفع الحقيقي يحتاج provider token صادر من BotFather ومزود دفع مربوطاً بحساب المالك؛ لا يمكن اختلاق هذا السر داخل الاختبارات. لذلك يبقى الإيداع معطلاً حتى يضع المالك `PAYMENT_PROVIDER_TOKEN` الحقيقي. كما أن voice chat الحقيقي يحتاج `TELEGRAM_API_ID` و`TELEGRAM_API_HASH` وPyrogram session ووجود backend PyTgCalls، ولذلك يرفض البوت الطلب بدلاً من ادعاء تشغيل صوت.

خدمات `instant` لا تزال غير متاحة حتى يُبنى executor حقيقي لكل provider. وجود حقول `api_endpoint` و`api_params` في schema لا يُعتبر تكاملاً؛ المطلوب مستقبلاً executor مع timeout وretry وidempotency وتوقيع/مصادقة provider ونتيجة تسليم قابلة للتدقيق. الخدمات اليدوية لا تُعرض مكتملة إلا بعد إجراء المشرف من لوحة الإدارة.

الفحص الحي مع Telegram API ومزود دفع وبوت صوت لم يُنفذ لعدم توفر credentials وبيئة خارجية حقيقية. اختبارات Bot API الخارجية تستخدم عزل handlers، بينما اختبارات Redis وقاعدة البيانات الموجودة في المشروع تستمر في استخدام الخدمات المحلية الحقيقية حيثما كان ذلك ممكناً.

## الملفات الأساسية

| الملف | التغيير |
|---|---|
| `config/settings.py` | `PAYMENT_PROVIDER_TOKEN` و`PAYMENT_CURRENCY` |
| `.env.example` | توثيق إعداد الدفع مع تعطيل افتراضي آمن |
| `src/shop/wallet_engine.py` | pending intent، validation، confirm، admin adjustment، وإيقاف direct deposit |
| `src/shop/handlers/wallet_handler.py` | invoice/pre-checkout/successful payment handlers |
| `src/shop/handlers/register.py` | تسجيل payment handlers |
| `src/shop/order_engine.py` | رفض instant بلا executor والتحقق من مالك الطلب |
| `src/shop/handlers/admin_handler.py` | استخدام adjustment الإداري |
| `src/features/media_downloader.py` | Bot API إرسال حقيقي |
| `src/features/soundcloud.py` | Bot API إرسال حقيقي |
| `src/features/instagram.py` | Bot API إرسال حقيقي |
| `src/features/smart_detect.py` | تمرير Bot الحقيقي وإزالة تسمية FakeUpdate |
| `src/features/voice_chat.py` | fail-closed وعدم ادعاء queue/playback |
| `tests/test_shop_real_operations.py` | اختبارات الدفع والتحميل والvoice |

## المراجع

[1]: https://core.telegram.org/bots/payments "Telegram Bot Payments API"

[2]: https://docs.python-telegram-bot.org/en/v22.5/examples.paymentbot.html "python-telegram-bot v22.5 Payment Bot example"
