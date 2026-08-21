# المساهمة في Guardian Bot

الدليل التفصيلي موجود في [`docs/development/contributing.md`](docs/development/contributing.md). قبل فتح PR، اقرأ `AGENT.md` و`README.md` ومرجع الاختبارات.

## الحد الأدنى قبل الطلب

```bash
python -m compileall -q -f .
python -m pytest tests/ -q -W error
pip check
pip-audit -r requirements.txt
```

شغل Ruff correctness على الملفات المعدلة فقط إذا كان الفحص العام يحتوي مخالفات تاريخية خارج نطاق التغيير. اشرح في PR ما اختُبر محلياً وما لم يُختبر مع Telegram أو providers حقيقية.

## معيار القبول

يجب أن يكون التغيير موصولاً بمسار التنفيذ الفعلي، وأن يملك owner واضحاً، واختبار نجاح ورفض وفشل مناسباً. لا تُضاف mock success أو storage موازية أو ادعاءات حماية مطلقة.
