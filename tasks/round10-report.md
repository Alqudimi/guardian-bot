# تقرير الجولة العاشرة — Guardian Bot

**المؤلف:** Manus AI  
**نوع الجولة:** مراجعة شاملة موجهة بالأدلة مع تحسينات تشغيلية وأمنية عالية القيمة  
**الحالة:** مكتملة داخل البيئة المعزولة، مع قيود التكاملات الحية الموضحة أدناه

## الملخص التنفيذي

بدأت الجولة من baseline فعلي بلغ **198 اختباراً ناجحاً**. أُجري جرد للمجلدات والمكونات ومسارات handlers والأوامر وcallbacks والمهام الخلفية والطلبات الخارجية، ثم رُتبت الفجوات حسب أثرها على سلامة المال، الملكية، التنفيذ الخارجي، lifecycle، وSSRF. بعد التنفيذ أصبحت suite تحتوي على **209 اختبارات ناجحة**.

أعلى مشكلة مكتشفة كانت في المتجر: كان إنشاء الطلب يعتمد على السعر الموجود في `context.user_data`، وكان استهلاك الكوبون يحدث قبل الدفع مع عدم ربط `CouponUsage` بصورة موثوقة بالطلب الناجح، كما كان الاسترداد لا يفرض ملكية الطلب من طبقة المحرك. عولجت هذه المسارات داخل معاملات قاعدة البيانات مع إعادة تحقق server-side وrow locks.

> لا تُعتبر الوظيفة الخارجية ناجحة إلا بعد نجاح العملية الأساسية الفعلية، ولا تُعتبر حالة المتجر أو الـcallback موثوقة لمجرد أن payload وصل إلى handler.

## الأقسام التي تمت مراجعتها

| القسم الفعلي | الملفات/المسارات التي شملها التدقيق | نتيجة الجولة |
|---|---|---|
| الحماية والإشراف | `src/pipeline/`، `src/layers/`، `src/security/`، `src/management/` | حافظت الجولة على إصلاحات الجولة التاسعة، وأضافت حماية redirect في طبقة SSRF وراجعت مسارات execution وcallbacks القائمة |
| المجموعات والإدارة | `message_handler`، `admin_commands`، group settings، rules، welcome، modlog، reports | أضيف lifecycle آمن لمهمة حذف الترحيب، وقُويت callbacks الإدارية للطلبات ومنع تسريب الأخطاء |
| الألعاب | `games/manager.py`، `games/session.py`، Mafia، Chameleon | جرى التحقق من wiring والاختبارات وعدم إدخال تغيير غير لازم بعد اكتمال الجولة الرابعة والخامسة |
| المتجر | catalog/pricing، order، coupon، wallet، support، notifications، admin handlers | نُفذت التحسينات الرئيسية في سلامة السعر والكوبون والدفع والاسترداد والفشل والإشعارات |
| الميزات | Azkar، Quran، quotes، media downloader، Instagram، SoundCloud، smart detect، voice | جرى تدقيق المهام الخلفية؛ نُقلت مسارات التنزيل والاستجابات التلقائية إلى registry، وصُحح callback data الخاص بالتنزيل |
| التخزين والمهام | SQLAlchemy async، Redis، Alembic، Celery | تم احترام حدود المعاملة الحالية، واستخدمت Redis tokens قصيرة للروابط المؤقتة؛ بقي Celery hot-path خارج التفعيل لغياب سياسة executor فعلية |

## التغييرات المنفذة بالتفصيل

### سلامة الطلب والتسعير

أصبح `create_order` يعيد جلب `ShopUser` و`Service` من قاعدة البيانات داخل transaction، ويعامل السعر القادم من Telegram state كبيان عرض غير موثوق. يحسب السعر من `calculate_service_price`، ويتحقق من تفعيل الخدمة، المخزون، الحد الأدنى والأقصى للكمية، المستوى المطلوب، وتكرار الخدمة داخل الطلب. بهذه الطريقة لا يكفي تعديل `unit_price` في `user_data` لتغيير المبلغ المحصل.

