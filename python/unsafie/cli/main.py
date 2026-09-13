import argparse
import json
import os
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

    p_serve = subs.add_parser("serve")
    p_serve.add_argument("--token", default=None)
    p_serve.add_argument("--api", default=None)

    p_setup = subs.add_parser("setup")
    p_setup.add_argument("tools", nargs="*", default=[])

    p_runner = subs.add_parser("ci-runner")
    p_runner.add_argument("--jit", default="")
    p_runner.add_argument("--name", default="")
    p_runner.add_argument("--repo", default="")
    p_runner.add_argument("--idle", type=float, default=300.0)
    p_runner.add_argument("--lifetime", type=float, default=3600.0)

    subs.add_parser("stop")

    p_chat = subs.add_parser("chat")
    s_chat = p_chat.add_subparsers(dest="subcmd")

    p_csend = s_chat.add_parser("send")
    p_csend.add_argument("text")
    p_csend.add_argument("--reply-to", type=int, default=None)
    p_csend.add_argument("--buttons", default=None)
    p_csend.add_argument("--silent", action="store_true")
    p_csend.add_argument("--chat", default=None)

    p_csend_file = s_chat.add_parser("send-file")
    p_csend_file.add_argument("paths", nargs="+")
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
    p_cedit.add_argument("--chat", default=None)

    p_cdel = s_chat.add_parser("delete")
    p_cdel.add_argument("message_ids", nargs="+", type=int)
    p_cdel.add_argument("--chat", default=None)

    p_creact = s_chat.add_parser("react")
    p_creact.add_argument("message_id", type=int)
    p_creact.add_argument("emoji", nargs="?", default="👍")
    p_creact.add_argument("--big", action="store_true")
    p_creact.add_argument("--chat", default=None)

    p_cpin = s_chat.add_parser("pin")
    p_cpin.add_argument("message_id", type=int)
    p_cpin.add_argument("--unpin", action="store_true")
    p_cpin.add_argument("--silent", action="store_true")
    p_cpin.add_argument("--chat", default=None)

    p_chist = s_chat.add_parser("history")
    p_chist.add_argument("--query", default=None)
    p_chist.add_argument("--limit", type=int, default=20)
    p_chist.add_argument("--since", default=None)
    p_chist.add_argument("--chat", default=None)

    p_cinfo = s_chat.add_parser("info")
    p_cinfo.add_argument("--chat", default=None)

    p_cdownload = s_chat.add_parser("download")
    p_cdownload.add_argument("file_id")
    p_cdownload.add_argument("-o", "--output", default=None)
    p_cdownload.add_argument("--chat", default=None)

    p_bloat = subs.add_parser("bloat2md")
    p_bloat.add_argument("path")
    p_bloat.add_argument("-o", "--output", default=None)
    p_bloat.add_argument("--images-dir", default=None)
    p_bloat.add_argument("--stdout", action="store_true")
    p_bloat.add_argument("--max-pages", type=int, default=50)
    p_bloat.add_argument("--no-sandbox", action="store_true")

    p_email = subs.add_parser("email")
    p_email.add_argument("email")
    p_email.add_argument("--raw", action="store_true", default=False)

    p_img = subs.add_parser("image")
    p_img.add_argument("prompt", nargs="?", default="Create a photo of a cute cat")
    p_img.add_argument("-o", "--output", default=None)
    p_img.add_argument("--timeout", type=float, default=120.0)

    p_pages = subs.add_parser("pages", aliases=["page"])
    s_pages = p_pages.add_subparsers(dest="subcmd")

    p_pcreate = s_pages.add_parser("create")
    p_pcreate.add_argument("content")
    p_pcreate.add_argument("--title", default=None)

    p_pupdate = s_pages.add_parser("update")
    p_pupdate.add_argument("slug")
    p_pupdate.add_argument("content")
    p_pupdate.add_argument("--title", default=None)

    p_pread = s_pages.add_parser("read")
    p_pread.add_argument("slug")
    p_pread.add_argument("-o", "--output", default=None)

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
    p_bwait.add_argument("sel", nargs="?", default=None)
    p_bwait.add_argument("--selector", default=None)
    p_bwait.add_argument("--state", default="visible")
    p_bwait.add_argument("--url", default=None)
    p_bwait.add_argument("--js", default=None)
    p_bwait.add_argument("--timeout", type=float, default=30.0)
    p_bwait.add_argument("--network-idle", action="store_true")
    p_bwait.add_argument("--idle-time", type=float, default=0.5)

    p_btext = s_br.add_parser("text")
    p_btext.add_argument("selector", nargs="?", default="body")

    p_bhtml = s_br.add_parser("html")
    p_bhtml.add_argument("selector", nargs="?", default=None)

    p_beval = s_br.add_parser("eval")
    p_beval.add_argument("expression")

    p_bshot = s_br.add_parser("shot")
    p_bshot.add_argument("-o", "--output", default=None)
    p_bshot.add_argument("--full", action="store_true")

    p_bcookies = s_br.add_parser("cookies")
    p_bcookies.add_argument("--set", dest="cookie_json", default=None)

    p_bback = s_br.add_parser("back")
    p_bback.add_argument("--timeout", type=float, default=30.0)

    p_bforward = s_br.add_parser("forward")
    p_bforward.add_argument("--timeout", type=float, default=30.0)

    p_breload = s_br.add_parser("reload")
    p_breload.add_argument("--ignore-cache", action="store_true")
    p_breload.add_argument("--timeout", type=float, default=30.0)

    s_br.add_parser("url")
    s_br.add_parser("title")

    p_bhover = s_br.add_parser("hover")
    p_bhover.add_argument("selector")

    p_bdrag = s_br.add_parser("drag")
    p_bdrag.add_argument("from_selector")
    p_bdrag.add_argument("to_selector")
    p_bdrag.add_argument("--steps", type=int, default=5)

    p_bupload = s_br.add_parser("upload")
    p_bupload.add_argument("selector")
    p_bupload.add_argument("path")

    p_bquery = s_br.add_parser("query")
    p_bquery.add_argument("selector")
    p_bquery.add_argument("--limit", type=int, default=20)

    p_bscroll = s_br.add_parser("scroll")
    p_bscroll.add_argument("--by", default=None)
    p_bscroll.add_argument("--to", default=None)
    p_bscroll.add_argument("--top", action="store_true")
    p_bscroll.add_argument("--bottom", action="store_true")

    p_bnet = s_br.add_parser("network")
    p_bnet.add_argument("--filter", dest="pattern", default=None)
    p_bnet.add_argument("--limit", type=int, default=50)
    p_bnet.add_argument("--clear", action="store_true")

    p_bblock = s_br.add_parser("block")
    p_bblock.add_argument("patterns", nargs="*", default=None)
    p_bblock.add_argument("--presets", default=None)
    p_bblock.add_argument("--clear", action="store_true")

    s_br.add_parser("tabs")

    p_btab = s_br.add_parser("tab")
    s_tab = p_btab.add_subparsers(dest="tab_action")
    p_tnew = s_tab.add_parser("new")
    p_tnew.add_argument("url", nargs="?", default=None)
    p_tswitch = s_tab.add_parser("switch")
    p_tswitch.add_argument("tab_id")
    p_tclose = s_tab.add_parser("close")
    p_tclose.add_argument("tab_id", nargs="?", default=None)

    p_bframe = s_br.add_parser("frame")
    p_bframe.add_argument("target", nargs="?", default=None)
    p_bframe.add_argument("--main", action="store_true")
    p_bframe.add_argument("--list", action="store_true")

    p_bcon = s_br.add_parser("console")
    p_bcon.add_argument("--level", default=None)
    p_bcon.add_argument("--limit", type=int, default=50)
    p_bcon.add_argument("--clear", action="store_true")

    p_bint = s_br.add_parser("intercept")
    p_bint.add_argument("pattern")
    p_bint.add_argument("--block", dest="block", action="store_true", default=True)
    p_bint.add_argument("--no-block", dest="block", action="store_false")
    p_bint.add_argument("--click", dest="click_selector", default=None)
    p_bint.add_argument("--timeout", type=float, default=30.0)

    p_vision = subs.add_parser("vision")
    p_vision.add_argument("paths", nargs="+")
    p_vision.add_argument("--caption", default=None)

    p_inline = subs.add_parser("inline")
    s_inline = p_inline.add_subparsers(dest="subcmd")
    p_iedit = s_inline.add_parser("edit")
    p_iedit.add_argument("text")
    p_iedit.add_argument("--inline-message-id", default=None)
    p_iedit.add_argument("--buttons", default=None)

    args = parser.parse_args(argv)

    if not args.cmd:
        return _out({"error": "subcommand required"}, ok=False)

    try:
        if args.cmd == "serve":
            token = args.token or os.environ.get("UNSAFIE_WORKER_TOKEN") or ""
            api = (
                args.api
                or os.environ.get("UNSAFIE_API")
                or os.environ.get("UNSAFIE_URL")
                or "http://127.0.0.1:8000"
            )
            if not token:
                sys.stderr.write("no worker token: set UNSAFIE_WORKER_TOKEN\n")
                return 0
            from unsafie.machine.daemon import serve

            return serve(api, token)

        if args.cmd == "setup":
            from unsafie.machine.toolchains import TOOLCHAINS, setup

            wanted = args.tools or list(TOOLCHAINS)
            for name, outcome in setup(*wanted).items():
                sys.stdout.write(f"{name}: {outcome}\n")
            sys.stdout.flush()
            return 0

        if args.cmd == "ci-runner":
            from unsafie.machine.runner import run_runner

            return run_runner(
                args.jit,
                name=args.name,
                repo=args.repo,
                idle=args.idle,
                lifetime=args.lifetime,
            )

        if args.cmd == "stop":
            from unsafie.cli.stop import stop

            return _out(stop())

        if args.cmd == "chat":
            if not getattr(args, "subcmd", None):
                return _out({"error": "missing subcommand for unsafie chat"}, ok=False)
            from unsafie.cli import chat

            if args.subcmd == "send":
                btns = json.loads(args.buttons) if args.buttons else None
                return _out(
                    chat.send(
                        args.text,
                        reply_to=args.reply_to,
                        buttons=btns,
                        silent=args.silent,
                        chat=args.chat,
                    ),
                )
            if args.subcmd == "send-file":
                if len(args.paths) == 1:
                    return _out(
                        chat.send_file(
                            args.paths[0],
                            name=args.name,
                            caption=args.caption,
                            kind=args.kind,
                            silent=args.silent,
                            chat=args.chat,
                        ),
                    )
                results = [
                    chat.send_file(
                        p,
                        name=args.name,
                        caption=args.caption if i == len(args.paths) - 1 else None,
                        kind=args.kind,
                        silent=args.silent,
                        chat=args.chat,
                    )
                    for i, p in enumerate(args.paths)
                ]
                return _out({"sent": results})
            if args.subcmd == "send-photo":
                return _out(
                    chat.send_photo(
                        args.path, caption=args.caption, silent=args.silent, chat=args.chat,
                    ),
                )
            if args.subcmd == "edit":
                btns = json.loads(args.buttons) if args.buttons else None
                return _out(chat.edit(args.message_id, args.text, buttons=btns, chat=args.chat))
            if args.subcmd == "delete":
                return _out(chat.delete(*args.message_ids, chat=args.chat))
            if args.subcmd == "react":
                return _out(chat.react(args.message_id, args.emoji, big=args.big, chat=args.chat))
            if args.subcmd == "pin":
                return _out(chat.pin(args.message_id, unpin=args.unpin, silent=args.silent, chat=args.chat))
            if args.subcmd == "history":
                return _out(chat.history(query=args.query, limit=args.limit, since=args.since, chat=args.chat))
            if args.subcmd == "info":
                return _out(chat.info(args.chat))
            if args.subcmd == "download":
                return _out(chat.download(args.file_id, output=args.output, chat=args.chat))

        if args.cmd == "email":
            from unsafie.cli import email

            code = email.get_code(args.email)
            if getattr(args, "raw", False):
                sys.stdout.write(f"{code}\n")
                sys.stdout.flush()
                return 0
            return _out({"code": code, "result": code, "email": args.email})

        if args.cmd == "image":
            from unsafie.cli import image

            return _out(image.generate(prompt=args.prompt, output=args.output, timeout=args.timeout))

        if args.cmd in ("pages", "page"):
            if not getattr(args, "subcmd", None):
                return _out({"error": "missing subcommand for unsafie pages"}, ok=False)
            from unsafie.cli import pages

            if args.subcmd == "create":
                return _out(pages.create(args.content, title=args.title))
            if args.subcmd == "update":
                return _out(pages.update(args.slug, args.content, title=args.title))
            if args.subcmd == "read":
                return _out(pages.read(args.slug, output=args.output))
            if args.subcmd == "delete":
                return _out(pages.delete(args.slug))

        if args.cmd == "github":
            if not getattr(args, "subcmd", None):
                return _out({"error": "missing subcommand for unsafie github"}, ok=False)
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
            if not getattr(args, "subcmd", None):
                return _out({"error": "missing subcommand for unsafie browser"}, ok=False)
            from unsafie.cli import browser

            if args.subcmd == "start":
                return _out(
                    browser.start(profile=args.profile, size=args.size, headless=args.headless),
                )
            if args.subcmd == "stop":
                return _out(browser.stop())
            if args.subcmd == "goto":
                return _out(
                    browser.goto(args.url, wait=args.wait, timeout=args.timeout),
                )
            if args.subcmd == "click":
                return _out(
                    browser.click(args.selector, button=args.button, clicks=args.clicks),
                )
            if args.subcmd == "type":
                return _out(
                    browser.type_text(args.selector, args.text, clear=args.clear),
                )
            if args.subcmd == "press":
                return _out(browser.press(args.combination))
            if args.subcmd == "wait":
                sel = args.sel or args.selector
                return _out(
                    browser.wait(
                        selector=sel,
                        state=args.state,
                        url=args.url,
                        js=args.js,
                        timeout=args.timeout,
                        network_idle=args.network_idle,
                        idle_time=args.idle_time,
                    ),
                )
            if args.subcmd == "back":
                return _out(browser.back(timeout=args.timeout))
            if args.subcmd == "forward":
                return _out(browser.forward(timeout=args.timeout))
            if args.subcmd == "reload":
                return _out(browser.reload(ignore_cache=args.ignore_cache, timeout=args.timeout))
            if args.subcmd == "url":
                return _out(browser.url())
            if args.subcmd == "title":
                return _out(browser.title())
            if args.subcmd == "hover":
                return _out(browser.hover(args.selector))
            if args.subcmd == "drag":
                return _out(browser.drag(args.from_selector, args.to_selector, steps=args.steps))
            if args.subcmd == "upload":
                return _out(browser.upload(args.selector, args.path))
            if args.subcmd == "query":
                return _out(browser.query(args.selector, limit=args.limit))
            if args.subcmd == "scroll":
                return _out(browser.scroll(by=args.by, to=args.to, top=args.top, bottom=args.bottom))
            if args.subcmd == "network":
                return _out(browser.network(pattern=args.pattern, limit=args.limit, clear=args.clear))
            if args.subcmd == "block":
                return _out(browser.block(patterns=args.patterns, presets=args.presets, clear=args.clear))
            if args.subcmd == "tabs":
                return _out(browser.tabs())
            if args.subcmd == "tab":
                if args.tab_action == "new":
                    return _out(browser.tab_new(args.url))
                if args.tab_action == "switch":
                    return _out(browser.tab_switch(args.tab_id))
                if args.tab_action == "close":
                    return _out(browser.tab_close(args.tab_id))
                return _out(browser.tabs())
            if args.subcmd == "frame":
                return _out(browser.frame(selector_or_id=args.target, main=args.main, list_frames=args.list))
            if args.subcmd == "console":
                return _out(browser.console(level=args.level, limit=args.limit, clear=args.clear))
            if args.subcmd == "intercept":
                return _out(
                    browser.intercept(
                        args.pattern,
                        block=args.block,
                        click_selector=args.click_selector,
                        timeout=args.timeout,
                    ),
                )
            if args.subcmd == "text":
                return _out(browser.text(args.selector))
            if args.subcmd == "html":
                return _out(browser.html(args.selector))
            if args.subcmd == "eval":
                return _out(browser.evaluate(args.expression))
            if args.subcmd == "shot":
                return _out(browser.shot(output=args.output, full=args.full))
            if args.subcmd == "cookies":
                c_data = json.loads(args.cookie_json) if args.cookie_json else None
                return _out(browser.cookies(c_data))

        if args.cmd == "bloat2md":
            from unsafie.cli import bloat2md

            res = bloat2md.run(
                args.path,
                output=args.output,
                images_dir=args.images_dir,
                to_stdout=args.stdout,
                max_pages=args.max_pages,
                no_sandbox=args.no_sandbox,
            )
            if args.stdout and res.get("ok"):
                return 0
            return _out(res, ok=res.get("ok", True))

        if args.cmd == "vision":
            from unsafie.cli import vision

            return _out(vision.attach(args.paths, caption=args.caption))

        if args.cmd == "inline":
            if not getattr(args, "subcmd", None):
                return _out({"error": "missing subcommand for unsafie inline"}, ok=False)
            from unsafie.cli import inline

            if args.subcmd == "edit":
                btns = json.loads(args.buttons) if args.buttons else None
                return _out(
                    inline.edit(args.text, inline_message_id=args.inline_message_id, buttons=btns),
                )

        return _out({"error": f"unknown command {args.cmd}"}, ok=False)
    except Exception as exc:
        return _out({"error": str(exc)}, ok=False)
