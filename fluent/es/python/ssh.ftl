ssh-empty =
    No hay servidores añadidos.

    /ssh key — obtener clave pública (agrégala a authorized_keys en el servidor)
    /ssh add ALIAS user@host — añadir un servidor
ssh-list = Servidores:
ssh-key = Clave pública de este bot. Agrégala a ~/.ssh/authorized_keys en el servidor:
ssh-key-rotated = Se ha generado una nueva clave. La antigua ya no funciona; cámbiala en authorized_keys:
ssh-added = Añadido { $alias } → { $target }. La clave del host se fijará en la primera conexión.
ssh-removed = Servidor { $alias } eliminado.
ssh-usage =
    /ssh — lista de servidores
    /ssh key — clave pública, /ssh key new — generar una nueva
    /ssh add ALIAS user@host[:puerto] — añadir un servidor
    /ssh rm ALIAS — eliminar
ssh-watch-fired =
    🔴 **{ $name }** en { $alias }

    La condición `{ $condition }` se cumple: { $reason }

    ```
    { $output }
    ```
ssh-watch-recovered = 🟢 **{ $name }** en { $alias } — normalizado ({ $reason })
ssh-watch-disabled =
    ⚠️ El monitor **{ $name }** en { $alias } está deshabilitado: el servidor no responde desde hace tiempo.

    { $error }