أصبح `pay_order` يعزل الطلب والمستخدم بـ`with_for_update`، ويعيد التحقق من الخدمة والسعر والمخزون والكوبون والرصيد قبل الخصم. إذا تغير السعر أو الخصم بين شاشة التأكيد والتنفيذ، يُلغى الطلب وتُحرر قيمة الحجز بدلاً من تحصيل سعر قديم أو غير متسق. كما أصبح الانتقال بعد الدفع إلى `PROCESSING` متوافقاً مع نصوص الواجهة ومسار المعالجة اليدوية.

### الكوبونات والمعاملات المالية

فُصل حساب الخصم عن استهلاك الكوبون. `apply_coupon` يحسب الخصم ولا يزيد `usage_count`، بينما يعاد التحقق من الكوبون داخل معاملة الدفع، ثم يُزاد العداد ويُضاف `CouponUsage` بعد نجاح الخصم فقط. يشمل التحقق الصلاحية الزمنية، الحد العام، الحد لكل مستخدم، المستخدمين المسموحين، مستويات الحساب، والخدمات المؤهلة.

أصبح `refund_order` يفرض ملكية المستخدم عندما يُستدعى من واجهة المستخدم، ويقصر الاسترداد على الطلبات المدفوعة أو قيد المعالجة أو المكتملة، ويمنع الاسترداد المكرر ويستخدم row lock. كما أضيف مسار مالي للفشل النهائي: بعد استنفاد retries يُرد مبلغ الطلب إلى الرصيد وتُسجل معاملة refund واحدة، مع تحديث الإجماليات الحسابية.

### الإدارة والإشعارات

قُويت admin order callbacks بحيث ترفض action أو ID غير صالحين، ولا تعرض نصوص الاستثناءات الداخلية للمستخدم. أصبح إكمال الطلب يفرض حالة انتقال صحيحة ويحمّل المستخدم قبل الإشعار، وأصبح الفشل الإداري يرسل إشعاراً للمستخدم بعد نجاح تغيير الحالة. بقيت الصلاحية الإدارية نفسها محكومة بالتحقق الموجود في المشروع.

### المهام الخلفية وlifecycle

أضيف `src/utils/background_tasks.py` كـregistry مشترك يحتفظ بمراجع المهام، يلتقط الاستثناءات ويسجلها، ويدعم إلغاء المهام وانتظارها في `post_shutdown`. نُقلت إليه مهام تنزيل YouTube/Instagram/SoundCloud، واستجابات Quran/Azkar في `smart_detect`، وحذف رسائل الترحيب. يمنع ذلك المهام غير المُدارة ويجعل الإغلاق أكثر نظافة.

### smart detection وTelegram callback data

كان smart detection يضع URL خاماً قد يصل إلى 200 حرف في `callback_data`، بينما callback data في Telegram محدود الحجم. استُبدل ذلك بـtoken قصير عشوائي مخزن في Redis لمدة عشر دقائق ومربوط بـ`chat_id` و`user_id`، مع استهلاك ذري عبر `getdel`. إذا تعذر Redis أو انتهت الصلاحية يُرفض التنزيل بدلاً من إنشاء مسار وهمي.

كما صُحح خلل فعلي في PTB v22: كان الكود يحاول تعديل `InlineKeyboardMarkup.inline_keyboard` بعد الإنشاء، وهو كائن مجمد. أصبحت الصفوف تُبنى قبل إنشاء markup.

### حماية SSRF والredirects

أصبح `safe_fetch` و`link_analysis._expand_url` لا يستخدمان التتبع التلقائي للredirect. يتحقق كل مسار من scheme وhostname وDNS والعنوان الناتج قبل إرسال الطلب التالي، مع حد redirect واضح وحماية من `Location` بلا قيمة. هذا يقلل خطر أن يبدأ الرابط بعنوان عام ثم يقفز إلى عنوان داخلي في redirect وسيط.

## الاختبارات المنفذة

