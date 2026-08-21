# Guardian Bot

**Guardian Bot** هو نظام Telegram متخصص في حماية المجموعات والإشراف عليها وإدارة محتواها، مع أدوات إدارية وألعاب داخلية وتفاعل ذكي اختياري. يعتمد المشروع على بنية طبقية قابلة للاختبار، ويفصل بين استقبال تحديث Telegram، والتحقق من الصلاحيات، ومنطق القرار، والتخزين، وتنفيذ إجراءات Telegram، والتدقيق.

> Guardian Bot لا يدّعي حماية مطلقة من spam أو raid أو الحظر. النتيجة الفعلية تعتمد على وصول تحديثات Telegram، وصلاحيات البوت داخل المجموعة، وحدود Bot API، ومعدلات الطلب، وتوفر الخدمات الاختيارية.

## الحالة الحالية

| المجال | الحالة الفعلية |
|---|---|
| اللغة والتشغيل | Python 3.11+ مع `async/await` |
| Telegram | `python-telegram-bot` v22.8؛ الاختبار الحي يحتاج token ومجموعة staging |
| قاعدة البيانات | PostgreSQL مدعومة للإنتاج، وSQLite مستخدمة في اختبارات الوحدات |
| Cache وatomic coordination | Redis 7+ |
| المهام الخلفية | Celery 5.6 مع Redis broker؛ lifecycle واختبارات smoke موثقة |
| الحاويات | Docker وCompose مدعومان؛ image الجولة 22 بُنيت محلياً |
| الاختبارات | 271 اختباراً ناجحاً مع `-W error` في آخر تحقق موثق |
| الدفع | fail-closed؛ لا يُفعل الإيداع بلا provider token ومسار Telegram payment مكتمل |
| instant fulfillment | معطل حتى إضافة executor/provider حقيقي موثق وقابل للاختبار |
| Mafia scoring | غير مفعل عمداً؛ اللعبة لا تملك scoring contract حالياً |

## ابدأ من هنا

| أريد أن... | أقرأ |
|---|---|
| أشغل نسخة محلية بسرعة | [`docs/getting-started/quickstart.md`](docs/getting-started/quickstart.md) |
| أضبط متغيرات البيئة | [`docs/getting-started/configuration.md`](docs/getting-started/configuration.md) |
| أشغل PostgreSQL وRedis وCelery | [`docs/getting-started/docker.md`](docs/getting-started/docker.md) و[`docs/runbooks/local-stack.md`](docs/runbooks/local-stack.md) |
| أفهم مسار الإشراف | [`docs/architecture/moderation-pipeline.md`](docs/architecture/moderation-pipeline.md) |
| أضيف ميزة بأمان | [`docs/development/contributing.md`](docs/development/contributing.md) |
| أتحقق من الجودة | [`docs/development/testing.md`](docs/development/testing.md) |
| أتعامل مع حادث تشغيل | [`docs/operations/runbook.md`](docs/operations/runbook.md) |
| أراجع حدود Telegram | [`docs/runbooks/telegram-staging.md`](docs/runbooks/telegram-staging.md) |

## البنية المعمارية المختصرة

```text
Telegram Update
      │
      ▼
handlers/message_handler.py
      │  validation, chat type, admin authorization
      ▼
pipeline/orchestrator.py
      │
      ├─ normalization
      ├─ fast rules
      ├─ flood / behavior
      ├─ link / media / AI (optional, fail-safe)
      ├─ risk scoring
      ├─ decision with high-confidence short-circuit
      ├─ action execution through Telegram API
      └─ audit and persistence
              │
              ├─ Redis: settings, cooldowns, dedup, sessions, coordination
              ├─ PostgreSQL: profiles, moderation events, group state, shop state
              └─ Celery: idempotent background work and scheduled maintenance
```

تدخل الرسائل من handlers ثم تمر عبر pipeline بالترتيب. لا تُعتبر العملية ناجحة للمستخدم إلا بعد نجاح mutation الأساسي، مثل `delete_message` أو `restrict_chat_member` أو `ban_chat_member` أو الكتابة المؤكدة إلى التخزين. تفشل الوظائف الاختيارية بشكل معزول ولا تعطل مسار الحماية الأساسي.

## الميزات الموجودة فعلياً

يضم المشروع مكافحة spam وflood، duplicate وcoordinated signals، blacklist وwhitelist، تحليل الروابط وphishing heuristics، moderation للغة العربية، معالجة media اختيارية، CAPTCHA، raid lockdown، إعدادات المجموعة، أوامر الإدارة، التدقيق، `/undo`، smart interaction، ومراقبة الحسابات ضمن البيانات التي يتيحها Bot API فعلياً.

الألعاب المملوكة للمشروع هي **Mafia** و**Chameleon** فقط. تحفظ جلساتهما عبر `GameSessionManager`، وتتحقق callbacks من payload وchat ownership. لا تفتح الألعاب WebApp خارجية ولا تعتمد على بوت آخر. Mafia لا تظهر نقاطاً اصطناعية لأن scoring contract غير موجود.

