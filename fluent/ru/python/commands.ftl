commands-unknown = Неизвестная команда: { $command }
commands-start =
    Привет. Пиши как есть — каждое сообщение без реплая начинает новый разговор с чистым контекстом, а ответ на любое сообщение (моё или своё) продолжает тот разговор, к которому оно относится. Реакция на твоё сообщение — ссылка на ход, который оно запустило: там видно всё, что я делаю.

    /stop — остановить: реплаем на сообщение — то, что запустило оно, без реплая — вообще всё
    /effort — усилие на размышления
    /model — модель Gemini
    /gh — токен GitHub и репозитории
    /ssh — серверы по SSH
    /pool — машины пула и раннеры CI
    /auth — токены для CLI и API
    /tasks — напоминания, расписания и наблюдатели
    /tz — таймзона
    /help — эта справка

commands-model-status =
    Модель: { $model }
    По умолчанию: { $default }

    /model NAME — сменить модель
    /model default — вернуть модель по умолчанию
commands-model-set = Модель: { $model }
commands-model-reset = Снова модель по умолчанию: { $model }
commands-model-usage = Имя модели — буквы, цифры, точки и дефисы, например /model gemini-3.1-pro-preview
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
