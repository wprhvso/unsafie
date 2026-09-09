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
