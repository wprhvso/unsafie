from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Arg:
    name: str
    optional: bool = False
    repeat: bool = False

    @property
    def display(self) -> str:
        body = f"{self.name}…" if self.repeat else self.name
        return f"[{body}]" if self.optional else f"<{body}>"


@dataclass(frozen=True, slots=True)
class Flag:
    long: str
    short: str = ""
    value: str = ""
    default: str = ""
    help: str = ""

    @property
    def takes_value(self) -> bool:
        return bool(self.value)

    @property
    def display(self) -> str:
        names = f"-{self.short}, --{self.long}" if self.short else f"--{self.long}"
        return f"{names} {self.value}" if self.value else names


@dataclass(frozen=True, slots=True)
class Cmd:
    path: tuple[str, ...]
    group: str
    summary: str
    args: tuple[Arg, ...] = ()
    flags: tuple[Flag, ...] = ()
    examples: tuple[str, ...] = ()
    phase: int = 1
    internal: bool = False
    passthrough: bool = False

    @property
    def name(self) -> str:
        return " ".join(self.path)

    @property
    def usage(self) -> str:
        parts = ["unsafie", *self.path, *(a.display for a in self.args)]
        if self.passthrough:
            parts.append("-- …")
        return " ".join(parts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.name,
            "group": self.group,
            "summary": self.summary,
            "usage": self.usage,
            "args": [
                {"name": a.name, "optional": a.optional, "repeat": a.repeat} for a in self.args
            ],
            "flags": [
                {
                    "flag": f"--{f.long}",
                    "short": f"-{f.short}" if f.short else None,
                    "value": f.value or None,
                    "default": f.default or None,
                    "help": f.help,
                }
                for f in self.flags
            ],
            "examples": list(self.examples),
            "phase": self.phase,
            "ready": self.phase <= READY_THROUGH,
            "internal": self.internal,
        }


def _arg(text: str) -> Arg:
    repeat = text.endswith("...")
    body = text.removesuffix("...")
    optional = body.endswith("?")
    return Arg(body.removesuffix("?"), optional, repeat)


def _flag(text: str) -> Flag:
    body, _, help_text = text.partition("#")
    body, _, default = body.strip().partition("|")
    names, _, value = body.partition("=")
    short, _, long = names.strip().rpartition("/")
    return Flag(long.lstrip("-"), short.lstrip("-"), value, default, help_text.strip())


def _flags(text: str) -> tuple[Flag, ...]:
    parts: list[str] = []
    for chunk in text.split(";"):
        piece = chunk.strip()
        if not piece:
            continue
        if "#" in piece:
            parts.append(piece)
        else:
            parts.extend(piece.split())
    return tuple(_flag(part) for part in parts)


def c(
    path: str,
    group: str,
    summary: str,
    args: str = "",
    flags: str = "",
    examples: tuple[str, ...] = (),
    phase: int = 1,
    internal: bool = False,
    passthrough: bool = False,
) -> Cmd:
    return Cmd(
        tuple(path.split()),
        group,
        summary,
        tuple(_arg(a) for a in args.split()),
        _flags(flags),
        examples,
        phase,
        internal,
        passthrough,
    )


READY_THROUGH = 7

GLOBAL_FLAGS: tuple[Flag, ...] = (
    _flag("--json # machine readable output"),
    _flag("--quiet # print nothing but errors"),
    _flag("--no-color # plain text, no escapes"),
    _flag("--api=URL # the unsafie server to talk to"),
    _flag("--token=TOKEN # authorize with this token instead of the stored one"),
    _flag("--chat=ID # act in this chat"),
    _flag("--machine=NAME # act on this machine"),
    _flag("-h/--help # this help"),
)

