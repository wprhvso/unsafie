import argparse
import json
import sys
from typing import Any


def _out(data: Any, ok: bool = True) -> int:
    if isinstance(data, dict):
        if "ok" not in data:
            data = {"ok": ok, **data}
    elif isinstance(data, list):
        data = {"ok": ok, "items": data}
    else:
        data = {"ok": ok, "result": data}
    sys.stdout.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="unsafie")
    subs = parser.add_subparsers(dest="cmd")

    subs.add_parser("me")

    p_setup = subs.add_parser("setup")
    p_setup.add_argument("tools", nargs="*", default=[])

    p_stop = subs.add_parser("stop")
    p_stop.add_argument("message", nargs="?", default=None)

    p_chat = subs.add_parser("chat")
    s_chat = p_chat.add_subparsers(dest="subcmd")

    p_csend = s_chat.add_parser("send")
    p_csend.add_argument("text")
    p_csend.add_argument("--reply-to", type=int, default=None)
    p_csend.add_argument("--buttons", default=None)
    p_csend.add_argument("--silent", action="store_true")
    p_csend.add_argument("--chat", default=None)

    p_csend_file = s_chat.add_parser("send-file")
    p_csend_file.add_argument("path")
    p_csend_file.add_argument("--name", default=None)
    p_csend_file.add_argument("--caption", default=None)
    p_csend_file.add_argument("--kind", default="document")
    p_csend_file.add_argument("--silent", action="store_true")
    p_csend_file.add_argument("--chat", default=None)

    p_csend_photo = s_chat.add_parser("send-photo")
    p_csend_photo.add_argument("path")
    p_csend_photo.add_argument("--caption", default=None)
    p_csend_photo.add_argument("--silent", action="store_true")
    p_csend_photo.add_argument("--chat", default=None)

    p_cedit = s_chat.add_parser("edit")
    p_cedit.add_argument("message_id", type=int)
    p_cedit.add_argument("text")
    p_cedit.add_argument("--buttons", default=None)

    p_cdel = s_chat.add_parser("delete")
    p_cdel.add_argument("message_ids", nargs="+", type=int)

    p_creact = s_chat.add_parser("react")
    p_creact.add_argument("message_id", type=int)
    p_creact.add_argument("emoji", nargs="?", default="👍")
    p_creact.add_argument("--big", action="store_true")

    p_cpin = s_chat.add_parser("pin")
    p_cpin.add_argument("message_id", type=int)
    p_cpin.add_argument("--unpin", action="store_true")
    p_cpin.add_argument("--silent", action="store_true")

    p_chist = s_chat.add_parser("history")
    p_chist.add_argument("--query", default=None)
    p_chist.add_argument("--limit", type=int, default=20)
    p_chist.add_argument("--since", default=None)

    p_cinfo = s_chat.add_parser("info")
    p_cinfo.add_argument("--chat", default=None)

    p_pages = subs.add_parser("pages")
    s_pages = p_pages.add_subparsers(dest="subcmd")

    p_pcreate = s_pages.add_parser("create")
    p_pcreate.add_argument("content")
    p_pcreate.add_argument("--title", default=None)

    p_pupdate = s_pages.add_parser("update")
    p_pupdate.add_argument("slug")
    p_pupdate.add_argument("content")
    p_pupdate.add_argument("--title", default=None)

    p_plist = s_pages.add_parser("list")
    p_plist.add_argument("--limit", type=int, default=20)

    p_pdel = s_pages.add_parser("delete")
    p_pdel.add_argument("slug")

    p_gh = subs.add_parser("github")
    s_gh = p_gh.add_subparsers(dest="subcmd")

    s_gh.add_parser("logins")

    p_ghuse = s_gh.add_parser("use")
    p_ghuse.add_argument("login", nargs="?", default=None)

    p_ghtok = s_gh.add_parser("token")
    p_ghtok.add_argument("--repo", default=None)
    p_ghtok.add_argument("--login", default=None)

    p_ghid = s_gh.add_parser("identity")
    p_ghid.add_argument("--login", default=None)

    p_br = subs.add_parser("browser")
    s_br = p_br.add_subparsers(dest="subcmd")

    p_bstart = s_br.add_parser("start")
    p_bstart.add_argument("--profile", default=None)
    p_bstart.add_argument("--size", default="1920x1080")
    p_bstart.add_argument("--headless", action="store_true")

    s_br.add_parser("stop")

    p_bgoto = s_br.add_parser("goto")
    p_bgoto.add_argument("url")
    p_bgoto.add_argument("--wait", default="load")
    p_bgoto.add_argument("--timeout", type=float, default=30.0)

    p_bclick = s_br.add_parser("click")
    p_bclick.add_argument("selector")
    p_bclick.add_argument("--button", default="left")
    p_bclick.add_argument("--clicks", type=int, default=1)

    p_btype = s_br.add_parser("type")
    p_btype.add_argument("selector")
    p_btype.add_argument("text")
    p_btype.add_argument("--clear", action="store_true")

    p_bpress = s_br.add_parser("press")
    p_bpress.add_argument("combination")

    p_bwait = s_br.add_parser("wait")
    p_bwait.add_argument("--selector", default=None)
    p_bwait.add_argument("--url", default=None)
    p_bwait.add_argument("--js", default=None)
    p_bwait.add_argument("--timeout", type=float, default=30.0)

    p_btext = s_br.add_parser("text")
    p_btext.add_argument("selector", nargs="?", default="body")

    p_bhtml = s_br.add_parser("html")
    p_bhtml.add_argument("selector", nargs="?", default=None)

    p_beval = s_br.add_parser("eval")
    p_beval.add_argument("expression")

    p_bshot = s_br.add_parser("shot")
    p_bshot.add_argument("--full", action="store_true")
    p_bshot.add_argument("--send", action="store_true")
    p_bshot.add_argument("--caption", default=None)

    p_bcookies = s_br.add_parser("cookies")
    p_bcookies.add_argument("--set", dest="cookie_json", default=None)

    args = parser.parse_args(argv)

    if not args.cmd:
        return _out({"error": "subcommand required"}, ok=False)

    try:
        if args.cmd == "setup":
            from unsafie.machine.toolchains import TOOLCHAINS, setup
            wanted = args.tools or list(TOOLCHAINS)
            return _out(setup(*wanted))

        if args.cmd == "me":
            from unsafie.cli.client import client
            return _out(client().call("GET", "/me"))

        if args.cmd == "stop":
            from unsafie.cli.stop import stop
            return _out(stop(args.message))

        if args.cmd == "chat":
            from unsafie.cli import chat
            if args.subcmd == "send":
                btns = json.loads(args.buttons) if args.buttons else None
                return _out(chat.send(args.text, reply_to=args.reply_to, buttons=btns, silent=args.silent, chat=args.chat))
            if args.subcmd == "send-file":
                return _out(chat.send_file(args.path, name=args.name, caption=args.caption, kind=args.kind, silent=args.silent, chat=args.chat))
            if args.subcmd == "send-photo":
                return _out(chat.send_photo(args.path, caption=args.caption, silent=args.silent, chat=args.chat))
            if args.subcmd == "edit":
                btns = json.loads(args.buttons) if args.buttons else None
                return _out(chat.edit(args.message_id, args.text, buttons=btns))
            if args.subcmd == "delete":
                return _out(chat.delete(*args.message_ids))
            if args.subcmd == "react":
                return _out(chat.react(args.message_id, args.emoji, big=args.big))
            if args.subcmd == "pin":
                return _out(chat.pin(args.message_id, unpin=args.unpin, silent=args.silent))
            if args.subcmd == "history":
                return _out(chat.history(query=args.query, limit=args.limit, since=args.since))
            if args.subcmd == "info":
                return _out(chat.info(args.chat))

        if args.cmd == "pages":
            from unsafie.cli import pages
            if args.subcmd == "create":
                return _out(pages.create(args.content, title=args.title))
            if args.subcmd == "update":
                return _out(pages.update(args.slug, args.content, title=args.title))
            if args.subcmd == "list":
                return _out(pages.listing(limit=args.limit))
            if args.subcmd == "delete":
                return _out(pages.delete(args.slug))

        if args.cmd == "github":
            from unsafie.cli import github
            if args.subcmd == "logins":
                return _out(github.logins())
            if args.subcmd == "use":
                return _out(github.use(args.login))
            if args.subcmd == "token":
                return _out(github.token(repo=args.repo, login=args.login))
            if args.subcmd == "identity":
                return _out(github.identity(login=args.login))

        if args.cmd == "browser":
            from unsafie.cli import browser
            if args.subcmd == "start":
                return _out(browser.start(profile=args.profile, size=args.size, headless=args.headless))
            if args.subcmd == "stop":
                return _out(browser.stop())
            if args.subcmd == "goto":
                return _out(browser.goto(args.url, wait=args.wait, timeout=args.timeout))
            if args.subcmd == "click":
                return _out(browser.click(args.selector, button=args.button, clicks=args.clicks))
            if args.subcmd == "type":
                return _out(browser.type_text(args.selector, args.text, clear=args.clear))
            if args.subcmd == "press":
                return _out(browser.press(args.combination))
            if args.subcmd == "wait":
                return _out(browser.wait(selector=args.selector, url=args.url, js=args.js, timeout=args.timeout))
            if args.subcmd == "text":
                return _out(browser.text(args.selector))
            if args.subcmd == "html":
                return _out(browser.html(args.selector))
            if args.subcmd == "eval":
                return _out(browser.evaluate(args.expression))
            if args.subcmd == "shot":
                return _out(browser.shot(full=args.full, send=args.send, caption=args.caption))
            if args.subcmd == "cookies":
                c_data = json.loads(args.cookie_json) if args.cookie_json else None
                return _out(browser.cookies(c_data))

        return _out({"error": f"unknown command {args.cmd}"}, ok=False)
    except Exception as exc:
        return _out({"error": str(exc)}, ok=False)
