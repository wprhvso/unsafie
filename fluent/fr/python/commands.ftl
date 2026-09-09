commands-unknown = Commande inconnue : { $command }
commands-start =
    Bonjour. Écrivez simplement : chaque message sans réponse démarre une nouvelle conversation avec un contexte propre, et une réponse à n'importe quel message poursuit la conversation correspondante. Réagissez à votre propre message pour obtenir un lien vers le tour initié, où tout ce que je fais est visible.

    /stop — arrêter : en réponse, ce que ce message a initié ; sans réponse, tout
    /effort — effort de réflexion
    /gh — token et dépôts GitHub
    /ssh — serveurs via SSH
    /pool — machines du pool et runners CI
    /auth — tokens pour le CLI et l'API
    /tasks — rappels, planifications et surveillances
    /tz — fuseau horaire
    /lang — langue (en, ru, es, fr, ar, fa)
    /help — cette aide

    /model NAME — changer de modèle
    /model default — retour au modèle par défaut
commands-effort-status =
    Effort : { $effort }
    Par défaut : { $default }
    Niveaux : { $levels }

    /effort NIVEAU — changer (1—5 fonctionne aussi)
    /effort default — retour au niveau par défaut
commands-effort-set = Effort : { $effort }
commands-effort-reset = Retour à l'effort par défaut : { $effort }
commands-effort-usage = Niveau : { $levels } ou 1—5, ex. /effort high
commands-stop-nothing = Rien ne s'exécute pour le moment.
commands-stop-nothing-here = Le tour initié par ce message est déjà terminé.
commands-stop-one = Tour en cours arrêté.
commands-stop-many = { $n ->
    [one] { $n } tour arrêté
   *[other] { $n } tours arrêtés
}.

commands-group-private = Cette commande ne peut être utilisée que dans les groupes.
commands-group-menu = Choisissez le comportement du bot dans ce groupe :
commands-group-mode-mentions = Mentions uniquement (@bot ou réponse)
commands-group-mode-all = Tous les messages
commands-group-mode-off = Désactivé
commands-group-mode-updated = Mode de groupe défini sur : { $mode }
commands-group-admin-only = Seuls les administrateurs du groupe peuvent configurer le bot.

commands-retry-button = 🔄 Réessayer
commands-retry-in-progress = ⏳ Nouvelle tentative...
commands-retry-toast = Nouvelle tentative en cours...
commands-retry-not-found = Impossible de retrouver la requête d'origine.
commands-retry-already-running = Cette requête est déjà en cours d'exécution.
commands-retry-denied = Seul l'auteur ou les administrateurs peuvent relancer cette requête.

inline-prompt = Posez une question ou cherchez...
inline-again = 🔍 Poser une autre question
inline-text-title = Réponse texte
inline-text-hint = Réponse rapide directement dans le chat
inline-page-title = Page Web (Page)
inline-page-hint = Publier une page détaillée avec lien
inline-pending = ⏳ Génération de la réponse...
commands-lang-status =
    Langue : { $current }
    Langues disponibles : { $languages }

    /lang CODE — changer de langue
    /lang default — détection automatique via Telegram
commands-lang-set = Langue modifiée pour : { $language }
commands-lang-reset = Rétabli sur la détection automatique : { $language }
commands-lang-usage = Langues disponibles : { $languages }, ex. /lang fr
