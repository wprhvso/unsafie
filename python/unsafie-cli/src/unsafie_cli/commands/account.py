from unsafie_cli import api
from unsafie_cli.output import Out
from unsafie_cli.parser import Call


def me(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/me")
    if out.json_mode:
        out.send(answer)
        return 0
    token = answer.get("token", {})
    out.table(
        [
            ("user", str(answer.get("user_id"))),
            ("chat", str(answer.get("chat_id") or "—")),
            ("machine", str(answer.get("machine") or "—")),
            ("token", f"{token.get('name')} ({token.get('kind')})"),
            ("scopes", ", ".join(token.get("scopes", []))),
        ]
    )
    return 0
