commands-unknown = Unknown command: { $command }
commands-start =
    Hi. Just write — every message without a reply starts a new conversation with a clean context, and a reply to any message (mine or yours) continues the conversation it belongs to. React to my reply to get a web link to it.

    /budget — balance and per-message limit
    /gh — GitHub accounts
    /model — Claude model
    /ssh — servers over SSH
    /subs — repository event subscriptions
    /tasks — reminders and scheduled jobs
    /tz — timezone
commands-budget-status =
    Balance: { $balance }
    Per-message limit: { $limit }
    (in hundredths of a cent, { $units } = $1)
commands-budget-unlimited = unlimited
commands-budget-usage =
    /budget — show balance and limit
    /budget N — per-message limit (in hundredths of a cent, { $units } = $1)
    /budget -1 — no limit (default)
    /budget 0 — maximum savings
commands-model-status =
    Model: { $model }
    Default: { $default }

    /model NAME — switch model
    /model default — back to default
commands-model-set = Model: { $model }
commands-model-reset = Back to default model: { $model }
commands-model-usage = Model name — letters, digits, dots and dashes, e.g. /model claude-opus-5
commands-budget-zero = Limit 0. The bot now works for free: silently, thoughtfully and doing absolutely nothing. The cheapest assistant on the market.
