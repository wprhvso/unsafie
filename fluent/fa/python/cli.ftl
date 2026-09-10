auth-issued =
    توکن **{ $name }**. منقضی نمی‌شود — آن را در جای امنی نگه دارید، فقط یک بار نشان داده می‌شود.

    ```
    uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=اینجا_بگذارید UNSAFIE_API={ $api }
    python -c "import unsafie_sdk as u; u.chat.send('سلام')"
    ```
auth-empty =
    هنوز توکنی وجود ندارد.

    /auth — ایجاد توکن
    /auth list — توکن‌های صادرشده
    /auth rm NAME — لغو توکن
auth-list = توکن‌ها:
auth-revoked = توکن { $name } لغو شد.
auth-unknown = توکنی با نام { $name } وجود ندارد.
auth-usage =
    /auth [NAME] — ایجاد توکن (توکن قبلی با همین نام جایگزین می‌شود)
    /auth list — توکن‌های صادرشده
    /auth rm NAME — لغو توکن

auth-private-only = مدیریت توکن‌ها فقط در پیام‌های خصوصی با بات مجاز است.

pool-empty =
    هنوز ماشینی وجود ندارد.

    استخر از حساب‌های اهداکننده ساخته می‌شود و اپراتور آنها را در پنل ادمین اضافه می‌کند.
pool-status = استخر:
pool-took = { $count } ماشین دریافت شد: { $names }
pool-released = { $names } آزاد شد
pool-none-free = در حال حاضر ماشین آزادی وجود ندارد — { $waiting } درخواست قبل از شما در صف است.
pool-usage =
    /pool — ماشین‌ها، ظرفیت و وضعیت اجرا
    /pool take [N] — دریافت ماشین‌ها
    /pool release NAME|all — پس دادن ماشین‌ها
    /pool ci add owner/name — اجرای CI مخزن روی استخر
    /pool ci rm owner/name — متوقف کردن آن
    /pool ci — مخازن روی استخر
pool-ci-added = مخزن { $slug } اکنون روی استخر اجرا می‌شود. `runs-on: { $label }` را در گردش کار قرار دهید.
pool-ci-removed = مخزن { $slug } دیگر روی استخر اجرا نمی‌شود.
pool-ci-empty = هیچ مخزنی روی استخر وجود ندارد.
pool-ci-list = مخازن روی استخر:
pool-ci-needs-token =
    توکنی با دسترسی **Administration: read and write** روی { $slug } نیاز است.

    آن را با /gh TOKEN به ربات بدهید، سپس دستور را تکرار کنید.
