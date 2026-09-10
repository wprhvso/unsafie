auth-issued =
    Token **{ $name }**. Il n'expire pas — conservez-le en sécurité, il n'est affiché qu'une seule fois.

    ```
    uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=COLLEZ_ICI UNSAFIE_API={ $api }
    python -c "import unsafie_sdk as u; u.chat.send('salut')"
    ```
auth-empty =
    Aucun token pour le moment.

    /auth — en créer un
    /auth list — liste des tokens
    /auth rm NOM — révoquer
auth-list = Tokens :
auth-revoked = Token { $name } révoqué.
auth-unknown = Aucun token nommé { $name }.
auth-usage =
    /auth [NOM] — émettre un token (s'il existe déjà, il est remplacé)
    /auth list — liste des tokens
    /auth rm NOM — révoquer

auth-private-only = La gestion des jetons est uniquement autorisée dans les messages privés avec le bot.

pool-empty =
    Aucune machine disponible.

    Le pool est constitué de comptes donateurs configurés dans le panneau d'administration.
pool-status = Pool :
pool-took = Réservation de { $count } machine(s) : { $names }
pool-released = { $names } libérée(s)
pool-none-free = Aucune machine libre pour le moment — { $waiting } requête(s) avant vous.
pool-usage =
    /pool — machines, capacité et exécutions
    /pool take [N] — réserver des machines
    /pool release NOM|all — libérer les machines
    /pool ci add owner/name — exécuter le CI d'un dépôt sur le pool
    /pool ci rm owner/name — l'arrêter
    /pool ci — dépôts configurés sur le pool
pool-ci-added = { $slug } s'exécute désormais sur le pool. Ajoutez `runs-on: { $label }` dans votre workflow.
pool-ci-removed = { $slug } ne s'exécute plus sur le pool.
pool-ci-empty = Aucun dépôt sur le pool.
pool-ci-list = Dépôts sur le pool :
pool-ci-needs-token =
    Un token avec **Administration: read and write** sur { $slug } est requis.

    Transmettez-le au bot avec /gh TOKEN, puis répétez la commande.
