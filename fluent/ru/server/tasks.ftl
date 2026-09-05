tasks-empty = В этом чате ничего не запланировано.
tasks-in = через { $left }
tasks-now = сейчас
tasks-cron = cron «{ $expr }»
tasks-every = каждые { $interval }
tasks-runs = { $n ->
    [one] сработала { $n } раз
    [few] сработала { $n } раза
   *[other] сработала { $n } раз
}
tasks-paused = пауза
tasks-reminder = ⏰ { $text }
tasks-watches = Проверки серверов:
tasks-hint = Скажи словами, что добавить или убрать — сам поставлю в расписание.
tasks-cleared = Удалено: { $tasks } задач(и), { $watches } проверок.
tz-current = Таймзона: { $name }. Местное время сейчас { $now }. Сменить: /tz Europe/Berlin
tz-set = Таймзона установлена: { $name }. Местное время сейчас { $now }.
