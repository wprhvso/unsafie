import logging

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.gh.context import SERVER, session_for, user_client
from unsafie.agent.tools.registry import register
from unsafie.database import SessionLocal
from unsafie.database.repositories.github import RepoRepository, UserRepoRepository
from unsafie.github import sealed_box, workspace
from unsafie.github.app import manifest
from unsafie.github.errors import GithubError, NotFound

logger = logging.getLogger(__name__)

REPO_ARGS = dict(repo=str)


@register(
    SERVER,
    "repo_info",
    "Information about a repository: description, default branch, size, languages, topics, "
    "open issues and pull requests, last push.",
    schema([], **REPO_ARGS),
)
@guarded
async def repo_info(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    info = await state.client.info()
    topics = ", ".join(info.get("topics") or [])
    lines = [
        f"{info.get('full_name')} — {info.get('description') or '(no description)'}",
        info.get("html_url") or "",
        f"default branch: {info.get('default_branch')}, {'private' if info.get('private') else 'public'}",
        f"language: {info.get('language')}, size: {info.get('size')} KB",
        f"open issues: {info.get('open_issues_count')}, stars: {info.get('stargazers_count')}, "
        f"forks: {info.get('forks_count')}",
        f"pushed: {info.get('pushed_at')}",
    ]
    if topics:
        lines.append(f"topics: {topics}")
    return text("\n".join(lines))


@register(
    SERVER,
    "repo_create",
    "Create a repository on the user's account (or in an organization via org=). Uses the user's "
    "account, not the app. After creation the app must be installed on it — if the app is set to "
    "'selected repositories', a link to add it is returned.",
    schema(["name"], name=str, org=str, description=str, private=bool, auto_init=bool, account=str),
)
@guarded
async def repo_create(ctx: ToolContext, args: dict) -> dict:
    client = await user_client(ctx.user_id, args.get("account"))
    created = await client.create_repo(
        args["name"],
        args.get("org"),
        description=args.get("description"),
        private=args.get("private", True),
        auto_init=args.get("auto_init", True),
    )
    owner, _, name = (created.get("full_name") or "").partition("/")
    async with SessionLocal() as session:
        repos = RepoRepository(session)
        existing = await repos.by_full_name(owner, name)
    lines = [f"repository created: {created.get('html_url')}"]
    if existing is None:
        lines.append(
            "The app does not see it yet. Ask the user to add the repository to the app installation: "
            "GitHub → Settings → Applications → unsafie → Configure. Until then repository tools "
            "will not work with it."
        )
    else:
        async with SessionLocal() as session:
            bound = await UserRepoRepository(session).bind(ctx.user_id, existing)
        lines.append(f"available as `{bound.alias}`")
    return text("\n".join(lines))


@register(
    SERVER,
    "repo_update",
    "Change repository settings: description, homepage, private, topics (comma-separated), "
    "default_branch, archived.",
    schema(
        [],
        description=str,
        homepage=str,
        private=bool,
        topics=str,
        default_branch=str,
        archived=bool,
        **REPO_ARGS,
    ),
)
@guarded
async def repo_update(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    done = []
    if raw := args.get("topics"):
        names = [t.strip().lower() for t in raw.split(",") if t.strip()]
        await state.client.set_topics(names)
        done.append("topics")
    fields = {
        k: args[k]
        for k in ("description", "homepage", "private", "default_branch", "archived")
        if args.get(k) is not None
    }
    if fields:
        await state.client.update(**fields)
        done += list(fields)
    if not done:
        raise GithubError("nothing to change")
    return text(f"{state.repo.full} updated: " + ", ".join(done))


@register(
    SERVER,
    "repo_alias",
    "Rename how a repository is addressed in this chat: ref — the current alias or owner/name, "
    "alias — the new short name. remove=true unbinds it from the user (the app installation is untouched).",
    schema(["ref"], ref=str, alias=str, remove=bool),
)
@guarded
async def repo_alias(ctx: ToolContext, args: dict) -> dict:
    async with SessionLocal() as session:
        repos = UserRepoRepository(session)
        if args.get("remove"):
            removed = await repos.unbind(ctx.user_id, args["ref"])
            if removed is None:
                raise NotFound(f"no repository '{args['ref']}'")
            return text(f"`{removed.alias}` unbound")
        if not args.get("alias"):
            raise GithubError("alias is required")
        renamed = await repos.rename(ctx.user_id, args["ref"], args["alias"])
        if renamed is None:
            raise NotFound(f"no repository '{args['ref']}'")
    return text(f"now addressed as `{renamed.alias}`")


@register(
    SERVER,
    "repo_secrets",
    "Actions secrets and variables: without arguments — the list (values of secrets are not "
    "readable). name + value — set (secret=false writes a variable instead). name + delete=true — remove.",
    schema([], name=str, value=str, secret=bool, delete=bool, **REPO_ARGS),
)
@guarded
async def repo_secrets(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    is_secret = args.get("secret", True)
    name = args.get("name")
    if name and args.get("delete"):
        if is_secret:
            await state.client.delete_secret(name)
        else:
            await state.client.delete_variable(name)
        return text(f"{'secret' if is_secret else 'variable'} {name} deleted")
    if name and args.get("value") is not None:
        if is_secret:
            key = await state.client.public_key()
            encrypted = sealed_box.seal(key["key"], args["value"])
            await state.client.put_secret(name, encrypted, key["key_id"])
        else:
            await state.client.put_variable(name, args["value"])
        return text(f"{'secret' if is_secret else 'variable'} {name} set in {state.repo.full}")
    secrets = await state.client.secrets()
    variables = await state.client.variables()
    lines = [f"{state.repo.full}:"]
    lines += [
        f"  secret {s['name']} (updated {s.get('updated_at', '')[:10]})" for s in secrets
    ] or ["  no secrets"]
    lines += [f"  var {v['name']} = {v.get('value')}" for v in variables] or ["  no variables"]
    return text("\n".join(lines))


@register(
    SERVER,
    "repo_protection",
    "Branch protection: branch — which one (the current one by default). Without other arguments — "
    "show the rules. enable=true sets a basic protection (PR review + status checks); "
    "disable=true removes protection. Only at an explicit request of the user.",
    schema([], branch=str, enable=bool, disable=bool, reviews=int, checks=str, repo=str),
)
@guarded
async def repo_protection(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    branch = args.get("branch") or state.branch
    if args.get("disable"):
        await state.client.unprotect_branch(branch)
        return text(f"protection removed from `{branch}`")
    if args.get("enable"):
        checks = [c.strip() for c in (args.get("checks") or "").split(",") if c.strip()]
        body = {
            "required_status_checks": {"strict": True, "contexts": checks} if checks else None,
            "enforce_admins": False,
            "required_pull_request_reviews": {
                "required_approving_review_count": int(args.get("reviews") or 1)
            },
            "restrictions": None,
        }
        await state.client.protect_branch(branch, body)
        return text(f"`{branch}` protected: PR review required")
    rules = await state.client.branch_protection(branch)
    if rules is None:
        return text(f"`{branch}` is not protected")
    reviews = (rules.get("required_pull_request_reviews") or {}).get(
        "required_approving_review_count"
    )
    checks = (rules.get("required_status_checks") or {}).get("contexts") or []
    return text(
        f"`{branch}`: reviews required = {reviews}, checks = {', '.join(checks) or 'none'}, "
        f"admins enforced = {(rules.get('enforce_admins') or {}).get('enabled')}"
    )


@register(
    SERVER,
    "repo_install_link",
    "A link for the user to manage which repositories the app can access, or to install it on a new "
    "account or organization.",
    schema([], organization=str),
)
@guarded
async def repo_install_link(ctx: ToolContext, args: dict) -> dict:
    from unsafie.github.app.auth import load_app

    app = await load_app()
    bound = await workspace.repos_of(ctx.user_id)
    lines = [f"Install or configure: {manifest.install_url(app.slug)}"]
    if bound:
        async with SessionLocal() as session:
            from unsafie.database.repositories.github import InstallationRepository

            for installation in await InstallationRepository(session).for_user(ctx.user_id):
                lines.append(
                    f"{installation.account_login}: {manifest.manage_url(installation.id)}"
                )
    return text("\n".join(lines))
