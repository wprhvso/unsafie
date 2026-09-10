auth-issued =
    رمز **{ $name }**. لا تنتهي صلاحيته — احتفظ به بأمان، يظهر مرة واحدة فقط.

    ```
    uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=الصق_هنا UNSAFIE_API={ $api }
    python -c "import unsafie_sdk as u; u.chat.send('مرحبا')"
    ```
auth-empty =
    لا توجد رموز بعد.

    /auth — إصدار رمز
    /auth list — الرموز الصادرة
    /auth rm NAME — إلغاء
auth-list = الرموز:
auth-revoked = تم إلغاء الرمز { $name }.
auth-unknown = لا يوجد رمز باسم { $name }.
auth-usage =
    /auth [NAME] — إصدار رمز (يستبدل الرمز الحالي إذا كان بنفس الاسم)
    /auth list — الرموز الصادرة
    /auth rm NAME — إلغاء

auth-private-only = إدارة الرموز مسموح بها فقط في الرسائل الخاصة مع البوت.

pool-empty =
    لا توجد أجهزة في المجمع بعد.

    يتم بناء المجمع من حسابات مانحة يضيفها المشغل في لوحة الإدارة.
pool-status = المجمع:
pool-took = تم حجز { $count } جهاز: { $names }
pool-released = تم تحرير { $names }
pool-none-free = لا توجد أجهزة شاغرة حاليًا — هناك { $waiting } طلبًا قبلك.
pool-usage =
    /pool — الأجهزة، السعة والتشغيل الحالي
    /pool take [N] — حجز أجهزة
    /pool release NAME|all — إعادتها
    /pool ci add owner/name — تشغيل CI لمستودع على المجمع
    /pool ci rm owner/name — إيقافه
    /pool ci — المستودعات على المجمع
pool-ci-added = { $slug } يعمل الآن على المجمع. ضع `runs-on: { $label }` في سير العمل.
pool-ci-removed = { $slug } لم يعد يعمل على المجمع.
pool-ci-empty = لا توجد مستودعات على المجمع.
pool-ci-list = المستودعات على المجمع:
pool-ci-needs-token =
    يلزم رمز بصلاحية **Administration: read and write** على { $slug }.

    مرره للبوت عبر /gh TOKEN ثم كرر الأمر.
