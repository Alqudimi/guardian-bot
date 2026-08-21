# Guardian Bot — AI Contributor Guide

اقرأ `AGENT.md` أولاً؛ فهو المرجع الدائم للمشروع. استخدم هذا الملف كفهرس سريع فقط.

## قواعد غير قابلة للتفاوض

حافظ على المعمارية الحالية. افحص group chat وadmin role عبر Telegram. لا تسجل الأسرار. لا تعلن نجاحاً قبل mutation أو state commit حقيقي. استخدم Redis atomicity وTTL. لا تستنتج account age من user ID. لا تضف mock success أو provider وهمياً.

## المسارات

`src/handlers/` للحدود، `src/pipeline/` للتنسيق، `src/layers/` للإشارات والتنفيذ، `src/management/` لإعدادات المجموعة، `src/games/` للألعاب، `src/db/` للتخزين، `src/tasks/` للمهام الخلفية.

## التحقق

شغل compileall وpytest مع `-W error` وpip check وpip-audit وRuff correctness للملفات المعدلة. عند تعديل callback أو handler اختبر group/private وauthorization وownership والنجاح والفشل.
