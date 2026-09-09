auth-issued =
    Token **{ $name }**. No caduca; guárdalo en un lugar seguro, solo se muestra una vez.

    ```
    uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=PEGA_AQUI UNSAFIE_API={ $api }
    python -c "import unsafie_sdk as u; u.chat.send('hola')"
    ```
auth-empty =
    Aún no hay tokens.

    /auth — emitir uno
    /auth list — tokens emitidos
    /auth rm NOMBRE — revocar
auth-list = Tokens:
auth-revoked = Token { $name } revocado.
auth-unknown = No existe el token { $name }.
auth-usage =
    /auth [NOMBRE] — emitir un token (si ya existe uno con el mismo nombre, se reemplaza)
    /auth list — tokens emitidos
    /auth rm NOMBRE — revocar

pool-empty =
    Aún no hay máquinas.

    El pool se compone de cuentas de donantes y el operador las añade en el panel de administración.
pool-status = Pool:
pool-took = Se tomaron { $count } máquina(s): { $names }
pool-released = Se liberaron { $names }
pool-none-free = No hay máquinas libres en este momento; hay { $waiting } solicitud(es) por delante de ti.
pool-usage =
    /pool — máquinas, capacidad y ejecuciones activas
    /pool take [N] — tomar máquinas
    /pool release NOMBRE|all — devolver máquinas
    /pool ci add owner/name — ejecutar el CI de un repositorio en el pool
    /pool ci rm owner/name — detenerlo
    /pool ci — repositorios en el pool
pool-ci-added = { $slug } ahora se ejecuta en el pool. Añade `runs-on: { $label }` a tu workflow.
pool-ci-removed = { $slug } ya no se ejecuta en el pool.
pool-ci-empty = No hay repositorios en el pool.
pool-ci-list = Repositorios en el pool:
pool-ci-needs-token =
    Se necesita un token con **Administration: read and write** en { $slug }.

    Pásalo al bot con /gh TOKEN y luego repite el comando.
