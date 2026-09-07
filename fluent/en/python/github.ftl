github-app-missing = The GitHub App has not been created yet — an administrator sets it up in the admin panel. It is only needed for event notifications and checks; everything else runs on your token.
github-not-connected =
    GitHub is not connected.

    Make a token: github.com → Settings → Developer settings → Personal access tokens (classic), scopes `repo`, `workflow`, `gist`, `notifications`, `read:org`.

    /gh TOKEN — connect it (I will delete the message with the token)
github-token-saved =
    Token accepted: { $login }. Repositories visible: { $n }, app installations: { $apps }.

    /gh add owner/name — add a repository that is not in the list
github-token-scopes = Missing scopes: { $scopes }. Some commands will not work without them.
github-no-token = · { $login }: no token, run /gh TOKEN
github-synced = Done: { $n } repositories visible.
github-added = { $repo } added as `{ $alias }`.
github-install =
    The App is installed only for webhooks and checks — reading and writing go through your token:
    { $url }

    "All repositories" is easier: new repos become available automatically.
github-accounts = Accounts: { $logins }
github-suspended = — suspended
github-repos = { $n ->
    [one] { $n } repository:
   *[other] { $n } repositories:
}
github-repos-more = … and { $n } more
github-no-repos = No repositories yet — /gh sync or /gh add owner/name
github-no-account = No account { $login } is connected.
github-removed = Account { $login } disconnected.
github-usage =
    /gh — tokens and repositories
    /gh TOKEN — connect a personal access token
    /gh sync — re-read the list of repositories
    /gh add owner/name [alias] — add a repository
    /gh app — install the App (events and checks)
    /gh rm LOGIN — disconnect an account
github-subs-empty = No subscriptions in this chat.
