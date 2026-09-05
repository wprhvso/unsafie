github-app-missing = GitHub is not set up yet: an administrator must create the app in the admin panel.
github-not-connected =
    GitHub is not connected.

    /gh add — connect an account
    /gh install — install the app on repositories
github-connect =
    Connect a GitHub account:
    { $url }

    The link is valid for 10 minutes. After that install the app on the repositories you need — /gh install
github-install =
    Choose the repositories the bot may work with:
    { $url }

    "All repositories" is easier: new repos become available automatically.
github-accounts = Accounts: { $logins }
github-suspended = — suspended
github-repos = { $n ->
    [one] { $n } repository:
   *[other] { $n } repositories:
}
github-no-repos = No repositories yet — install the app: /gh install
github-no-account = No account { $login } is connected.
github-removed = Account { $login } disconnected.
github-usage =
    /gh — accounts and repositories
    /gh add — connect another account
    /gh install — choose repositories
    /gh rm LOGIN — disconnect an account
github-subs-empty = No subscriptions in this chat.