| الاختبار | النتيجة |
|---|---:|
| baseline قبل الجولة | 198 ناجحاً |
| اختبارات سلامة المتجر الجديدة | 5 ناجحة |
| اختبارات lifecycle وsmart token وSSRF redirect | 6 ناجحة |
| suite الكاملة `pytest tests/ -q -W error` | **209 ناجحة** |
| `python -m compileall -q -f .` | ناجح |
| `pip check` | `No broken requirements found` |
| `pip-audit -r requirements.txt` | `No known vulnerabilities found` |
| Ruff correctness على الملفات الجديدة/المعدلة | ناجح: `E9,F401,RUF012` |

تغطي الاختبارات الجديدة السعر authoritative، السعر القديم، حدود الكوبون واستهلاكه بعد الدفع، ملكية الاسترداد، idempotency، رد الرصيد عند الفشل النهائي، registry والإلغاء، token binding وcallback size، ومنع متابعة SSRF redirect إلى عنوان داخلي. مجموع الاختبارات الجديدة في الجولة العاشرة هو **11 اختباراً**: خمسة لمسارات المتجر وستة للـlifecycle والـsmart token وSSRF.

## الملفات الرئيسية المعدلة أو المضافة

| الملف | الغرض |
|---|---|
| `src/shop/order_engine.py` | server-side pricing، row locks، الدفع، الفشل النهائي، الاسترداد والانتقالات |
| `src/shop/coupon_engine.py` | التحقق داخل session، الفصل بين discount وconsumption، usage recording |
| `src/shop/service_engine.py` | كشف دالة التسعير server-side لإعادة استخدامها |
| `src/shop/handlers/order_handler.py` | ملكية التفاصيل والاسترداد ومعالجة callbacks غير الصالحة |
| `src/shop/handlers/admin_handler.py` | حماية admin callbacks والإشعارات وعدم تسريب الأخطاء |
| `src/utils/background_tasks.py` | registry وcleanup للمهام الخلفية |
| `main.py` | إلغاء background tasks ضمن `post_shutdown` |
| `src/features/smart_detect.py` | Redis tokens، callback validation، markup fix، task registry |
| `src/features/media_downloader.py`، `instagram.py`، `soundcloud.py` | task lifecycle آمن |
| `src/management/welcome_manager.py` | task lifecycle لحذف رسائل الترحيب |
| `src/security/ssrf_guard.py`، `src/layers/link_analysis.py` | فحص كل redirect قبل المتابعة |
| `tests/test_round10_shop_integrity.py` | اختبارات المتجر والتدفقات المالية |
| `tests/test_round10_lifecycle.py` | اختبارات المهام، tokens، callbacks، وSSRF |
| `tasks/round10-plan.md`، `round10-research-notes.md`، `round10-final-validation.txt` | خطة وأدلة وسجل تحقق الجولة |

## المشكلات المتبقية والقيود

لم يُنفذ اختبار Bot API حي، أو PostgreSQL حي، أو دفع Telegram فعلي، أو yt-dlp فعلي، أو voice provider فعلي، لأن البيئة لا تحتوي credentials أو خدمات تشغيل خارجية. لذلك لا يدّعي التقرير نجاح external side effects غير المختبرة. يجب تنفيذ smoke tests في staging قبل production، خصوصاً الدفع، callbacks، membership restrictions، وvoice lifecycle.

ما زال instant fulfillment غير مفعّل عندما لا يوجد executor/provider فعلي، وما زال Celery hot-path مؤجلاً حتى تُعرّف سياسة enqueue/retry/idempotency/monitoring. كما بقيت مخالفات Ruff العامة التاريخية خارج نطاق الجولة، بينما اجتازت قواعد correctness المحددة للملفات التي أُضيفت أو عُدلت في هذه الجولة.

لا تزال اختبارات PostgreSQL وRedis الحية وDocker build وend-to-end Telegram غير متاحة في sandbox، رغم أن الاختبارات المحلية تستخدم SQLite async وmocks موجهة للواجهات الخارجية عند الحاجة. ينبغي عدم اعتبار ذلك بديلاً عن staging validation.

## المراجع الرسمية

[1]: https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.application.html "python-telegram-bot v22.8 Application documentation"
[2]: https://redis.io/docs/latest/develop/clients/redis-py/async/ "Redis asyncio client documentation"
[3]: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html "SQLAlchemy 2.0 asyncio documentation"
