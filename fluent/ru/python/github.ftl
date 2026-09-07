github-app-missing = Приложение GitHub ещё не создано — его настраивает администратор в админке. Оно нужно только для уведомлений о событиях и checks; всё остальное работает по токену.
github-not-connected =
    GitHub не подключён.

    Сделай токен: github.com → Settings → Developer settings → Personal access tokens (classic), скоупы `repo`, `workflow`, `gist`, `notifications`, `read:org`.

    /gh ТОКЕН — подключить (сообщение с токеном я удалю)
github-token-saved =
    Токен принят: { $login }. Репозиториев видно: { $n }, установок приложения: { $apps }.

    /gh add owner/name — добавить репозиторий, которого нет в списке
github-token-scopes = Не хватает скоупов: { $scopes }. Без них часть команд не сработает.
github-no-token = · { $login }: токена нет, нужен /gh ТОКЕН
github-synced = Готово: репозиториев видно { $n }.
github-added = { $repo } добавлен как `{ $alias }`.
github-install =
    Приложение ставится только ради вебхуков и checks — читать и писать бот будет твоим токеном:
    { $url }

    «All repositories» проще: новые репо появятся сами.
github-accounts = Аккаунты: { $logins }
github-suspended = — приостановлен
github-repos = { $n ->
    [one] { $n } репозиторий:
    [few] { $n } репозитория:
   *[other] { $n } репозиториев:
}
github-repos-more = … и ещё { $n }
github-no-repos = Репозиториев пока нет — /gh sync или /gh add owner/name
github-no-account = Аккаунт { $login } не подключён.
github-removed = Аккаунт { $login } отключён.
github-usage =
    /gh — токены и репозитории
    /gh ТОКЕН — подключить personal access token
    /gh sync — перечитать список репозиториев
    /gh add owner/name [алиас] — добавить репозиторий
    /gh app — поставить приложение (события и checks)
    /gh rm LOGIN — отключить аккаунт
github-subs-empty = В этом чате нет подписок.
