# unsafie-cli

One binary that both a human and an agent use to drive [unsafie](https://unsafie.com): messages
and files into a Telegram chat, published pages, GitHub repositories, machines in the pool, a real
Chrome on one of them.

```bash
uv tool install unsafie-cli
unsafie auth login --token uns_…     # the bot hands out the token with /auth
unsafie help
```

On a machine in the pool the CLI is already installed and already authorized: the token, the chat
and the machine name arrive in the environment, so `unsafie say …` and `unsafie chrome shot` work
without a single question.

```bash
unsafie machines                     what I have right now
unsafie take 2                       two more
unsafie run 'pytest -q' --on box-1   a command on one of them
unsafie chrome start && unsafie chrome goto https://example.com && unsafie chrome shot
unsafie say 'готово' && unsafie page create report.md
```

Two things make it pleasant for a model to use:

- `unsafie help --json` returns the whole command index — every command, argument, flag and
  example — in one answer, so nothing has to be guessed;
- structured results come back as marker lines (`::unsafie::{…}`), which the server turns into
  pictures inside the tool result, files in the chat and notes in the live log.

No dependencies beyond `unsafie-wire`, so it installs in about a second on a fresh machine.
