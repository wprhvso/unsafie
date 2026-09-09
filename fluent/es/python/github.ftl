github-app-missing = La GitHub App aún no ha sido creada; el administrador la configura en el panel de control. Solo se necesita para notificaciones de eventos y comprobaciones; todo lo demás usa tu token.
github-not-connected =
    GitHub no está conectado.

    Crea un token: github.com → Settings → Developer settings → Personal access tokens (classic), permisos `repo`, `workflow`, `gist`, `notifications`, `read:org`.

    /gh TOKEN — conectar (eliminaré el mensaje con el token)
github-token-saved =
    Token aceptado: { $login }. Repositorios visibles: { $n }, instalaciones de la app: { $apps }.

    /gh add owner/name — añadir un repositorio que no está en la lista
github-token-scopes = Permisos faltantes: { $scopes }. Algunos comandos no funcionarán sin ellos.
github-no-token = · { $login }: sin token, ejecuta /gh TOKEN
github-synced = Listo: { $n } repositorios visibles.
github-added = { $repo } añadido como `{ $alias }`.
github-install =
    La App se instala solo para webhooks y comprobaciones; la lectura y escritura se realizan con tu token:
    { $url }

    "All repositories" es más fácil: los nuevos repos estarán disponibles automáticamente.
github-accounts = Cuentas: { $logins }
github-suspended = — suspendida
github-repos = { $n ->
    [one] { $n } repositorio:
   *[other] { $n } repositorios:
}
github-repos-more = … y { $n } más
github-no-repos = Aún no hay repositorios — /gh sync o /gh add owner/name
github-no-account = Ninguna cuenta { $login } está conectada.
github-removed = Cuenta { $login } desconectada.
github-usage =
    /gh — tokens y repositorios
    /gh TOKEN — conectar un personal access token
    /gh sync — releer la lista de repositorios
    /gh add owner/name [alias] — añadir un repositorio
    /gh app — instalar la App (eventos y comprobaciones)
    /gh rm LOGIN — desconectar una cuenta
github-subs-empty = No hay suscripciones en este chat.
