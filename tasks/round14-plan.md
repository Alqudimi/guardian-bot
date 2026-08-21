# خطة تنفيذ الجولة الرابعة عشرة — منظومة مجموعات Guardian Bot

## النطاق

تهدف الجولة إلى تعميق منظومة المجموعات الموجودة فعلياً، لا إلى إعادة بناء المشروع. سيُحافظ التنفيذ على pipeline الحالي ذي الطبقات، Redis للإشارات الساخنة والإعدادات، PostgreSQL للتدقيق والعضوية، `python-telegram-bot` v22.8 للتحديثات والإجراءات، وGameSessionManager للألعاب. كل تعديل يجب أن يملك اختباراً يثبت مسار النجاح والفشل والحالة الحدية قبل اعتماده.

## ما تم التحقق منه في الفحص الأولي

| المجال | الموجود فعلياً | الملاحظة التصميمية |
|---|---|---|
| الإدخال | `message_handler.py` و`ChatMemberHandler.CHAT_MEMBER` وhandlers للأوامر/callbacks | يجب عدم تسجيل handlers متعارضة، مع احترام allowed updates وصلاحيات Telegram |
| moderation | orchestrator من DoS وnormalization وfast rules وflood وbehavioral وaccount intelligence وlink/media/AI وrisk/decision/action/audit | الأفضل إصلاح نقاط الربط القائمة بدلاً من بناء engine موازٍ |
| إعدادات المجموعة | Redis hash في `group_settings.py` مع moderation level، limits، patterns، smart responses، welcome/leave | يلزم توحيد الإعدادات التي ما زالت في key family منفصلة مثل language policy |
| spam/flood | sliding windows، burst، duplicate fingerprint، entropy، coordinated spam، media rate | يلزم فصل repeated content عن shared duplicate لتقليل false positives، وربط thresholds بإعدادات المجموعة |
| الحسابات المشبوهة | username/name flags، join velocity، cross-group bans، ID-based age heuristic | لا يجوز اعتبار user ID دليلاً على عمر الحساب أو كونه وهمياً؛ يجب تخفيض/إزالة الاعتماد غير القابل للتحقق |
| المحتوى | fast regex، normalization، group patterns، language guard، optional AI toxicity/NSFW | يلزم جعل الإشارة عالية الثقة لا تضيع في decision flow، ودعم درجات/استثناءات قابلة للتفسير |
| الإدارة | `_admin_only` يتحقق من allowlist و`get_chat_member`، أوامر settings/moderation/patterns/undo/leave | كل أمر جديد يجب أن يمر من نفس البوابة ويكتب audit دون arguments حساسة |
| الألعاب | Mafia وChameleon bot-native، Redis session، Chameleon scoreboard | لا تُضاف لعبة أو نقاط جديدة بلا contract عادل واختبارات حالة حقيقية |
| التفاعل | smart replies مع group setting/cooldown، rules، welcome/leave، grouphelp | أي رد جديد يحتاج enable flag وcooldown وdegradation واضح |

## قرارات المعمارية

أولاً، ستبقى إشارات مكافحة spam والمحتوى داخل `PipelineContext` وتُستهلك عبر risk/decision/action الموجود، مع إضافة حقول محددة فقط عندما تكون ضرورية للتفسير والتدقيق. ثانياً، ستستخدم إعدادات المجموعة الموجودة بدلاً من إنشاء مخزن إعدادات ثالث؛ وسيتم تقييم نقل language policy إلى `group_settings` مع الحفاظ على التوافق مع المفتاح الحالي إن كان ذلك ضرورياً.

ثالثاً، لن تُستخدم مؤشرات لا يستطيع Telegram إتاحتها فعلياً، مثل تاريخ إنشاء الحساب الحقيقي، لتقرير عقوبة. يمكن استعمال ID-based age heuristic كإشارة ضعيفة telemetry فقط إن بقيت خارج قرار العقوبة المباشر، أو إزالتها من risk إذا أثبتت الاختبارات أنها تسبب false positives. رابعاً، ستظل إجراءات الحذف والتقييد والحظر مشروطة بنجاح Telegram وصلاحيات البوت، مع تحديث `execution_status` وaudit بعد downgrade أو suppression.

خامساً، لن تُضاف AI dependency جديدة في هذه الجولة. سيُستفاد من AI الموجود اختيارياً فقط بعد مرور deterministic gates، مع fail-safe وresource limits، لأن الهدف هو تقوية النظام لا زيادة تكلفة أو زمن الاستجابة بلا دليل.

## مراحل التنفيذ وقبولها

### المرحلة 1: فحص وتثبيت baseline

يُحفظ reconnaissance والبحث الرسمي، ويُشغّل baseline كامل مع Redis محلي حقيقي. القبول هو تطابق baseline مع الحالة المسلمة، وعدم وجود ملفات مفقودة أو وظائف مفترضة.

