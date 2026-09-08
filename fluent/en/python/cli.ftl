auth-issued =
    Token **{ $name }**. It does not expire — keep it somewhere safe, it is shown once.

    ```
    uv tool install unsafie-sdk
    export UNSAFIE_TOKEN=PASTE UNSAFIE_API={ $api }
    python -c "import unsafie_sdk as u; u.say('hi')"
    ```
auth-empty =
    No tokens yet.

    /auth — issue one
    /auth list — what is issued
    /auth rm NAME — revoke
auth-list = Tokens:
auth-revoked = Token { $name } revoked.
auth-unknown = No token named { $name }.
auth-usage =
    /auth [NAME] — issue a token (an existing one with the same name is replaced)
    /auth list — what is issued
    /auth rm NAME — revoke

pool-empty =
    No machines yet.

    The pool is built from donor accounts, and the operator adds those in the admin panel.
pool-status = Pool:
pool-took = Took { $count } machine(s): { $names }
pool-released = Released { $names }
pool-none-free = No free machines right now — { $waiting } request(s) ahead of you.
pool-usage =
    /pool — machines, capacity, what is running
    /pool take [N] — take machines
    /pool release NAME|all — give them back
    /pool ci add owner/name — run the CI of a repository on the pool
    /pool ci rm owner/name — stop it
    /pool ci — repositories on the pool
pool-ci-added = { $slug } runs on the pool now. Put `runs-on: { $label }` into the workflow.
pool-ci-removed = { $slug } no longer runs on the pool.
pool-ci-empty = No repositories on the pool.
pool-ci-list = Repositories on the pool:
pool-ci-needs-token =
    A token with **Administration: read and write** on { $slug } is needed.

    Give it to the bot with /gh TOKEN, then repeat the command.