GROUPS: dict[str, str] = {
    "meta": "help, version, local settings",
    "auth": "tokens issued by the bot in Telegram",
    "chat": "talk to the human: messages, files, reactions, polls, history",
    "pages": "publish long results as web pages",
    "github": "accounts, repositories, short lived tokens, gh passthrough",
    "ci": "run the CI of your repositories on the pool",
    "machines": "take, release and drive machines in the pool",
    "store": "blobs, key-value, secrets",
    "chrome": "a real Chrome on the machine: navigate, click, read, screenshot",
    "automation": "schedules, watches, repository subscriptions",
    "admin": "the pool from the operator side",
    "internal": "what the machine runs for itself",
}

COMMANDS: tuple[Cmd, ...] = (
    c(
        "help",
        "meta",
        "what this CLI can do; a topic, a group or a command",
        "topic?...",
        "--json # the whole command index at once",
        ("unsafie help", "unsafie help chrome", "unsafie help --json", "unsafie help tour"),
    ),
    c("version", "meta", "versions of the CLI, the wire contract and the server"),
    c("completion", "meta", "shell completion script", "shell", examples=("unsafie completion zsh",)),
    c("config show", "meta", "every setting with the place it comes from"),
    c("config get", "meta", "one setting", "key"),
    c("config set", "meta", "store a setting", "key value", examples=("unsafie config set chat 1749187700",)),
    c("config unset", "meta", "forget a setting", "key"),
    c("config path", "meta", "where the config file lives"),
    c("doctor", "meta", "what is installed here, what answers, how fast", phase=3),
    c("update", "meta", "update the CLI in place", phase=10),
    c(
        "auth login",
        "auth",
        "store the token the bot gave you",
        flags="--token=TOKEN; --api=URL; --pair # ask Telegram instead of pasting",
        examples=("unsafie auth login --token uns_…",),
    ),
    c("auth status", "auth", "who am I, where does the token come from"),
    c("auth logout", "auth", "forget the stored token"),
    c("auth token", "auth", "print the token", flags="--raw # unmasked"),
    c("me", "auth", "the account behind the token", phase=2),
    c("quota", "auth", "limits and what is left today", phase=3),
    c(
        "say",
        "chat",
        "send a message to the chat",
        "text",
        "--reply-to=ID --buttons=JSON --silent --chat=ID",
        ('unsafie say "готово"', 'unsafie say "?" --buttons \'[["да","нет"]]\''),
        phase=2,
    ),
    c(
        "file",
        "chat",
        "send a file to the chat",
        "path",
        "--caption=TEXT --kind=KIND|document --silent",
        ("unsafie file report.pdf --caption 'отчёт'",),
        phase=2,
    ),
    c("album", "chat", "send several files as one message", "path...", "--caption=TEXT", phase=2),
    c("edit", "chat", "edit a message of mine", "id text", "--buttons=JSON", phase=2),
    c("rm", "chat", "delete messages", "id...", phase=2),
    c("react", "chat", "put a reaction on a message", "id emoji", "--big", phase=2),
    c("pin", "chat", "pin a message", "id", "--silent", phase=2),
    c("unpin", "chat", "unpin a message", "id?", phase=2),
    c("forward", "chat", "forward or copy a message", "id", "--to=CHAT --copy --caption=TEXT", phase=2),
    c("typing", "chat", "show a chat action for a few seconds", "action?", phase=2),
    c("poll", "chat", "send a poll", "question", "-o/--option=TEXT --multiple --quiz --correct=N --close-in=WHEN", phase=2),
    c("dice", "chat", "throw a dice, dart, basketball, football, bowling or slot", "emoji?", phase=2),
    c("location", "chat", "send a point on the map", "lat lon", "--title=TEXT --address=TEXT", phase=2),
    c("contact", "chat", "send a contact", "phone name", "--last=NAME", phase=2),
    c("note", "chat", "write a line into the live log of this turn", "text", phase=2),
    c("progress", "chat", "report progress into the live log", "value", "--of=TEXT", phase=2),
    c("history search", "chat", "search this chat", "query", "--who=WHO --since=AGE --limit=N|20", phase=9),
    c("history get", "chat", "a slice of this chat", "", "--id=ID --around=N|5 --limit=N|20", phase=9),
    c("chat info", "chat", "about the chat", "", "--id=CHAT", phase=9),
    c("chat member", "chat", "who a user is here", "user", phase=9),
    c("chat ban", "chat", "ban a member", "user", "--until=WHEN --revoke --unban", phase=9),
    c("chat mute", "chat", "mute a member", "user", "--until=WHEN --unmute", phase=9),
    c("chat invite", "chat", "an invite link", "", "--limit=N --expires=WHEN --name=TEXT", phase=9),
    c(
        "page create",
        "pages",
        "publish markdown as a page and print its link",
        "file",
        "--title=TEXT",
        ("unsafie page create report.md --title 'Бенчмарк'", "cat r.md | unsafie page create -"),
        phase=2,
    ),
    c("page list", "pages", "pages I published", "", "--limit=N|20", phase=2),
    c("page update", "pages", "replace the content of a page", "slug file", "--title=TEXT", phase=2),
    c("page rm", "pages", "delete a page", "slug", phase=2),
    c("account add", "github", "attach a GitHub token", "token", examples=("unsafie account add ghp_…",), phase=5),
    c("account list", "github", "attached GitHub accounts", phase=5),
    c("account rm", "github", "detach an account by login", "login", phase=5),
    c("repo list", "github", "repositories I can reach", "", "--limit=N|50", phase=5),
    c("repo add", "github", "bind a repository", "ref", "--alias=NAME", phase=5),
    c("repo rm", "github", "unbind a repository", "ref", phase=5),
    c("repo info", "github", "description, default branch, languages, activity", "ref", phase=5),
    c("repo sync", "github", "refresh the list of repositories", phase=5),
    c(
        "repo clone",
        "github",
        "clone with credentials already wired in",
        "ref dir?",
        "--branch=NAME --depth=N",
        ("unsafie repo clone wprhvso/unsafie",),
        phase=5,
    ),
    c("github token", "github", "a short lived token for git, gh or curl", "", "--repo=REF --minutes=N|60", phase=5),
    c("github api", "github", "call the GitHub API as me", "path", "-X/--method=METHOD|GET; -f/--field=K=V", phase=5),
    c("gh", "github", "run gh with the token already set", "", "", ("unsafie gh -- pr create --fill",), phase=5, passthrough=True),
    c("git-credential", "github", "git credential helper", "action", phase=5, internal=True),
    c(
        "ci add",
        "ci",
        "run the CI of this repository on the pool",
        "repo",
        "--label=NAME|pool --jobs=N --idle=WHEN --lifetime=WHEN",
        ("unsafie ci add alice/app",),
        phase=8,
    ),
    c("ci list", "ci", "repositories wired to the pool", phase=8),
    c("ci status", "ci", "queue, live runners, recent jobs", "repo", phase=8),
    c("ci logs", "ci", "what the runners of this repository did", "repo", "--limit=N|50", phase=8),
    c("ci rm", "ci", "stop running this repository on the pool", "repo", "--drain", phase=8),
    c("ci snippet", "ci", "the runs-on block to paste into the workflow", "repo", phase=8),
    c(
        "machines",
        "machines",
        "my machines: state, idle time, what runs there",
        "",
        "--json",
        ("unsafie machines",),
        phase=3,
    ),
    c("take", "machines", "take machines from the pool", "count?", "--label=NAME --wait=SEC|180", phase=3),
    c("release", "machines", "give a machine back; it is destroyed", "name?", "--all", phase=3),
    c("rename", "machines", "give a machine a human name", "name new", phase=3),
    c(
        "run",
        "machines",
        "run a command on another machine",
        "command",
        "--on=NAME --timeout=SEC --cwd=DIR",
        ("unsafie run 'pytest -q' --on box-2",),
        phase=3,
    ),
    c("fan", "machines", "run the same command on every machine", "command", "--on=LIST --all --timeout=SEC", phase=3),
    c("cp", "machines", "copy a file between machines", "source target", phase=5),
    c("job submit", "machines", "run something in the background", "command", "--count=N|1 --name=TEXT", phase=3),
    c("job list", "machines", "background jobs", "", "--limit=N|20", phase=3),
    c("job logs", "machines", "output of a background job", "id", "-f/--follow", phase=3),
    c("job cancel", "machines", "stop a background job", "id", phase=3),
    c("term", "machines", "a link to the web terminal of this machine", "", "--machine=NAME", phase=7),
    c("blob put", "store", "store a file under a key", "key path?", phase=5),
    c("blob get", "store", "read a stored file", "key", "-o/--out=FILE", phase=5),
    c("blob ls", "store", "stored keys", "prefix?", "--limit=N|50", phase=5),
    c("blob rm", "store", "forget a key", "key", phase=5),
    c("blob url", "store", "a link to a stored file", "key", "--minutes=N|60", phase=5),
    c("kv set", "store", "remember a small value", "key value", phase=5),
    c("kv get", "store", "read a small value", "key", phase=5),
    c("kv ls", "store", "remembered keys", "prefix?", phase=5),
    c("kv rm", "store", "forget a small value", "key", phase=5),
    c("secret set", "store", "store a secret", "name", "--from-stdin --value=TEXT", phase=5),
    c("secret get", "store", "read a secret", "name", phase=5),
    c("secret ls", "store", "secret names", phase=5),
    c("secret rm", "store", "delete a secret", "name", phase=5),
    c("secret env", "store", "print secrets as export lines", "", "--prefix=TEXT", phase=5),
    c("chrome start", "chrome", "start Chrome on this machine", "", "--profile=NAME --size=WxH --headless", phase=6),
    c("chrome stop", "chrome", "close Chrome", "", "--save-profile", phase=6),
    c("chrome status", "chrome", "is it running, where, what is open", phase=6),
    c("chrome desktop", "chrome", "a link to the live desktop", "", "--open", phase=7),
    c("chrome goto", "chrome", "open a url", "url", "--wait=STATE --timeout=SEC", phase=6),
    c("chrome back", "chrome", "history back", phase=6),
    c("chrome forward", "chrome", "history forward", phase=6),
    c("chrome reload", "chrome", "reload the page", phase=6),
    c("chrome click", "chrome", "click an element", "selector", "--timeout=SEC", phase=6),
    c("chrome dblclick", "chrome", "double click", "selector", phase=6),
    c("chrome rclick", "chrome", "right click", "selector", phase=6),
    c("chrome hover", "chrome", "move the cursor over an element", "selector", phase=6),
    c("chrome type", "chrome", "type text into a field", "selector text", "--clear", phase=6),
    c("chrome press", "chrome", "press a key", "key", phase=6),
    c("chrome hotkey", "chrome", "press a combination", "keys", phase=6),
    c("chrome select", "chrome", "pick an option", "selector value", phase=6),
    c("chrome scroll", "chrome", "scroll to an element or by pixels", "selector?", "--by=PX", phase=6),
    c("chrome wait", "chrome", "wait for an element, a url or a condition", "selector?", "--url=PATTERN --js=EXPR --state=STATE --timeout=SEC", phase=6),
    c(
        "chrome shot",
        "chrome",
        "screenshot; comes back to the model as a picture",
        "",
        "-o/--out=FILE; --full; --send; --caption=TEXT",
        ("unsafie chrome shot", "unsafie chrome shot --send --caption 'вот так'"),
        phase=6,
    ),
    c("chrome text", "chrome", "text of an element", "selector", phase=6),
    c("chrome html", "chrome", "html of the page or an element", "selector?", phase=6),
    c("chrome md", "chrome", "the page as markdown", "selector?", phase=6),
    c("chrome attr", "chrome", "an attribute of an element", "selector name", phase=6),
    c("chrome value", "chrome", "value of a field", "selector", phase=6),
    c("chrome url", "chrome", "current url", phase=6),
    c("chrome title", "chrome", "current title", phase=6),
    c("chrome eval", "chrome", "evaluate javascript in the page", "expression", phase=6),
    c("chrome script", "chrome", "run a javascript file in the page", "file", "--on-load", phase=6),
    c("chrome tabs", "chrome", "open tabs", phase=6),
    c("chrome tab", "chrome", "new, close or switch a tab", "action index?", "--url=URL", phase=6),
    c("chrome upload", "chrome", "put a file into a file input", "selector path", phase=6),
    c("chrome downloads", "chrome", "what the page downloaded", phase=6),
    c("chrome download", "chrome", "fetch a downloaded file", "name", "-o/--out=FILE --send", phase=6),
    c("chrome cookies", "chrome", "export or import cookies", "", "--export=FILE --import=FILE", phase=6),
    c("chrome profile", "chrome", "list, delete, export or import profiles", "action name?", "--file=PATH", phase=6),
    c("setup", "meta", "install a toolchain on this machine", "what...", "--yes", phase=6),
    c("chrome tap add", "chrome", "intercept requests of the page", "name", "--url=PATTERN --action=WHAT --status=CODE", phase=6),
    c("chrome tap take", "chrome", "take an intercepted request", "name", "--timeout=SEC", phase=6),
    c("chrome tap replay", "chrome", "replay a request from inside the page", "name", "--body=FILE --timeout=SEC", phase=6),
    c("schedule add", "automation", "say or do something later", "text", "--when=WHEN --cron=EXPR --every=WHEN --task", phase=9),
    c("schedule list", "automation", "what is scheduled", phase=9),
    c("schedule rm", "automation", "delete a schedule", "id", "--all", phase=9),
    c("schedule pause", "automation", "pause or resume a schedule", "id", "--resume", phase=9),
    c("watch add", "automation", "watch a command and report when it turns", "name", "--cmd=COMMAND --if=CONDITION --every=WHEN --task --host=ALIAS", phase=9),
    c("watch list", "automation", "what is watched", phase=9),
    c("watch run", "automation", "run a watch right now", "id", phase=9),
    c("watch rm", "automation", "delete a watch", "id", "--all", phase=9),
    c("sub add", "automation", "subscribe this chat to repository events", "kind", "--repo=REF --filters=JSON", phase=9),
    c("sub list", "automation", "what this chat is subscribed to", phase=9),
    c("sub rm", "automation", "unsubscribe", "id", "--all", phase=9),
    c("tz get", "automation", "the timezone I work in", phase=9),
    c("tz set", "automation", "remember a timezone", "zone", phase=9),
    c("fetch", "automation", "a page or an api as markdown or json", "url", "--md --json --timeout=SEC", phase=9),
    c("fs read", "automation", "read a file with line numbers", "path", "--lines=A:B", phase=5),
    c("fs write", "automation", "write a file atomically from stdin", "path", phase=5),
    c("fs patch", "automation", "apply a unified diff from stdin", "path?", phase=5),
    c("fs replace", "automation", "replace exactly one occurrence", "path old new", "--all", phase=5),
    c("fs tree", "automation", "what is in a directory", "dir?", "--depth=N|2", phase=5),
    c("admin donors", "admin", "accounts that give the pool its machines", "", "--json", phase=7),
    c("admin donor add", "admin", "add a donor token", "", "--token=TOKEN --jobs=N|20 --label=TEXT", phase=7),
    c("admin donor test", "admin", "check a donor: rights, limits, repository", "login", phase=7),
    c("admin donor bootstrap", "admin", "create the donor repository and seed its secrets", "login", phase=7),
    c("admin donor rotate", "admin", "rotate the worker token of a donor", "login", phase=7),
    c("admin donor disable", "admin", "stop launching new jobs on a donor", "login", "--enable", phase=7),
    c("admin donor rm", "admin", "remove a donor", "login", phase=7),
    c("admin capacity", "admin", "idle, leased, ci, queue, waiting time", "", "--watch", phase=7),
    c("admin machines", "admin", "every machine in the pool", "", "--donor=LOGIN", phase=7),
    c("admin recycle", "admin", "destroy a machine now", "name", phase=7),
    c("admin quota", "admin", "limits of a user", "user", "--machines=N --minutes=N --priority=N", phase=7),
    c("admin ci", "admin", "pause or block the CI of a repository", "action repo", phase=8),
    c("admin users", "admin", "who uses the pool and how much", "", "--busy", phase=7),
    c("serve", "internal", "become a machine of the pool", "", "--token=TOKEN --profile=NAME", phase=3, internal=True),
    c(
        "ci-runner",
        "internal",
        "become a GitHub runner for exactly one job",
        "",
        "--jit=CONFIG --name=NAME --repo=SLUG --idle=SEC --lifetime=SEC",
        phase=8,
        internal=True,
    ),
)

