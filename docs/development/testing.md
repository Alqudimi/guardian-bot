# الاختبارات والتحقق

## بوابة التحقق الرسمية

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

## ما تغطيه الاختبارات

تغطي suite طبقات الحماية والإعدادات وRedis والتسجيل ومسارات الألعاب والدفع fail-closed وCelery lifecycle ومعالجة الأخطاء. آخر تحقق موثق للجولة 22 انتهى بـ271 اختباراً ناجحاً مع PostgreSQL وRedis محليين.

## Redis integration

تحتاج اختبارات Redis خدمة محلية حقيقية. استخدم prefix اختبارياً ونظف keys والجلسات في fixture teardown. لا تشغل tests المتوازية على namespace الإنتاجي.

## Telegram handlers

لكل handler أو callback جديد اختبر group/private، admin/non-admin، payload صحيح/خاطئ، ownership، success، provider failure، وTelegram error. الاختبارات mocks لا تثبت Telegram live.

## games

عند تعديل لعبة شغل اختبارات اللعبة وsuite كاملة. اختبر استعادة session، stop المتكرر، callback cross-chat، scoreboard، وفشل Redis. Mafia لا تحصل على scoreboard غير متعاقد عليه.

## اختبار حي منفصل

الاختبار الحي يحتاج token ومجموعة staging وPostgreSQL/Redis staging. ابدأ dry-run، استخدم مجموعة مملوكة، واحتفظ بسجل mutation الفعلي. لا تستخدم user أو group production في suite.
