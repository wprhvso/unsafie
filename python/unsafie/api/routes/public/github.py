import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse

from unsafie.database import SessionLocal
from unsafie.database.repositories.github import GithubAppRepository
from unsafie.database.repositories.oauth_state import OAuthStateRepository
from unsafie.github.app import install, manifest
from unsafie.github.errors import GithubError
from unsafie.github.webhooks import router as webhooks
from unsafie.github.webhooks.verify import valid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gh", tags=["github"])

PAGE = """<!doctype html><meta charset="utf-8"><title>unsafie</title>
<style>body{font:16px/1.5 system-ui;margin:15vh auto;max-width:34rem;padding:0 1rem;color:#111}
a{color:#06c}code{background:#f2f2f2;padding:.1em .3em;border-radius:3px}</style>
<h1>{title}</h1><p>{body}</p>"""


def page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.replace("{title}", title).replace("{body}", body), status_code=status)


@router.post("/webhook")
async def webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
):
    body = await request.body()
    async with SessionLocal() as session:
        app = await GithubAppRepository(session).get()
    if app is None:
        logger.warning("webhook received but the app is not configured")
        return JSONResponse({"error": "app not configured"}, status_code=503)
    if not valid(app.webhook_secret, body, x_hub_signature_256):
        logger.warning("webhook %s: bad signature", x_github_delivery)
        return JSONResponse({"error": "bad signature"}, status_code=401)
    if not x_github_event or not x_github_delivery:
        return JSONResponse({"error": "missing headers"}, status_code=400)
    if x_github_event == "ping":
        return {"ok": True, "pong": True}
    payload = await request.json()
    await webhooks.handle(x_github_delivery, x_github_event, payload)
    return JSONResponse({"ok": True}, status_code=202)


@router.get("/oauth")
async def oauth(code: str = "", state: str = ""):
    if not code or not state:
        return page(
            "Something went wrong", "GitHub did not return a code. Try /gh in the chat again.", 400
        )
    async with SessionLocal() as session:
        row = await OAuthStateRepository(session).consume(state)
    if row is None:
        return page("The link has expired", "Run <code>/gh</code> in the chat again.", 400)
    try:
        account = await install.connect_user(row.user_id, code)
    except GithubError as e:
        logger.exception("oauth failed for user=%s", row.user_id)
        return page("Could not connect the account", str(e), 400)
    return page(
        f"Connected: {account.login}",
        "Go back to the chat. If the repositories you need are missing, add them to the app installation.",
    )


@router.get("/app/new", response_class=HTMLResponse)
async def app_new(name: str = manifest.NAME):
    body = manifest.as_json(name)
    html = (
        '<!doctype html><meta charset="utf-8"><title>Creating the GitHub App…</title>'
        '<body style="font:16px system-ui;margin:15vh auto;max-width:30rem;text-align:center">'
        "<p>Redirecting to GitHub…</p>"
        f'<form id="f" method="post" action="{manifest.create_url()}">'
        f'<input type="hidden" name="manifest" value=\'{body.replace("'", "&#39;")}\'>'
        '<button type="submit">Continue</button></form>'
        '<script>document.getElementById("f").submit()</script>'
    )
    return HTMLResponse(html)


@router.get("/app/created")
async def app_created(code: str = ""):
    if not code:
        return page("No code", "GitHub did not return a code for the app.", 400)
    try:
        info = await install.create_from_manifest(code)
    except GithubError as e:
        logger.exception("app manifest conversion failed")
        return page("Could not create the app", str(e), 400)
    return page(
        f"App {info['name']} created",
        f'Now install it on your repositories: <a href="{manifest.install_url(info["slug"])}">'
        f"github.com/apps/{info['slug']}</a>.",
    )
