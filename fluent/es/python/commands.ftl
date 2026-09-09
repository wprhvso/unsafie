commands-unknown = Comando desconocido: { $command }
commands-start =
    Hola. Escribe cualquier mensaje: cada mensaje sin respuesta inicia una nueva conversación con contexto limpio, y una respuesta a cualquier mensaje continúa la conversación correspondiente. Reacciona a tu propio mensaje para obtener un enlace al turno iniciado, donde todo lo que hago es visible.

    /stop — detener: como respuesta, lo que inició ese mensaje; sin respuesta, todo
    /effort — esfuerzo de pensamiento
    /gh — token y repositorios de GitHub
    /ssh — servidores por SSH
    /pool — máquinas del pool y ejecutores de CI
    /auth — tokens para la CLI y la API
    /tasks — recordatorios, programaciones y monitores
    /tz — zona horaria
    /lang — idioma (en, ru, es, fr, ar, fa)
    /help — esta ayuda

    /model NAME — cambiar modelo
    /model default — volver al predeterminado
commands-effort-status =
    Esfuerzo: { $effort }
    Por defecto: { $default }
    Niveles: { $levels }

    /effort NIVEL — cambiar (1—5 también funciona)
    /effort default — volver al valor por defecto
commands-effort-set = Esfuerzo: { $effort }
commands-effort-reset = De vuelta al esfuerzo por defecto: { $effort }
commands-effort-usage = Nivel: { $levels } o 1—5, ej. /effort high
commands-stop-nothing = No hay nada ejecutándose en este momento.
commands-stop-nothing-here = El turno que inició este mensaje ya ha terminado.
commands-stop-one = Turno en ejecución detenido.
commands-stop-many = Se han detenido { $n ->
    [one] { $n } turno
   *[other] { $n } turnos
}.

commands-group-private = Este comando solo se puede usar en chats de grupo.
commands-group-menu = Elige cómo debe comportarse el bot en este grupo:
commands-group-mode-mentions = Solo menciones (@bot o respuesta)
commands-group-mode-all = Todos los mensajes
commands-group-mode-off = Desactivado
commands-group-mode-updated = Modo de grupo cambiado a: { $mode }
commands-group-admin-only = Solo los administradores del grupo pueden configurar el bot.

commands-retry-button = 🔄 Reintentar
commands-retry-in-progress = ⏳ Reintentando...
commands-retry-toast = Reintentando petición...
commands-retry-not-found = No se pudo encontrar la petición original.
commands-retry-already-running = Esta petición ya se está ejecutando.
commands-retry-denied = Solo el autor o los administradores pueden reintentar esta petición.

inline-prompt = Escribe una pregunta o busca...
inline-again = 🔍 Otra pregunta
inline-text-title = Respuesta de texto
inline-text-hint = Respuesta rápida directamente en el chat
inline-page-title = Página web (Page)
inline-page-hint = Publicar página completa con enlace
inline-pending = ⏳ Generando respuesta...
commands-lang-status =
    Idioma: { $current }
    Idiomas disponibles: { $languages }

    /lang CÓDIGO — cambiar idioma
    /lang default — detección automática de Telegram
commands-lang-set = Idioma cambiado a: { $language }
commands-lang-reset = Restablecido a detección automática: { $language }
commands-lang-usage = Idiomas disponibles: { $languages }, ej. /lang es
cmd-system-help =
    Instrucciones para el modelo que lo orientan hacia un mejor rendimiento.

    Ejemplos:
    <code>/system Responde de la forma más concisa posible</code>
    <code>/system No uses términos técnicos en tu respuesta</code>

    Volver a lo predeterminado: /system_clear
cmd-system-ok = Prompt del sistema establecido
cmd-system-clear-ok = Prompt del sistema restablecido
cmd-long-prompt = ¿Envío el mensaje?
cmd-system-long-prompt = ¿Guardo el prompt del sistema?
cmd-long-send = Enviar
cmd-long-reset = Cancelar
cmd-long-reset-ok = Cancelado
cmd-long-empty = Todavía no hay nada que enviar
cmd-long-expired = Se agotó el tiempo: no se envió nada
