tasks-empty = Rien n'est planifié dans ce chat.
tasks-in = dans { $left }
tasks-now = maintenant
tasks-cron = cron «{ $expr }»
tasks-every = toutes les { $interval }
tasks-runs = { $n ->
    [one] exécuté { $n } fois
   *[other] exécuté { $n } fois
}
tasks-paused = en pause
tasks-reminder = ⏰ { $text }
tasks-watches = Surveillance des serveurs :
tasks-hint = Demandez simplement d'ajouter ou de retirer quelque chose, je le planifierai moi-même.
tasks-cleared = Supprimé : { $tasks } tâche(s) planifiée(s), { $watches } surveillance(s).
tz-current = Fuseau horaire : { $name }. Heure locale actuelle : { $now }. Changer : /tz Europe/Paris
tz-set = Fuseau horaire défini : { $name }. Heure locale actuelle : { $now }.
