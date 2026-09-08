# unsafie-sdk

What the agent writes and a human can import. One package, two lives: inside the agent's REPL
every name is already there, and on a laptop it is a normal library.

```bash
uv tool install unsafie-sdk        # or: pip install unsafie-sdk
export UNSAFIE_TOKEN=uns_…         # the bot gives you one with /auth
```

```python
import unsafie_sdk as u

u.chat.send("готово")                  # a message into the chat
u.pages.create("# отчёт\n\nвсё сошлось")  # a web page, returns its link
box = u.machines.take(1)[0]            # a machine from the pool
box.run("uname -a").output             # a command on it
u.github.use("wprhvso")                # git and gh now speak as this account
box.run("git clone https://github.com/wprhvso/unsafie.git")
u.browser.start(); u.browser.goto("https://example.com"); u.browser.shot()
u.packages.install("pandas"); import pandas  # packages on the fly, with uv
```

The same package runs the machine itself: `unsafie-machine serve` registers the job as a machine
of the pool and keeps a living python namespace for the blocks the agent sends.
