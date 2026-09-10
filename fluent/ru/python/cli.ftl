auth-issued =
    Токен **{ $name }**. Он бессрочный и показывается один раз — сохрани.

    ```
    uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=ВСТАВЬ UNSAFIE_API={ $api }
    python -c "import unsafie_sdk as u; u.chat.send('привет')"
    ```
auth-empty =
    Токенов пока нет.

    /auth — выпустить
    /auth list — что выпущено
    /auth rm ИМЯ — отозвать
auth-list = Токены:
auth-revoked = Токен { $name } отозван.
auth-unknown = Токена { $name } нет.
auth-usage =
    /auth [ИМЯ] — выпустить токен (одноимённый заменяется)
    /auth list — что выпущено
    /auth rm ИМЯ — отозвать

auth-private-only = Управление токенами доступно только в личных сообщениях с ботом.

pool-empty =
    Машин нет.

    Мощность пула складывается из донорских аккаунтов — их добавляет оператор в админке.
pool-status = Пул:
pool-took = Взято машин: { $count } — { $names }
pool-released = Отпущено: { $names }
pool-none-free = Свободных машин нет — перед тобой заявок: { $waiting }.
pool-usage =
    /pool — машины, ёмкость, что выполняется
    /pool take [N] — взять машины
    /pool release ИМЯ|all — отпустить
    /pool ci add owner/name — гонять CI репозитория на пуле
    /pool ci rm owner/name — перестать
    /pool ci — репозитории на пуле
pool-ci-added = { $slug } теперь на пуле. В воркфлоу поставь `runs-on: { $label }`.
pool-ci-removed = { $slug } больше не на пуле.
pool-ci-empty = Репозиториев на пуле нет.
pool-ci-list = Репозитории на пуле:
pool-ci-needs-token =
    Нужен токен с правом **Administration: read and write** на { $slug }.

    Отдай его боту через /gh ТОКЕН и повтори команду.