## التشغيل السريع

```bash
cd /home/ubuntu/guardian_work
cp .env.example .env
# حرر .env وضع TELEGRAM_BOT_TOKEN وبيانات PostgreSQL وRedis الحقيقية
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python main.py
```

للاختبارات المحلية التي تحتاج Redis حقيقياً، راجع [`docs/development/testing.md`](docs/development/testing.md). لا تستخدم `.env.round22.local` أو أي ملف أسرار محلي في GitHub؛ ملفات البيئة مستبعدة من `.gitignore`.

## أوامر الإدارة والألعاب

المرجع الكامل مع متطلبات المجموعة والصلاحيات موجود في [`docs/reference/commands.md`](docs/reference/commands.md). أهم الأوامر تشمل `/status`، `/settings`، `/setmoderation`، `/setlimits`، `/setraid`، `/setwarnlimit`، `/whitelist`، `/blacklist`، `/undo`، `/groupaddpattern`، `/groupremovepattern`، `/grouppatterns`، `/setsmart`، `/setleave`، `/games`، `/play mafia`، `/play chameleon`، `/stopgame`، و`/gamescores`.

## اختبارات وتحقيق الجودة

الأمر الرسمي للتحقق قبل التسليم هو:

```bash
cd /home/ubuntu/guardian_work
export PYTHONPATH=.
export TELEGRAM_BOT_TOKEN=123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
export TELEGRAM_ADMIN_IDS=123456789
export DATABASE_URL=sqlite+aiosqlite:///./baseline_test.db
export REDIS_URL=redis://localhost:6379/0
python -m compileall -q -f .
python -m pytest tests/ -q -W error
pip check
pip-audit -r requirements.txt
ruff check --select E9,F401,RUF012 <changed-files>
```

هذه الأوامر لا تثبت Telegram live أو PostgreSQL production أو providers خارجية. إثبات تلك المسارات يحتاج خدمات وcredentials وبيئة staging حقيقية، كما هو موضح في [`docs/operations/production-readiness.md`](docs/operations/production-readiness.md).

## الأمان والحدود

لا تُسجل tokens أو secrets أو arguments الحساسة. أوامر الإدارة تتحقق من `is_authorized_admin` ومن رتبة Telegram داخل المجموعة. إعدادات المجموعة canonical داخل manager واحد وRedis hash، ومفاتيح Redis تستخدم prefix. rate limits وdedup وcooldowns تعتمد على reservations ذرية أو معاملات مناسبة. account age لا يُستنتج من Telegram user ID؛ إذا لم تتوفر بيانات فعلية يبقى `unknown`.

راجع [`SECURITY.md`](SECURITY.md) و[`docs/security/threat-model.md`](docs/security/threat-model.md) قبل تشغيل bot في مجموعة حقيقية.

## هيكل المشروع

```text
main.py                       نقطة التشغيل
config/                       إعدادات Pydantic
src/handlers/                 تسجيل handlers وواجهات Telegram
src/pipeline/                 orchestration وraid detection
src/layers/                   طبقات normalization إلى audit
src/management/               group settings وعمليات الإدارة
src/games/                    Mafia وChameleon وGameSessionManager
src/features/                 الميزات الاختيارية، مثل الصوت والتفاعل
src/db/                       SQLAlchemy models وsessions
src/tasks/                    Celery app والمهام الخلفية
src/utils/                    Redis، logging، lifecycle، anti-ban
migrations/                   Alembic revisions
 tests/                       pytest وpytest-asyncio
 docs/                        التوثيق التشغيلي والمعماري والتعليمي
 tasks/                       تقارير التحقق التاريخية وسجلات الجولات
 .github/                     قوالب GitHub وworkflow الجودة
```

## المساهمة

ابدأ من [`CONTRIBUTING.md`](CONTRIBUTING.md). لا تضف storage manager موازياً، ولا تستخدم raw `asyncio.create_task` لمسار طويل، ولا تعلن نجاحاً قبل mutation حقيقية. كل تغيير يجب أن يضيف اختبار نجاح واختبار رفض واختبار فشل مناسباً لمساره.

## التوثيق التاريخي

تقارير الجولات 1–22 موجودة في `tasks/`، وآخر حزمة محلية معتمدة موصوفة في `tasks/round22-report.md` و`tasks/round22-final-validation.txt`. هذه الملفات أدلة تحقق تاريخية وليست بديلاً عن اختبار البيئة الحالية.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://docs.python-telegram-bot.org/en/v22.8/ "python-telegram-bot v22.8 documentation"
[3]: https://docs.celeryq.dev/en/stable/ "Celery stable documentation"
[4]: https://redis.io/docs/latest/ "Redis documentation"
[5]: https://docs.docker.com/compose/ "Docker Compose documentation"
