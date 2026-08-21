# ملاحظات البحث للجولة العاشرة

## مصادر رسمية

| المصدر | الخلاصة المرتبطة بالمشروع |
|---|---|
| [python-telegram-bot v22.8 Application](https://docs.python-telegram-bot.org/en/v22.8/telegram.ext.application.html) | المشروع يستخدم واجهة async في PTB v22.8؛ يجب احترام lifecycle الخاص بـ Application وعدم اعتبار callback أو task ناجحاً قبل اكتمال العملية الخارجية. |
| [Redis asyncio client](https://redis.io/docs/latest/develop/clients/redis-py/async/) | `redis.asyncio` هو واجهة async الرسمية؛ مسارات state وrate-limit تحتاج إدارة اتصال وإغلاقاً صريحاً واستخدام معاملات/عمليات ذرية عند الحاجة. الصفحة تعذر استخراجها آلياً في هذه الجولة، لذلك لا يُبنى عليها ادعاء تفصيلي غير متحقق. |
| [SQLAlchemy 2.0 asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html) | توضح الوثائق أن `AsyncSession` يمثل حالة/معاملة stateful ولا ينبغي مشاركته بين مهام concurrent؛ يجب إبقاء حدود المعاملات واضحة وتجنب implicit I/O في async paths. |

## قاعدة الاستخدام

استُخدمت هذه المصادر للتحقق من اتجاهات التنفيذ فقط، بينما تحديد الفجوات الفعلية للجولة يعتمد على الكود والاختبارات داخل المستودع. لا توجد إضافة dependency أو تغيير معماري مبني على مصدر خارجي وحده.
