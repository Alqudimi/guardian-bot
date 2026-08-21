## الهدف

اشرح المشكلة والنتيجة المتوقعة.

## التغيير

اذكر الملفات والمسار الفعلي من handler إلى service/storage/provider إلى النتيجة.

## الاختبارات

- [ ] `python -m compileall -q -f .`
- [ ] `python -m pytest tests/ -q -W error`
- [ ] `pip check`
- [ ] `pip-audit -r requirements.txt`
- [ ] Ruff correctness للملفات المعدلة

## حدود التحقق

اذكر بوضوح ما اختُبر محلياً وما لم يُختبر مع Telegram live أو PostgreSQL production أو providers خارجية.

## الأمان

- [ ] لا توجد أسرار أو بيانات شخصية في diff/logs.
- [ ] authorization وchat type وcallback ownership مغطاة عند الحاجة.
- [ ] لا يوجد mock success أو false success.
