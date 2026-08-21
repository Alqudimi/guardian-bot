# التشغيل باستخدام Docker

## الهدف

يوفر Docker بيئة قابلة للتكرار لتشغيل bot وخدمات PostgreSQL وRedis وCelery. استخدم Compose للتطوير أو staging المقيد، ولا تعتبره وحده خطة production عالية التوافر.

## قبل التشغيل

تحقق من توفر Docker وCompose والمساحة:

```bash
docker --version
docker compose version
docker system df
```

بناء image قد يحتاج مساحة كبيرة بسبب Python dependencies والنماذج الاختيارية. لا تحذف volumes الإنتاجية عشوائياً؛ افحصها أولاً.

## إعداد البيئة

```bash
cp .env.example .env
chmod 600 .env
# حرر .env قبل تشغيل compose
```

لا تضع `.env` داخل image أو archive. يضمن `.gitignore` استبعاد ملفات البيئة، لكن يجب مراجعة `git diff` و`git status` قبل push.

## التشغيل

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 bot
```

إذا كان اسم خدمة bot مختلفاً في `docker-compose.yml`، استخدم الاسم الموجود في الملف بدلاً من `bot`. طبّق migrations ضمن lifecycle واضح قبل استقبال تحديثات:

```bash
docker compose run --rm bot alembic upgrade head
```

## فحوص smoke

```bash
docker compose exec redis redis-cli ping
docker compose exec postgres pg_isready
docker compose ps
```

يجب أن تظهر حالة Redis وPostgreSQL healthy أو running حسب healthcheck المطبق. لا تعلن readiness إذا كان bot متصلاً بـRedis لكن migration state غير صحيحة.

## Celery

في بيئة Compose منفصلة شغل worker وbeat حسب service definitions الحالية، ثم تحقق من log task حقيقي أو ping:

```bash
docker compose logs --tail=100 celery-worker
docker compose logs --tail=100 celery-beat
```

لا تستخدم `asyncio.create_task` لمسار طويل داخل handler. lifecycle الخلفي موثق في [`../architecture/data-and-lifecycle.md`](../architecture/data-and-lifecycle.md).

## الإيقاف والتنظيف

```bash
docker compose down
```

لا تستخدم `docker compose down -v` إلا إذا كنت تقصد حذف بيانات PostgreSQL وRedis. عند فشل build بسبب امتلاء المساحة، افحص `docker system df` واحذف artifacts غير المستخدمة بعد مراجعة أثرها.

## ملاحظات الجولة 22

تم بناء image `guardian-bot:round22` محلياً بعد معالجة مشكلة مساحة Docker، ونجح runtime smoke مع PostgreSQL وRedis. هذا إثبات محلي فقط؛ لا يثبت registry push أو production rollout أو Telegram live.

## المراجع

[1]: https://docs.docker.com/compose/ "Docker Compose documentation"
[2]: https://docs.docker.com/build/ "Docker Build documentation"
