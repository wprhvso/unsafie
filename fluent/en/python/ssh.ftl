ssh-empty =
    No servers added.

    /ssh key — get the public key (put it into authorized_keys on the server)
    /ssh add ALIAS user@host — add a server
ssh-list = Servers:
ssh-key = Public key of this bot. Add it to ~/.ssh/authorized_keys on the server:
ssh-key-rotated = A new key has been generated. The old one no longer works — replace it in authorized_keys:
ssh-added = Added { $alias } → { $target }. The host key will be pinned on the first connection.
ssh-removed = Server { $alias } removed.
ssh-usage =
    /ssh — list of servers
    /ssh key — public key, /ssh key new — generate a new one
    /ssh add ALIAS user@host[:port] — add a server
    /ssh rm ALIAS — remove
ssh-watch-fired =
    🔴 **{ $name }** on { $alias }

    Condition `{ $condition }` holds: { $reason }

    ```
    { $output }
    ```
ssh-watch-recovered = 🟢 **{ $name }** on { $alias } — back to normal ({ $reason })
ssh-watch-disabled =
    ⚠️ Check **{ $name }** on { $alias } is disabled: the server has been unreachable for a while.

    { $error }
