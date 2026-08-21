# نتائج الجولة الثالثة

## التدقيق

أعيد تشغيل خط الأساس من الحالة الحالية: `compileall` ناجح و176 اختباراً ناجحاً مع `pytest -W error`. أظهر فحص Alembic أن `heads` لا يحتوي revisions، وأن `migrations/script.py.mako` مفقود، وأن `migrations/env.py` لا يستورد نماذج المتجر رغم اعتمادها على Base نفسه.

## الإصلاحات

تم استيراد نماذج المتجر داخل Alembic metadata، وإضافة قالب Alembic القياسي، وتوليد baseline revision باسم `e28d7e1c3e09_initial_guardian_schema.py` من metadata core والمتجر. تم إصلاح import `Text` الناقص في revision، ثم تحويل JSONB في migration إلى `sa.JSON().with_variant(postgresql.JSONB(), "postgresql")` حتى يحافظ PostgreSQL على JSONB ويعمل SQLite في التحقق المحلي.

تم اكتشاف فشل `create_all` في development مع SQLite بسبب JSONB المباشر في نماذج core والمتجر. عولج ذلك بتعريف `JSON_TYPE` مركزي في `src/db/models.py` واستخدامه في core وshop models.

أضيفت سياسة `AUTO_CREATE_TABLES`: يسمح development بالإنشاء المريح، بينما يرفض production وstaging تفعيله، ويمنع `init_db` إنشاء schema في production إذا لم توجد `alembic_version`. يجب تنفيذ `alembic upgrade head` قبل تشغيل production.

## التحقق

اختبار SQLite migration الفعلي نجح في المراحل الثلاث: `alembic upgrade head` و`alembic check` و`alembic downgrade base`. كما نجح probe `init_db` في development، وأثبت رفض production غير المهاجر. بعد إضافة اختبارات schema gate وmetadata أصبح مجموع الاختبارات **179 اختباراً ناجحاً** مع `pytest -W error`.

## القيود

لم يُختبر upgrade على PostgreSQL حقيقي لعدم توفر خادم PostgreSQL في البيئة. تم الحفاظ على JSONB في PostgreSQL عبر variant، لكن يجب تنفيذ smoke test على PostgreSQL staging قبل اعتماد migration في production. لم تُنفذ أوامر Telegram الحية أو بناء Docker لغياب token ومجموعة اختبار وDocker daemon.
