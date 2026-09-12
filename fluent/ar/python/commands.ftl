commands-unknown = أمر غير معروف: { $command }
commands-start =
    مرحبًا! اكتب أي رسالة: كل رسالة دون رد تبدأ محادثة جديدة بسياق نظيف، والرد على أي رسالة يتابع المحادثة التابعة لها. تفاعل مع رسالتك للحصول على رابط للتحول الذي بدأته، حيث تظهر جميع أعمالي بوضوح.

    /wipe — حذف جميع سجل المحادثات وملفات بيئة الاختبار والمخرجات
    /stop — إيقاف: كرد يوقف ما بدأته تلك الرسالة، ودون رد يوقف كل شيء
    /effort — جهد التفكير
    /gh — رمز ومستودعات GitHub
    /ssh — خوادم عبر SSH
    /pool — أجهزة المجمع ومُشغلات CI
    /auth — رموز CLI وAPI
    /tasks — تذكيرات، جداول ومراقبات
    /tz — المنطقة الزمنية
    /lang — اللغة (en, ru, es, fr, ar, fa)
    /help — هذه المساعدة

    /model NAME — تبديل النموذج
    /model default — العودة للافتراضي
commands-effort-status =
    الجهد: { $effort }
    الافتراضي: { $default }
    المستويات: { $levels }

    /effort LEVEL — تغيير (1—5 يعمل أيضًا)
    /effort default — العودة للافتراضي
commands-effort-set = الجهد: { $effort }
commands-effort-reset = العودة إلى الجهد الافتراضي: { $effort }
commands-effort-usage = المستوى: { $levels } أو 1—5، مثل /effort high
commands-stop-nothing = لا يوجد شيء يعمل حاليًا.
commands-stop-nothing-here = اكتملت المعالجة التي بدأتها هذه الرسالة بالفعل.
commands-stop-one = تم إيقاف المعالجة الحالية.
commands-stop-many = تم إيقاف { $n } معالجة.

commands-group-private = هذا الأمر مخصص للمجموعات فقط.
commands-group-menu = اختر طريقة استجابة البوت في هذه المجموعة:
commands-group-mode-mentions = الإشارات فقط (@بوت أو الرد)
commands-group-mode-all = جميع الرسائل
commands-group-mode-off = معطّل
commands-group-mode-updated = تم تغيير وضع المجموعة إلى: { $mode }
commands-group-admin-only = مشرفو المجموعة فقط يمكنهم ضبط البوت.

commands-retry-button = 🔄 إعادة المحاولة
commands-retry-in-progress = ⏳ جارٍ إعادة المحاولة...
commands-retry-toast = جارٍ إعادة تشغيل الطلب...
commands-retry-not-found = تعذر العثور على الطلب الأصلي.
commands-retry-already-running = هذا الطلب قيد التنفيذ بالفعل.
commands-retry-denied = صاحب الطلب أو مشرفو المجموعة فقط يمكنهم إعادة المحاولة.

inline-prompt = اكتب سؤالاً أو ابحث...
inline-again = 🔍 سؤال جديد
inline-text-title = رد نصي
inline-text-hint = رد سريع داخل المحادثة
inline-page-title = صفحة ويب (Page)
inline-page-hint = نشر صفحة مفصلة مع رابط
inline-pending = ⏳ جارٍ توليد الرد...
commands-lang-status =
    اللغة الحالية: { $current }
    اللغات المتاحة: { $languages }

    /lang CODE — تغيير اللغة
    /lang default — تحديد تلقائي حسب تيليجرام
commands-lang-set = تم تغيير اللغة إلى: { $language }
commands-lang-reset = تمت إعادة التعيين إلى التحديد التلقائي: { $language }
commands-lang-usage = اللغات المتاحة: { $languages }، مثل /lang ar
cmd-system-help =
    تعليمات للنموذج توجّهه نحو أداء أفضل.

    أمثلة:
    `/system أجب بأقصى قدر ممكن من الإيجاز`
    `/system لا تستخدم مصطلحات تقنية في ردك`

    للعودة إلى الوضع الافتراضي: /system_clear
cmd-system-ok = تم ضبط موجّه النظام
cmd-system-clear-ok = تمت إعادة ضبط موجّه النظام
cmd-long-prompt = هل أرسل الرسالة؟
cmd-system-long-prompt = هل أحفظ موجّه النظام؟
cmd-long-send = إرسال
cmd-long-reset = إلغاء
cmd-long-reset-ok = تم الإلغاء
cmd-long-empty = لا يوجد ما يُرسل بعد
cmd-long-expired = انتهت المهلة — لم يُرسل شيء

cmd-runs-empty = لا توجد مهام نشطة في هذه الدردشة

commands-wipe-success = تم حذف جميع سجل المحادثات والسياق وملفات بيئة الاختبار والمخرجات لهذه المحادثة نهائيًا.
