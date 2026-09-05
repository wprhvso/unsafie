github-app-missing = GitHub ещё не настроен: администратор должен создать приложение в админке.
github-not-connected =
    GitHub не подключён.

    /gh add — подключить аккаунт
    /gh install — поставить приложение на репозитории
github-connect =
    Подключить аккаунт GitHub:
    { $url }

    Ссылка живёт 10 минут. После этого поставь приложение на нужные репозитории — /gh install
github-install =
    Выбери репозитории, с которыми боту можно работать:
    { $url }

    «All repositories» проще: новые репо появятся сами.
github-accounts = Аккаунты: { $logins }
github-suspended = — приостановлен
github-repos = { $n ->
    [one] { $n } репозиторий:
    [few] { $n } репозитория:
   *[other] { $n } репозиториев:
}
github-no-repos = Репозиториев пока нет — поставь приложение: /gh install
github-no-account = Аккаунт { $login } не подключён.
github-removed = Аккаунт { $login } отключён.
github-usage =
    /gh — аккаунты и репозитории
    /gh add — подключить ещё аккаунт
    /gh install — выбрать репозитории
    /gh rm LOGIN — отключить аккаунт
github-subs-empty = В этом чате нет подписок.
