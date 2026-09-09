ssh-empty =
    لم تتم إضافة خوادم بعد.

    /ssh key — الحصول على المفتاح العام (أضفه إلى authorized_keys على الخادم)
    /ssh add ALIAS user@host — إضافة خادم
ssh-list = الخوادم:
ssh-key = المفتاح العام لهذا البوت. أضفه إلى ~/.ssh/authorized_keys على الخادم:
ssh-key-rotated = تم إنشاء مفتاح جديد. المفتاح القديم لم يعد يعمل — استبدله في authorized_keys:
ssh-added = تمت إضافة { $alias } ← { $target }. سيتم تثبيت مفتاح المضيف عند أول اتصال.
ssh-removed = تم حذف الخادم { $alias }.
ssh-usage =
    /ssh — قائمة الخوادم
    /ssh key — المفتاح العام، /ssh key new — إنشاء مفتاح جديد
    /ssh add ALIAS user@host[:port] — إضافة خادم
    /ssh rm ALIAS — حذف
ssh-watch-fired =
    🔴 **{ $name }** على { $alias }

    تحقق الشرط `{ $condition }`: { $reason }

    ```
    { $output }
    ```
ssh-watch-recovered = 🟢 **{ $name }** على { $alias } — عاد إلى الوضع الطبيعي ({ $reason })
ssh-watch-disabled =
    ⚠️ تم تعطيل فحص **{ $name }** على { $alias }: الخادم غير متاح منذ فترة.

    { $error }
