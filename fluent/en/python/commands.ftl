commands-unknown = Unknown command: { $command }
commands-start =
    Hi. Just write — every message without a reply starts a new conversation with a clean context, and a reply to any message (mine or yours) continues the conversation it belongs to. React to your own message to get a link to the turn it started, where everything I do is visible.

    /stop — stop: as a reply, whatever that message started; without a reply, everything
    /effort — thinking effort
    /gh — GitHub token and repositories
    /ssh — servers over SSH
    /pool — pool machines and CI runners
    /auth — tokens for the CLI and the API
    /tasks — reminders, schedules and watches
    /tz — timezone
    /help — this help


    /model NAME — switch model
    /model default — back to default
commands-effort-status =
    Effort: { $effort }
    Default: { $default }
    Levels: { $levels }

    /effort LEVEL — switch (1—5 works too)
    /effort default — back to default
commands-effort-set = Effort: { $effort }
commands-effort-reset = Back to default effort: { $effort }
commands-effort-usage = Level: { $levels } or 1—5, e.g. /effort high
commands-stop-nothing = Nothing is running right now.
commands-stop-nothing-here = The turn this message started has already finished.
commands-stop-one = Stopped the running turn.
commands-stop-many = Stopped { $n ->
    [one] { $n } turn
   *[other] { $n } turns
}.

commands-group-private = This command can only be used in group chats.
commands-group-menu = Choose how the bot should behave in this group:
commands-group-mode-mentions = Mentions only (@bot or reply)
commands-group-mode-all = All messages
commands-group-mode-off = Disabled
commands-group-mode-updated = Group mode set to: { $mode }
commands-group-admin-only = Only group administrators can configure the bot.

commands-retry-button = 🔄 Retry
commands-retry-in-progress = ⏳ Retrying...
commands-retry-toast = Retrying request...
commands-retry-not-found = Could not find the original request.
commands-retry-already-running = This request is already running.
commands-retry-denied = Only the author or group admins can retry this request.

inline-prompt = Ask a question or search...
inline-again = 🔍 Ask another question
inline-text-title = Text Answer
inline-text-hint = Quick answer directly in chat
inline-page-title = Web Page
inline-page-hint = Publish comprehensive page with link
inline-pending = ⏳ Generating answer...
