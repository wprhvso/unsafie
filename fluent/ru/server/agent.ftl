agent-failure = Что-то сломалось, попробуй ещё раз.
agent-empty-balance = Баланс пуст. Проверить: /budget
agent-no-credentials = Все ключи Anthropic сейчас недоступны{ $when }. Попробуй позже.
agent-no-credentials-when = { $minutes ->
    [one] { " " }(ближайший освободится через ~{ $minutes } минуту)
    [few] { " " }(ближайший освободится через ~{ $minutes } минуты)
   *[other] { " " }(ближайший освободится через ~{ $minutes } минут)
}