TOPICS: dict[str, tuple[str, ...]] = {
    "tour": (
        "Ten minutes with unsafie",
        "",
        "  unsafie auth login --token uns_…      the bot gives you the token with /auth",
        "  unsafie machines                      what you already have",
        "  unsafie take 1                        a machine of your own",
        "  unsafie run 'uname -a' --on box-1     a command on it",
        "  unsafie repo clone owner/name         a real checkout, git works as usual",
        "  unsafie chrome start && unsafie chrome goto https://example.com",
        "  unsafie chrome shot                   the picture goes back to whoever asked",
        "  unsafie say 'готово'                  a message into the chat",
        "  unsafie page create report.md         a long answer as a web page",
        "  unsafie release --all                 the machine is destroyed, keep nothing on it",
    ),
    "markers": (
        "Structured output",
        "",
        "Commands print plain text. Anything the caller should see as more than text goes as one",
        "line:",
        "",
        '  ::unsafie::{"kind":"image","blob":"shots/a1b2","mime":"image/png"}',
        "",
        "The server strips those lines and turns them into pictures inside the tool result, files",
        "in the chat and notes in the live log. Kinds: image, file, note, link, sent, result,",
        "progress, error.",
    ),
    "exit-codes": (
        "Exit codes",
        "",
        "  0   done",
        "  1   failed",
        "  2   wrong usage",
        "  3   no token, or the token cannot do this",
        "  4   not found",
        "  5   a limit is in the way",
        "  69  the command exists but is not implemented yet",
    ),
    "config": (
        "Settings",
        "",
        "Order: flag, then environment, then ~/.config/unsafie/config.toml, then the default.",
        "",
        "  token    UNSAFIE_TOKEN    issued by /auth in Telegram",
        "  api      UNSAFIE_API      https://unsafie.com",
        "  chat     UNSAFIE_CHAT     which chat to talk to",
        "  machine  UNSAFIE_MACHINE  which machine to act on",
        "  format   UNSAFIE_FORMAT   text or json",
        "",
        "On a machine in the pool all of this is already set.",
    ),
}


