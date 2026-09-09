github-app-missing = L'application GitHub n'a pas encore été créée — l'administrateur la configure dans le panneau d'administration. Elle n'est requise que pour les webhooks et vérifications ; tout le reste passe par votre token.
github-not-connected =
    GitHub n'est pas connecté.

    Créez un token : github.com → Settings → Developer settings → Personal access tokens (classic), permissions `repo`, `workflow`, `gist`, `notifications`, `read:org`.

    /gh TOKEN — connecter (le message contenant le token sera supprimé)
github-token-saved =
    Token accepté : { $login }. Dépôts visibles : { $n }, installations d'applications : { $apps }.

    /gh add owner/name — ajouter un dépôt qui n'est pas dans la liste
github-token-scopes = Permissions manquantes : { $scopes }. Certaines commandes ne fonctionneront pas sans elles.
github-no-token = · { $login } : pas de token, lancez /gh TOKEN
github-synced = Terminé : { $n } dépôts visibles.
github-added = { $repo } ajouté sous `{ $alias }`.
github-install =
    L'application est installée uniquement pour les webhooks et vérifications — la lecture et l'écriture passent par votre token :
    { $url }

    "All repositories" est plus pratique : les nouveaux dépôts seront disponibles automatiquement.
github-accounts = Comptes : { $logins }
github-suspended = — suspendu
github-repos = { $n ->
    [one] { $n } dépôt :
   *[other] { $n } dépôts :
}
github-repos-more = … et { $n } de plus
github-no-repos = Aucun dépôt pour l'instant — /gh sync ou /gh add owner/name
github-no-account = Aucun compte { $login } n'est connecté.
github-removed = Compte { $login } déconnecté.
github-usage =
    /gh — tokens et dépôts
    /gh TOKEN — connecter un personal access token
    /gh sync — relire la liste des dépôts
    /gh add owner/name [alias] — ajouter un dépôt
    /gh app — installer l'application (événements et vérifications)
    /gh rm LOGIN — déconnecter un compte
github-subs-empty = Aucun abonnement dans ce chat.
