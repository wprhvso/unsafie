ssh-empty =
    Aucun serveur ajouté.

    /ssh key — obtenir la clé publique (à ajouter dans authorized_keys sur le serveur)
    /ssh add ALIAS user@host — ajouter un serveur
ssh-list = Serveurs :
ssh-key = Clé publique de ce bot. Ajoutez-la à ~/.ssh/authorized_keys sur le serveur :
ssh-key-rotated = Une nouvelle clé a été générée. L'ancienne ne fonctionne plus — remplacez-la dans authorized_keys :
ssh-added = Ajouté { $alias } → { $target }. La clé d'hôte sera vérifiée lors de la première connexion.
ssh-removed = Serveur { $alias } supprimé.
ssh-usage =
    /ssh — liste des serveurs
    /ssh key — clé publique, /ssh key new — générer une nouvelle clé
    /ssh add ALIAS user@host[:port] — ajouter un serveur
    /ssh rm ALIAS — supprimer
ssh-watch-fired =
    🔴 **{ $name }** sur { $alias }

    La condition `{ $condition }` est vérifiée : { $reason }

    ```
    { $output }
    ```
ssh-watch-recovered = 🟢 **{ $name }** sur { $alias } — retour à la normale ({ $reason })
ssh-watch-disabled =
    ⚠️ La surveillance **{ $name }** sur { $alias } est désactivée : le serveur est inaccessible depuis un moment.

    { $error }
