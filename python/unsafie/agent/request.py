import logging

from unsafie.settings import settings

logger = logging.getLogger(__name__)

EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "low"
UNCACHEABLE = frozenset({"thinking", "redacted_thinking"})
DOWNGRADABLE = ("thinking", "effort", "output_config", "context_management", "fallbacks")
THINKING_DISPLAY = "thinking.display"
PREAMBLE = "You are a Claude agent, built on Anthropic's Claude Agent SDK."

PYTHON_TOOL_NAME = "python"

PYTHON_TOOL_DESCRIPTION = '''Run python on a machine of your own and get back everything it printed.

This is how you act and how you speak. The chat receives exactly what this code sends with \
`say`, `file` and `page` — nothing else. Your own text never reaches anybody.

# The interpreter

- One machine per chat, taken automatically on your first call. Fresh Ubuntu with root, a desktop \
already up (Xvfb and KasmVNC), Chrome, docker, git, gh, ripgrep, jq, uv and python. Every machine of the \
pool is identical and fully equipped. It is single use: `release()` destroys it, and GitHub ends \
the job after six hours anyway.
- The namespace is a living REPL. Variables, imports, open files and objects survive between \
calls and between messages within a turn. `_` is the value of the last expression.
- Top level `await` works. A bare expression on the last line is echoed, as in a REPL.
- Calls run in order, one after another, never overlapping — but a call starts the moment you \
finish writing it, while you are still composing the rest of the message.
- If the code raises, the traceback comes back as the result. Read it and fix it in the next call.
- Anything worth keeping must leave the machine: `git push`, `store.put(...)`, `kv['x'] = ...`.
- Long work: `submit("...")` in the background, `machines.logs(job, follow=True)` to read it.

# The SDK

Everything below is already imported. No import is needed; the module is also available as \
`unsafie` and `u`. This description is the whole map: if a name is not here, it is not there.

## Talking to the user

    say(text, reply_to=None, buttons=None, silent=False)  markdown message — the only way to speak
    photo(path_or_bytes, caption=None)                    a picture into the chat
    file(path_or_bytes, caption=None, kind="document")    document | photo | video | audio | voice
    page(markdown, title=None) -> url                     publish a long result as a web page
    note(text)                                            a line into the live log, not the chat
    chat.edit(id, text) / chat.delete(id) / chat.react(id, "👍") / chat.pin(id)
    chat.history("query", limit=20) / chat.info()
    pages.listing() / pages.update(slug, markdown) / pages.delete(slug)

`say` is the only thing the user sees. One user message deserves one reply message: put detail \
in a page and send its link.

## The pool

    run(command, machine=None, timeout=None) -> Run   shell on your machine; .output .exit_code .ok .check()
    take(n) -> [Machine]                              more machines, each single use
    release(name_or_none)                             give one back (it is destroyed)
    fan(command) -> {machine: Run}                    the same command on all of them
    submit(command, count=1) -> [job]                 background work
    machines.listing() / machines.logs(job, follow=True) / machines.cancel(job)
    machines.copy("box-1:/tmp/a", "box-2:/tmp/a")
    machines.desktop() -> url                         a live desktop link for the human
    machines.terminal() -> url                        a web terminal on this machine
    quota()                                           what is left today
    install("pandas", "httpx")                        into this interpreter with uv, then import it

## The shell is the rest of the SDK

git, gh, ssh, docker, curl, psql and everything else are on the machine already, and already \
authenticated. Use them through `run(...)` or `subprocess` instead of looking for a wrapper.

    run("git clone https://github.com/owner/name.git")  credentials sit in ~/.git-credentials
    run("gh pr create --fill")                          GH_TOKEN is the user's own token
    run("ssh prod 'df -h'")                             the owner's key and host aliases are in ~/.ssh
    run("scp report.pdf prod:/srv/www/")                same key, plain scp and rsync

    github.logins() -> ["alice", "bob"]     every account the user attached
    github.use("alice")                     rewires git and gh to that account
    github.token(repo=None) -> str          a token for curl and the GitHub API

Work with repositories as a developer does: clone, edit files, run the tests, commit, push, open \
a pull request with `gh`. The servers behind those ssh aliases are production: only when asked, \
never for experiments — experiments belong on the machine, which is disposable.

## Browser

    browser.start(profile=None, headless=False)   a real Chrome on the machine
    browser.goto(url) / click(sel) / type(sel, text) / press("Enter") / wait(sel, timeout=30)
    browser.text(sel) / html(sel) / evaluate(js)  evaluate() covers the rest of the page
    browser.shot(full=False, send=False) -> key   a screenshot; you see it, send=True posts it too
    browser.cookies() / upload(sel, path) / profiles() / restore(name) / stop(save_profile=True)
    browser.desktop() -> url                      hand the mouse to the human when a login blocks you

A profile keeps cookies between sessions, so a site the human logged into once stays logged in.

## State that outlives the machine

    store.put(key, data) / store.get(key) / store.text(key) / store.download(key, path)
    store.listing(prefix) / store.delete(key)
    kv["plan"] = "step 2"   ·   kv["plan"]   ·   kv.keys()
    secrets["OPENAI_API_KEY"]   ·   secrets.environ()      API keys, never printed into the chat

## CI and automation

    ci.add("owner/name", label="pool") -> {..., "snippet": "runs-on: pool"}
    ci.status(repo) / ci.jobs(repo) / ci.remove(repo)
    automation.schedule(text, when="18:00" | cron="0 9 * * 1-5" | every="6h", task=False)
    automation.watch(name, command, ">90", every="5m", host="prod")
    automation.subscribe("ci", "owner/name", branch="main")
    automation.timezone("Europe/Moscow")

## Reading the web

    fetch(url) -> markdown        ·   net.get_json(url)      plus web search, which is a real tool

# How to write a call

- Keep each call small and readable: one step, and print what matters. The result you get back is \
what the code printed, so print deliberately rather than dumping everything.
- Destructive or irreversible things — deleting, force pushing, restarting services, writing to \
other people — only at an explicit request. When in doubt ask through `say(...)` with buttons.
- Secrets stay in `secrets`; never print them, never paste them into a page or a message.
- If a call fails because a package is missing, `install("...")` in the next one and go on.
- Never claim you sent, published, pushed or saved anything before the call that did it has come \
back with its result.'''

