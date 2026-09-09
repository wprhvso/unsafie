commands-unknown = دستور ناشناخته: { $command }
commands-start =
    سلام. هر پیامی بنویسید: هر پیام بدون ریپلای یک گفتگوی جدید با زمینه پاک آغاز می‌کند، و ریپلای روی هر پیام گفتگو را ادامه می‌دهد. به پیام خود واکنش نشان دهید تا پیوند نوبتی که آغاز شده را دریافت کنید.

    /stop — توقف: در پاسخ، آنچه این پیام آغاز کرده؛ بدون پاسخ، همه چیز
    /effort — تلاش تفکر
    /gh — توکن و مخازن GitHub
    /ssh — سرورها از طریق SSH
    /pool — ماشین‌های استخر و اجراکننده‌های CI
    /auth — توکن‌ها برای CLI و API
    /tasks — یادآوری‌ها، زمان‌بندی‌ها و پایش‌ها
    /tz — منطقه زمانی
    /help — این راهنما

    /model NAME — تغییر مدل
    /model default — بازگشت به پیش‌فرض
commands-effort-status =
    تلاش: { $effort }
    پیش‌فرض: { $default }
    سطوح: { $levels }

    /effort LEVEL — تغییر (1—5 نیز کار می‌کند)
    /effort default — بازگشت به پیش‌فرض
commands-effort-set = تلاش: { $effort }
commands-effort-reset = بازگشت به تلاش پیش‌فرض: { $effort }
commands-effort-usage = سطح: { $levels } یا 1—5، مثلاً /effort high
commands-stop-nothing = در حال حاضر چیزی در حال اجرا نیست.
commands-stop-nothing-here = نوبتی که این پیام آغاز کرده بود پایان یافته است.
commands-stop-one = نوبت در حال اجرا متوقف شد.
commands-stop-many = { $n } نوبت متوقف شد.

commands-group-private = این دستور فقط در گروه‌ها قابل استفاده است.
commands-group-menu = نحوه پاسخگویی ربات در این گروه را انتخاب کنید:
commands-group-mode-mentions = فقط منشن‌ها (@ربات یا ریپلای)
commands-group-mode-all = همه پیام‌ها
commands-group-mode-off = غیرفعال
commands-group-mode-updated = حالت گروه تغییر یافت به: { $mode }
commands-group-admin-only = فقط مدیران گروه می‌توانند ربات را تنظیم کنند.

commands-retry-button = 🔄 تلاش مجدد
commands-retry-in-progress = ⏳ در حال تلاش مجدد...
commands-retry-toast = در حال شروع مجدد درخواست...
commands-retry-not-found = درخواست اصلی پیدا نشد.
commands-retry-already-running = این نوبت در حال حاضر در حال اجرا است.
commands-retry-denied = فقط ارسال‌کننده یا مدیران گروه می‌توانند دوباره تلاش کنند.

inline-prompt = پرسشی بنویسید یا جستجو کنید...
inline-again = 🔍 پرسش جدید
inline-text-title = پاسخ متنی
inline-text-hint = پاسخ سریع در همین گفتگو
inline-page-title = صفحه وب (Page)
inline-page-hint = انتشار صفحه کامل به همراه پیوند
inline-pending = ⏳ در حال آماده‌سازی پاسخ...
