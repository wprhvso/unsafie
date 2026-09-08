commands-unknown = Неизвестная команда: { $command }
commands-start =
    Привет. Пиши как есть — каждое сообщение без реплая начинает новый разговор с чистым контекстом, а ответ на любое сообщение (моё или своё) продолжает тот разговор, к которому оно относится. Реакция на твоё сообщение — ссылка на ход, который оно запустило: там видно всё, что я делаю.

    /stop — остановить: реплаем на сообщение — то, что запустило оно, без реплая — вообще всё
    /budget — баланс и лимит на ход
    /effort — усилие на размышления
    /model — модель Claude
    /gh — токен GitHub и репозитории
    /ssh — серверы по SSH
    /pool — машины пула и раннеры CI
    /auth — токены для CLI и API
    /tasks — напоминания, расписания и наблюдатели
    /tz — таймзона
    /help — эта справка

commands-budget-balance = Баланс: { $amount }
commands-budget-locked = Залочено под ход: { $amount }
commands-budget-available = Доступно: { $amount }
commands-budget-limit = Лимит на ход: { $limit }
commands-budget-amount = { NUMBER($amount, minimumFractionDigits: 4, maximumFractionDigits: 4) }$
commands-budget-unlimited = без лимита
commands-budget-usage =
    /budget — баланс, залоченное и лимит
    /budget 0.5 — лимит на ход в долларах (можно и 0,5)
    /budget -1 — без лимита (по умолчанию)
    /budget 0 — экономия по-максимуму
commands-model-status =
    Модель: { $model }
    По умолчанию: { $default }

    /model NAME — сменить модель
    /model default — вернуть модель по умолчанию
commands-model-set = Модель: { $model }
commands-model-reset = Снова модель по умолчанию: { $model }
commands-model-usage = Имя модели — буквы, цифры, точки и дефисы, например /model claude-opus-5
commands-effort-status =
    Усилие: { $effort }
    По умолчанию: { $default }
    Уровни: { $levels }

    /effort LEVEL — сменить (можно 1—5)
    /effort default — вернуть по умолчанию
commands-effort-set = Усилие: { $effort }
commands-effort-reset = Снова усилие по умолчанию: { $effort }
commands-effort-usage = Уровень: { $levels } или 1—5, например /effort high
commands-budget-zero = Лимит 0. Бот теперь работает бесплатно: молча, вдумчиво и абсолютно ничего не делая. Самый дешёвый ассистент на рынке.
commands-stop-nothing = Сейчас ничего не выполняется.
commands-stop-nothing-here = Ход, запущенный этим сообщением, уже закончился.
commands-stop-one = Остановил текущий ход.
commands-stop-many = Остановил { $n ->
    [one] { $n } ход
    [few] { $n } хода
   *[other] { $n } ходов
}.