### المرحلة 2: مكافحة spam وflood والسلوك المشبوه

ستُراجع duplicate keys وcoordinated keys وsliding windows، ثم تُضاف إعدادات per-group فقط عند الحاجة، مثل تفعيل/تعطيل anti-spam أو thresholds محدودة وآمنة. ستُراجع signals الخاصة بـjoin velocity وrate anomaly وaccount heuristics لتجنب معاقبة المستخدم بناءً على user ID أو اسم فقط. يجب أن تشمل الاختبارات concurrency، الرسائل المتكررة من مستخدم واحد، رسالة شائعة من مستخدمين مختلفين، flood، media flood، Redis failure، والحدود غير الصالحة.

### المرحلة 3: المحتوى العربي والمخالفات

ستُراجع normalization لمعالجة whitespace والتكرار والرموز والتحايل العربي دون تدمير النصوص المشروعة، وستُربط group patterns بمستوى/فئة واضحين إن كان ذلك ضرورياً. ستُصلح أي fast-rule decision لا يصل إلى short-circuit أو يُستبدل لاحقاً بقرار allow. ستُضاف اختبارات false-positive للكلمات داخل كلمات أخرى، العربية واللهجات، Unicode confusables، والاستثناءات/whitelist.

### المرحلة 4: الإدارة وأدوات الأعضاء

ستُراجع أوامر الإدارة الحالية والـhelp وsettings، ويُوحّد مسار الصلاحيات والتدقيق. ستُضاف فقط أدوات ذات صلة، مثل عرض حالة حماية المجموعة أو مراجعة مختصرة للأحداث، إذا كان writer/reader موجودين فعلياً. أي أمر إداري جديد يجب أن يرفض private/non-group contexts عند الحاجة، ويتعامل مع Telegram errors برسالة عامة.

### المرحلة 5: الألعاب والتفاعل والتكامل

ستُراجع عدالة scoring الحالية وidempotency والـsession cleanup، ويُحسن التكامل مع group settings وuser stats فقط حيث توجد persistence حقيقية. سيُضبط smart interaction لمنع الإغراق، وتُراجع triggers والـcooldowns والـbackground task lifecycle. لا تُضاف ألعاب عشوائية أو wrappers خارجية.

### المرحلة 6: الاختبارات والتحقق

يجب تشغيل compileall، suite كاملة مع `-W error`، pip check، pip-audit، وفحوصات Ruff. تُضاف اختبارات لكل تعديل مع Redis حقيقي عند توفره، وتُفصل بوضوح الاختبارات المحلية عن الاختبارات الحية التي تحتاج Telegram token أو PostgreSQL أو خدمات خارجية.

### المرحلة 7: التوثيق والتسليم

يُحدّث README وAGENT وtodo، وتُكتب `tasks/round14-report.md` مع جدول الملفات والتغييرات ونتائج الاختبارات والحدود. يُجهز `Guardian-bot-round14-groups-pass.zip` دون cache أو `.pyc` أو `.db`، مع SHA-256 وفحص integrity.

## المخاطر والضوابط

| الخطر | الأثر | الضبط |
|---|---|---|
| false positive من duplicate أو account heuristic | عقوبة مستخدم سليم | فصل الإشارات، عدم العقوبة من مؤشر واحد، اختبارات سلبية، whitelist |
| تغيير قرار fast rule بلا short-circuit | السماح بمحتوى عالي الخطورة أو audit drift | اختبار end-to-end من layer إلى action، ومراجعة decision precedence |
| Redis latency/failure | فقدان rate limits أو settings | defaults آمنة، fail-safe للعمليات الحساسة، وعدم إعلان نجاح غير مثبت |
| صلاحيات Telegram غير كافية | فشل delete/mute/ban أو رسائل مضللة | catch Telegram errors، execution status، ورسائل عامة |
| زيادة ردود البوت | spam من النظام نفسه | setting per-group، cooldown، background registry، وحدود إرسال |
| تكرار event بسبب concurrency | نقاط أو عقوبات مكررة | Redis atomic reservation/locks وidempotency markers |
| اختلاف Bot API عن المكتبة المثبتة | runtime failures | استخدام توثيق v22.8 وBot API الرسمي وعدم إدخال methods غير مدعومة |

## تعريف الإنجاز

لا تُعتبر الجولة مكتملة إلا إذا كانت كل وظيفة جديدة موصولة من handler أو event إلى business logic ثم persistence/provider والنتيجة، ولها اختبار نجاح وفشل وحد أدنى من الحالات الحدية. يجب أن يوضح التقرير ما لم يُنفذ، خصوصاً الاختبارات الحية أو الوظائف التي تحتاج Telegram capabilities لا تتوفر في sandbox.
