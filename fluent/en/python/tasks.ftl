tasks-empty = Nothing is scheduled in this chat.
tasks-in = in { $left }
tasks-now = now
tasks-cron = cron «{ $expr }»
tasks-every = every { $interval }
tasks-runs = { $n ->
    [one] ran { $n } time
   *[other] ran { $n } times
}
tasks-paused = paused
tasks-reminder = ⏰ { $text }
tasks-watches = Server checks:
tasks-hint = Ask in plain words to add or remove something — I will schedule it myself.
tasks-cleared = Removed: { $tasks } scheduled item(s), { $watches } check(s).
tz-current = Timezone: { $name }. Local time now { $now }. Change: /tz Europe/Berlin
tz-set = Timezone set: { $name }. Local time now { $now }.
