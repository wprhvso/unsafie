import json
import os
import subprocess
import sys
from pathlib import Path

from unsafie_cli import api
from unsafie_cli.errors import FAILED, NOT_FOUND, OK, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

HELPER = "!unsafie git-credential"


def account_add(call: Call, out: Out) -> int:
    token = call.arg("token")
    if token == "-":
        token = sys.stdin.read().strip()
    answer = api.client(call).call("POST", "/github/accounts", {"token": token})
    out.send(
        answer,
        [
            f"attached {answer.get('login')}",
            "another login stands beside this one; the same login replaces its token",
        ],
    )
    return OK


def account_list(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/github/accounts")
    if out.json_mode:
        out.send(answer)
        return OK
    rows = [[row["login"], row.get("scopes") or "fine-grained"] for row in answer.get("accounts", [])]
    if not rows:
        out.line("no github accounts attached")
        return OK
    out.table(rows, ["login", "scopes"])
    return OK


def account_rm(call: Call, out: Out) -> int:
    answer = api.client(call).call("DELETE", f"/github/accounts/{call.arg('login')}")
    out.send(answer, [f"detached {answer.get('login')}"])
    return OK


def repo_list(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/github/repos", params={"limit": call.flag("limit", "50")})
    if out.json_mode:
        out.send(answer)
        return OK
    rows = [
        [row["slug"], row.get("alias") or "-", row.get("default_branch") or "", "private" if row.get("private") else "public"]
        for row in answer.get("repos", [])
    ]
    if not rows:
        out.line("no repositories bound; add one: unsafie repo add owner/name")
        return OK
    out.table(rows, ["repository", "alias", "branch", "visibility"])
    return OK


def repo_add(call: Call, out: Out) -> int:
    body = {"ref": call.arg("ref"), "alias": call.flag("alias") or None}
    answer = api.client(call).call("POST", "/github/repos", body)
    out.send(answer, [f"bound {answer.get('slug')} as {answer.get('alias')}"])
    return OK


def repo_rm(call: Call, out: Out) -> int:
    answer = api.client(call).call("DELETE", f"/github/repos/{call.arg('ref')}")
    out.send(answer, [f"unbound {answer.get('ref')}"])
    return OK


def repo_sync(call: Call, out: Out) -> int:
    answer = api.client(call).call("POST", "/github/repos/sync", {})
    out.send(answer, [f"{answer.get('account')}: {answer.get('repos')} repositories"])
    return OK


def repo_info(call: Call, out: Out) -> int:
    ref = call.arg("ref")
    answer = api.client(call).call("POST", "/github/api", {"path": f"/repos/{ref}"})
    data = answer.get("result") or {}
    if out.json_mode:
        out.send(data)
        return OK
    out.send(
        data,
        [
            f"{data.get('full_name')} — {data.get('description') or 'no description'}",
            f"default branch {data.get('default_branch')}, {data.get('language') or 'no language'},"
            f" {data.get('open_issues_count', 0)} open issues",
            f"pushed {data.get('pushed_at')}",
        ],
    )
    return OK


def token(call: Call, out: Out) -> int:
    body = {"repo": call.flag("repo") or None, "minutes": int(call.flag("minutes") or "60")}
    answer = api.client(call).call("POST", "/github/token", body)
    if out.json_mode:
        out.send(answer)
        return OK
    out.line(str(answer.get("token")))
    if answer.get("note"):
        sys.stderr.write(f"note: {answer['note']}\n")
    return OK


def api_call(call: Call, out: Out) -> int:
    fields: dict[str, object] = {}
    for pair in call.many("field") if call.args.get("field") else []:
        key, _, value = str(pair).partition("=")
        fields[key] = value
    for pair in [call.flag("field")] if call.flag("field") else []:
        key, _, value = pair.partition("=")
        fields[key] = value
    body = {
        "path": call.arg("path"),
        "method": call.flag("method") or "GET",
        "body": fields or None,
    }
    answer = api.client(call).call("POST", "/github/api", body)
    out.send(answer.get("result"), [json.dumps(answer.get("result"), ensure_ascii=False, indent=1)])
    return OK


def _token_for(call: Call, repo: str | None = None) -> str:
    answer = api.client(call).call("POST", "/github/token", {"repo": repo})
    return str(answer.get("token") or "")


def gh(call: Call, out: Out) -> int:
    if not call.rest:
        raise Usage("nothing to pass to gh", "unsafie gh -- pr create --fill")
    binary = _which("gh")
    if binary is None:
        raise CliError("gh is not installed here", NOT_FOUND)
    env = dict(os.environ)
    env["GH_TOKEN"] = _token_for(call)
    done = subprocess.run([binary, *call.rest], env=env, check=False)
    return done.returncode


def clone(call: Call, out: Out) -> int:
    ref = call.arg("ref")
    target = call.arg("dir") or ref.split("/")[-1]
    binary = _which("git")
    if binary is None:
        raise CliError("git is not installed here", NOT_FOUND)
    token_value = _token_for(call, ref)
    url = f"https://x-access-token:{token_value}@github.com/{ref}.git"
    line = [binary, "clone", url, target]
    if call.flag("branch"):
        line += ["--branch", call.flag("branch")]
    if call.flag("depth"):
        line += ["--depth", call.flag("depth")]
    done = subprocess.run(line, check=False, capture_output=True, text=True)
    if done.returncode != 0:
        raise CliError(done.stderr.strip().replace(token_value, "***") or "clone failed", FAILED)
    _wire_credentials(Path(target), binary)
    out.send({"repo": ref, "path": target}, [f"cloned into {target}"])
    return OK


def _wire_credentials(target: Path, binary: str) -> None:
    if not target.is_dir():
        return
    subprocess.run(
        [binary, "-C", str(target), "config", "credential.https://github.com.helper", HELPER],
        check=False,
        capture_output=True,
    )
    subprocess.run(
        [binary, "-C", str(target), "remote", "set-url", "origin", _plain_url(target, binary)],
        check=False,
        capture_output=True,
    )


def _plain_url(target: Path, binary: str) -> str:
    done = subprocess.run(
        [binary, "-C", str(target), "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
    )
    url = done.stdout.strip()
    if "@github.com/" in url:
        return "https://github.com/" + url.split("@github.com/", 1)[1]
    return url


def credential(call: Call, out: Out) -> int:
    action = call.arg("action")
    if action != "get":
        return OK
    asked: dict[str, str] = {}
    for line in sys.stdin:
        key, _, value = line.strip().partition("=")
        if key:
            asked[key] = value
    repo = None
    path = asked.get("path")
    if path:
        repo = path.removesuffix(".git")
    out.line("username=x-access-token")
    out.line(f"password={_token_for(call, repo)}")
    return OK


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)
