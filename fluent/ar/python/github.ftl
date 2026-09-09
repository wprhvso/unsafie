github-app-missing = لم يتم إنشاء تطبيق GitHub بعد — يقوم المسؤول بإعداده في لوحة الإدارة. يلزم فقط لإشعارات الأحداث والفحوصات؛ كل شيء آخر يعمل عبر رمزك.
github-not-connected =
    GitHub غير متصل.

    أنشئ رمزًا: github.com ← Settings ← Developer settings ← Personal access tokens (classic)، الصلاحيات `repo`, `workflow`, `gist`, `notifications`, `read:org`.

    /gh TOKEN — توصيل (سأقوم بحذف الرسالة التي تحتوي على الرمز)
github-token-saved =
    تم قبول الرمز: { $login }. المستودعات المرئية: { $n }، تثبيتات التطبيق: { $apps }.

    /gh add owner/name — إضافة مستودع غير موجود في القائمة
github-token-scopes = صلاحيات مفقودة: { $scopes }. بعض الأوامر لن تعمل بدونها.
github-no-token = · { $login }: لا يوجد رمز، شغل /gh TOKEN
github-synced = تم: { $n } مستودعًا مرئيًا.
github-added = تمت إضافة { $repo } باسم `{ $alias }`.
github-install =
    يتم تثبيت التطبيق فقط للـ webhooks والفحوصات — القراءة والكتابة تتم عبر رمزك:
    { $url }

    خيار "All repositories" أسهل: المستودعات الجديدة ستتاح تلقائيًا.
github-accounts = الحسابات: { $logins }
github-suspended = — معلّق
github-repos = المستودعات ({ $n }):
github-repos-more = … و { $n } إضافية
github-no-repos = لا توجد مستودعات بعد — /gh sync أو /gh add owner/name
github-no-account = الحساب { $login } غير متصل.
github-removed = تم فصل الحساب { $login }.
github-usage =
    /gh — الرموز والمستودعات
    /gh TOKEN — ربط رمز وصول شخصي
    /gh sync — إعادة قراءة قائمة المستودعات
    /gh add owner/name [alias] — إضافة مستودع
    /gh app — تثبيت التطبيق (الأحداث والفحوصات)
    /gh rm LOGIN — فصل حساب
github-subs-empty = لا توجد اشتراكات في هذه المحادثة.
