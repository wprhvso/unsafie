ssh-empty =
    هنوز سروری اضافه نشده است.

    /ssh key — دریافت کلید عمومی (آن را در authorized_keys روی سرور قرار دهید)
    /ssh add ALIAS user@host — افزودن سرور
ssh-list = سرورها:
ssh-key = کلید عمومی این ربات. آن را در ~/.ssh/authorized_keys روی سرور قرار دهید:
ssh-key-rotated = کلید جدیدی ایجاد شد. کلید قدیمی دیگر کار نمی‌کند — آن را در authorized_keys جایگزین کنید:
ssh-added = سرور { $alias } ← { $target } اضافه شد. کلید میزبان در اولین اتصال ثبت می‌شود.
ssh-removed = سرور { $alias } حذف شد.
ssh-usage =
    /ssh — فهرست سرورها
    /ssh key — کلید عمومی، /ssh key new — ایجاد کلید جدید
    /ssh add ALIAS user@host[:port] — افزودن سرور
    /ssh rm ALIAS — حذف
ssh-watch-fired =
    🔴 **{ $name }** روی { $alias }

    شرط `{ $condition }` برقرار است: { $reason }

    ```
    { $output }
    ```
ssh-watch-recovered = 🟢 **{ $name }** روی { $alias } — به حالت عادی بازگشت ({ $reason })
ssh-watch-disabled =
    ⚠️ پایش **{ $name }** روی { $alias } غیرفعال شد: سرور مدتی است در دسترس نیست.

    { $error }
