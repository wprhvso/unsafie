commands-unknown = Неизвестная команда: { $command }
commands-start =
    Привет. Пиши как есть — каждое сообщение без реплая начинает новый разговор с чистым контекстом, а ответ на любое сообщение (моё или своё) продолжает тот разговор, к которому оно относится. Реакция на твоё сообщение — ссылка на ход, который оно запустило: там видно всё, что я делаю.

    /stop — остановить: реплаем на сообщение — то, что запустило оно, без реплая — вообще всё
    /effort — усилие на размышления
    /gh — токен GitHub и репозитории
    /ssh — серверы по SSH
    /pool — машины пула и раннеры CI
    /auth — токены для CLI и API
    /tasks — напоминания, расписания и наблюдатели
    /tz — таймзона
    /lang — язык интерфейса (en, ru, es, fr, ar, fa)
    /help — эта справка


    /model NAME — сменить модель
    /model default — вернуть модель по умолчанию
commands-effort-status =
    Усилие: { $effort }
    По умолчанию: { $default }
    Уровни: { $levels }

    /effort LEVEL — сменить (можно 1—5)
    /effort default — вернуть по умолчанию
commands-effort-set = Усилие: { $effort }
commands-effort-reset = Снова усилие по умолчанию: { $effort }
commands-effort-usage = Уровень: { $levels } или 1—5, например /effort high
commands-stop-nothing = Сейчас ничего не выполняется.
commands-stop-nothing-here = Ход, запущенный этим сообщением, уже закончился.
commands-stop-one = Остановил текущий ход.
commands-stop-many = Остановил { $n ->
    [one] { $n } ход
    [few] { $n } хода
   *[other] { $n } ходов
}.

commands-group-private = Эта команда предназначена только для групповых чатов.
commands-group-menu = Выберите режим работы бота в этой группе:
commands-group-mode-mentions = Только упоминания (@бот или ответ)
commands-group-mode-all = Все сообщения
commands-group-mode-off = Выключен
commands-group-mode-updated = Режим группы изменен на: { $mode }
commands-group-admin-only = Только администраторы группы могут настраивать бота.

commands-retry-button = 🔄 Повторить
commands-retry-in-progress = ⏳ Повторяется...
commands-retry-toast = Перезапускаю запрос...
commands-retry-not-found = Не удалось найти исходный запрос.
commands-retry-already-running = Этот запрос уже выполняется.
commands-retry-denied = Только автор запроса или администраторы группы могут повторить его.

inline-prompt = Начните вводить вопрос...
inline-again = 🔍 Новый запрос
inline-text-title = Текстовый ответ
inline-text-hint = Быстрый ответ прямо в чат
inline-page-title = Веб-страница (Page)
inline-page-hint = Опубликовать подробную статью со ссылкой
inline-pending = ⏳ Генерирую ответ...
commands-lang-status =
    Язык: { $current }
    Доступные языки: { $languages }

    /lang КОД — переключить язык
    /lang default — автоопределение по Telegram
commands-lang-set = Язык изменен на: { $language }
commands-lang-reset = Сброшено на автоопределение по Telegram: { $language }
commands-lang-usage = Доступные языки: { $languages }, например /lang ru
cmd-system-help =
    Инструкции для модели, которые направляют её для достижения лучшей производительности.

    Примеры:
    `/system Отвечай как можно более кратко`
    `/system Не используй технические термины в своем ответе`

    Вернуть как было: /system_clear
cmd-system-ok = Системный промпт установлен
cmd-system-clear-ok = Системный промпт сброшен
cmd-long-prompt = Отправить сообщение?
cmd-system-long-prompt = Сохранить системный промпт?
cmd-long-send = Отправить
cmd-long-reset = Сбросить
cmd-long-reset-ok = Сброшено
cmd-long-empty = Пока нечего отправлять
cmd-long-expired = Время вышло — ничего не отправлено

cmd-runs-empty = Нет активных задач в этом чате
