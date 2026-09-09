tasks-empty = No hay nada programado en este chat.
tasks-in = en { $left }
tasks-now = ahora
tasks-cron = cron «{ $expr }»
tasks-every = cada { $interval }
tasks-runs = { $n ->
    [one] se ejecutó { $n } vez
   *[other] se ejecutó { $n } veces
}
tasks-paused = en pausa
tasks-reminder = ⏰ { $text }
tasks-watches = Monitorización de servidores:
tasks-hint = Pídeme con palabras sencillas añadir o quitar algo; lo programaré yo mismo.
tasks-cleared = Eliminado: { $tasks } tarea(s) programada(s), { $watches } monitor(es).
tz-current = Zona horaria: { $name }. Hora local actual: { $now }. Cambiar: /tz Europe/Madrid
tz-set = Zona horaria establecida: { $name }. Hora local actual: { $now }.
