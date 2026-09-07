ssh-empty =
    Серверов нет.

    /ssh key — получить публичный ключ (положить его в authorized_keys на сервере)
    /ssh add ALIAS user@host — добавить сервер
ssh-list = Серверы:
ssh-key = Публичный ключ этого бота. Добавь его в ~/.ssh/authorized_keys на сервере:
ssh-key-rotated = Сгенерирован новый ключ. Старый больше не работает — замени его в authorized_keys:
ssh-added = Добавлен { $alias } → { $target }. Ключ хоста запомнится при первом подключении.
ssh-removed = Сервер { $alias } удалён.
ssh-usage =
    /ssh — список серверов
    /ssh key — публичный ключ, /ssh key new — сгенерировать новый
    /ssh add ALIAS user@host[:port] — добавить сервер
    /ssh rm ALIAS — удалить
ssh-watch-fired =
    🔴 **{ $name }** на { $alias }

    Условие `{ $condition }` выполнилось: { $reason }

    ```
    { $output }
    ```
ssh-watch-recovered = 🟢 **{ $name }** на { $alias } — снова в норме ({ $reason })
ssh-watch-disabled =
    ⚠️ Проверка **{ $name }** на { $alias } отключена: сервер долго недоступен.

    { $error }
