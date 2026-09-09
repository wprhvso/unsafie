github-app-missing = برنامه GitHub هنوز ایجاد نشده است — مدیر آن را در پنل مدیریت تنظیم می‌کند. فقط برای اعلان‌ها و بررسی‌ها نیاز است؛ بقیه کارها با توکن شما انجام می‌شود.
github-not-connected =
    GitHub متصل نیست.

    توکن بسازید: github.com ← Settings ← Developer settings ← Personal access tokens (classic)، دسترسی‌های `repo`, `workflow`, `gist`, `notifications`, `read:org`.

    /gh TOKEN — اتصال (پیام حاوی توکن را حذف خواهم کرد)
github-token-saved =
    توکن پذیرفته شد: { $login }. مخازن قابل مشاهده: { $n }، نصب‌های برنامه: { $apps }.

    /gh add owner/name — افزودن مخزنی که در فهرست نیست
github-token-scopes = دسترسی‌های ناموجود: { $scopes }. برخی دستورها بدون آنها کار نمی‌کنند.
github-no-token = · { $login }: بدون توکن، دستور /gh TOKEN را اجرا کنید
github-synced = انجام شد: { $n } مخزن قابل مشاهده است.
github-added = مخزن { $repo } با نام مستعار `{ $alias }` اضافه شد.
github-install =
    برنامه فقط برای وب‌هوک‌ها و بررسی‌ها نصب می‌شود — خواندن و نوشتن با توکن شما انجام می‌شود:
    { $url }

    گزینه "All repositories" ساده‌تر است: مخازن جدید به صورت خودکار در دسترس خواهند بود.
github-accounts = حساب‌ها: { $logins }
github-suspended = — معلق
github-repos = مخازن ({ $n }):
github-repos-more = … و { $n } مورد دیگر
github-no-repos = هنوز مخزنی وجود ندارد — /gh sync یا /gh add owner/name
github-no-account = حساب { $login } متصل نیست.
github-removed = حساب { $login } قطع اتصال شد.
github-usage =
    /gh — توکن‌ها و مخازن
    /gh TOKEN — اتصال توکن دسترسی شخصی
    /gh sync — بازخوانی فهرست مخازن
    /gh add owner/name [alias] — افزودن مخزن
    /gh app — نصب برنامه (رویدادها و بررسی‌ها)
    /gh rm LOGIN — قطع اتصال حساب
github-subs-empty = هیچ اشتراکی در این گفتگو وجود ندارد.
