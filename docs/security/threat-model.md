# نموذج التهديد

## الأصول

الأصول الأساسية هي Telegram token، كلمات مرور PostgreSQL وRedis، بيانات الأعضاء والأحداث، إعدادات المجموعات، game sessions، سجلات الدفع، وقرارات moderation. أي تسريب لهذه البيانات قد يتيح انتحال bot أو كشف بيانات المجموعة أو تغيير الحالة.

## الجهات المهددة

يشمل النموذج spammer، raid coordinator، مستخدم يحاول تجاوز admin authorization، attacker يستغل callback payload، مزود خارجي غير متاح أو خبيث، وتسريب credentials من بيئة التشغيل. لا يفترض النموذج أن Telegram يسلّم كل update أو أن network provider متاح دائماً.

## الضوابط

| الخطر | الضابط |
|---|---|
| تنفيذ أمر إداري من private chat أو عضو عادي | group chat check ثم `is_authorized_admin` ثم `get_chat_member` |
| callback cross-chat أو cross-user | تحقق payload وchat ownership وuser ownership |
| race في cooldown/dedup/warn/raid | Redis atomic reservation أو WATCH/MULTI/EXEC |
| SSRF عبر URL | فحص كل redirect وDNS والوجهة قبل المتابعة |
| false success | الإعلان بعد mutation أو state commit الحقيقي فقط |
| تسريب secret | redaction، عدم تسجيل arguments، `.gitignore`، `.env` خارج Git |
| provider outage | degradation مع fail-closed للمال والإنفاذ |
| account intelligence مضلل | account age `unknown`، ولا يدخل moderation risk |

## حدود لا يغطيها المشروع

لا يضمن bot منع spam أو raid بالكامل، ولا يعوض عن صلاحيات Telegram، ولا يثبت هوية أو maliciousness من user ID وحده. الاختبارات المعزولة لا تثبت دفاعاً ضد حسابات أو شبكة Telegram الحقيقية.

## مراجعة قبل الإنتاج

راجع permissions، allowed updates، webhook secret، Redis ACL/network، PostgreSQL TLS/backup، logs redaction، rate limits، وrunbook rollback. لا تفعل provider أو instant fulfillment دون عقد واختبارات حقيقية.

## المراجع

[1]: https://core.telegram.org/bots/api "Telegram Bot API"
[2]: https://owasp.org/www-project-application-security-verification-standard/ "OWASP ASVS"