def by_path(path: tuple[str, ...]) -> Cmd | None:
    for cmd in COMMANDS:
        if cmd.path == path:
            return cmd
    return None


def match(tokens: list[str]) -> tuple[Cmd, list[str]] | None:
    for size in (3, 2, 1):
        if len(tokens) >= size:
            found = by_path(tuple(tokens[:size]))
            if found is not None:
                return found, tokens[size:]
    return None


def in_group(group: str) -> list[Cmd]:
    return [cmd for cmd in COMMANDS if cmd.group == group and not cmd.internal]


def prefixed(prefix: tuple[str, ...]) -> list[Cmd]:
    return [cmd for cmd in COMMANDS if cmd.path[: len(prefix)] == prefix]


def index() -> dict[str, Any]:
    return {
        "cli": "unsafie",
        "ready_through_phase": READY_THROUGH,
        "globals": [
            {"flag": f"--{f.long}", "value": f.value or None, "help": f.help} for f in GLOBAL_FLAGS
        ],
        "groups": [
            {
                "name": name,
                "summary": summary,
                "commands": [cmd.name for cmd in in_group(name)],
            }
            for name, summary in GROUPS.items()
        ],
        "commands": [cmd.as_dict() for cmd in COMMANDS],
        "topics": list(TOPICS),
    }
