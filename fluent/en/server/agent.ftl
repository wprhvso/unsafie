agent-failure = Something broke, try again.
agent-empty-balance = Balance is empty. Check: /budget
agent-no-credentials = All Anthropic keys are unavailable right now{ $when }. Try later.
agent-no-credentials-when = { $minutes ->
    [one] { " " }(the nearest one frees up in ~{ $minutes } minute)
   *[other] { " " }(the nearest one frees up in ~{ $minutes } minutes)
}
