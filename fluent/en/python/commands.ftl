commands-unknown = Unknown command: { $command }
commands-start =
    Hi. Just write — every message without a reply starts a new conversation with a clean context, and a reply to any message (mine or yours) continues the conversation it belongs to. React to your own message to get a link to the turn it started, where everything I do is visible.

    /stop — stop: as a reply, whatever that message started; without a reply, everything
    /budget — balance and per-turn limit
    /effort — thinking effort
    /model — Gemini model
    /gh — GitHub token and repositories
    /ssh — servers over SSH
    /pool — pool machines and CI runners
    /auth — tokens for the CLI and the API
    /tasks — reminders, schedules and watches
    /tz — timezone
    /help — this help

commands-budget-balance = Balance: { $amount }
commands-budget-locked = Locked for the turn: { $amount }
commands-budget-available = Available: { $amount }
commands-budget-limit = Per-turn limit: { $limit }
commands-budget-amount = ${ NUMBER($amount, minimumFractionDigits: 4, maximumFractionDigits: 4) }
commands-budget-unlimited = unlimited
commands-budget-usage =
    /budget — balance, what is locked and the limit
    /budget 0.5 — per-turn limit in dollars (0,5 works too)
    /budget -1 — no limit (default)
    /budget 0 — maximum savings
commands-model-status =
    Model: { $model }
    Default: { $default }

    /model NAME — switch model
    /model default — back to default
commands-model-set = Model: { $model }
commands-model-reset = Back to default model: { $model }
commands-model-usage = Model name — letters, digits, dots and dashes, e.g. /model gemini-3.1-pro-preview
commands-effort-status =
    Effort: { $effort }
    Default: { $default }
    Levels: { $levels }

    /effort LEVEL — switch (1—5 works too)
    /effort default — back to default
commands-effort-set = Effort: { $effort }
commands-effort-reset = Back to default effort: { $effort }
commands-effort-usage = Level: { $levels } or 1—5, e.g. /effort high
commands-budget-zero = Limit 0. The bot now works for free: silently, thoughtfully and doing absolutely nothing. The cheapest assistant on the market.
commands-stop-nothing = Nothing is running right now.
commands-stop-nothing-here = The turn this message started has already finished.
commands-stop-one = Stopped the running turn.
commands-stop-many = Stopped { $n ->
    [one] { $n } turn
   *[other] { $n } turns
}.