PYTHON_TOOL = {
    "name": PYTHON_TOOL_NAME,
    "description": PYTHON_TOOL_DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "The python source to execute in the living interpreter of this chat. "
                    "Plain source: no markdown, no fences, no prose around it."
                ),
            }
        },
        "required": ["code"],
    },
}

_unsupported: dict[str, set[str]] = {}


def cache_control() -> dict:
    return {"type": "ephemeral", "ttl": settings.cache_ttl}


def system(prompt: str) -> list[dict]:
    return [
        {"type": "text", "text": PREAMBLE, "cache_control": cache_control()},
        {"type": "text", "text": prompt, "cache_control": cache_control()},
    ]


def reminder(text: str) -> dict:
    return {"type": "text", "text": f"<system-reminder>\n{text}\n</system-reminder>"}


def user(prompt: str, context: str | None = None) -> dict:
    content: list[dict] = []
    if context:
        content.append(reminder(context))
    content.append({"type": "text", "text": prompt})
    return {"role": "user", "content": content}


def tools(definitions: list[dict] | None = None) -> list[dict]:
    out = [PYTHON_TOOL, *(definitions or [])]
    if settings.claude_web_search:
        out.append(
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": settings.claude_web_search_max_uses,
            }
        )
    return out


def thinking() -> dict | None:
    mode = (settings.claude_thinking or "adaptive").strip().lower()
    if mode in ("", "off", "none", "0"):
        return None
    if mode.isdigit():
        config: dict = {"type": "enabled", "budget_tokens": int(mode)}
    else:
        if mode != "adaptive":
            logger.warning(
                "CLAUDE_THINKING=%r is not understood, falling back to adaptive",
                settings.claude_thinking,
            )
        config = {"type": "adaptive"}
    if settings.claude_thinking_display:
        config["display"] = settings.claude_thinking_display
    return config


def applied_thinking(model: str) -> dict | None:
    blocked = _unsupported.get(model, frozenset())
    if "thinking" in blocked:
        return None
    config = thinking()
    if config is not None and THINKING_DISPLAY in blocked:
        config.pop("display", None)
    return config


def context_management() -> dict | None:
    if not settings.claude_clear_thinking:
        return None
    return {
        "edits": [{"type": "clear_thinking_20251015", "keep": settings.claude_clear_thinking_keep}]
    }


def fallbacks() -> str | None:
    value = (settings.claude_fallbacks or "").strip()
    return value or None


def anchors(messages: list[dict], previous: int) -> set[int]:
    last = len(messages) - 1
    if last < 0:
        return set()
    marks = {last}
    if 0 <= previous < last:
        marks.add(previous)
    return marks


def cached(messages: list[dict], marks: set[int]) -> list[dict]:
    out: list[dict] = []
    for index, message in enumerate(messages):
        content = message.get("content")
        if index not in marks or not isinstance(content, list):
            out.append(message)
            continue
        target = None
        for block in reversed(content):
            if isinstance(block, dict) and block.get("type") not in UNCACHEABLE:
                target = block
                break
        if target is None:
            out.append(message)
            continue
        blocks = [
            {**block, "cache_control": cache_control()} if block is target else block
            for block in content
        ]
        out.append({**message, "content": blocks})
    return out


def build(
    *,
    model: str,
    prompt: str,
    messages: list[dict],
    marks: set[int],
    definitions: list[dict],
    effort: str | None,
    max_tokens: int,
) -> dict:
    blocked = _unsupported.get(model, frozenset())
    body: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "system": system(prompt),
        "messages": cached(messages, marks),
        "tools": definitions,
    }
    if effort and not ({"effort", "output_config"} & blocked):
        body["output_config"] = {"effort": effort}
    config = applied_thinking(model)
    if config is not None:
        body["thinking"] = config
    edits = context_management()
    if edits is not None and "context_management" not in blocked:
        body["context_management"] = edits
    mode = fallbacks()
    if mode is not None and "fallbacks" not in blocked:
        body["fallbacks"] = mode
    return body


def downgrade(model: str, error) -> list[str]:
    if error.status != 400:
        return []
    text = (error.message or "").lower()
    if "display" in text:
        hit = {THINKING_DISPLAY}
    else:
        hit = {field for field in DOWNGRADABLE if field in text}
    if not hit:
        return []
    known = _unsupported.setdefault(model, set())
    fresh = sorted(hit - known)
    if not fresh:
        return []
    known.update(fresh)
    logger.warning("%s rejects %s, retrying without it", model, ", ".join(fresh))
    return fresh
