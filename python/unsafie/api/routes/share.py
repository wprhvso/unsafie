"""Публичная страница ответа: /<slug>, слаг — 12 заглавных латинских букв.

Единственный маршрут, который стоит выставлять наружу; всё остальное в API —
административное, без авторизации.
"""

import json
from importlib.resources import files

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from yet_another_claude_bot.api.dependencies.database import Session
from yet_another_claude_bot.repositories.share import ShareRepository
from yet_another_claude_bot.slugs import is_slug

router = APIRouter(tags=["share"])

_TEMPLATE = files("yet_another_claude_bot.api").joinpath("answer.html").read_text("utf-8")


def render(content: str, title: str = "Answer") -> str:
    payload = json.dumps(content, ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__TITLE__", title).replace("__PAYLOAD__", payload)


@router.get("/{slug}", response_class=HTMLResponse, include_in_schema=False)
async def share_page(slug: str, session: Session) -> HTMLResponse:
    if not is_slug(slug):
        raise HTTPException(404)
    content = await ShareRepository(session).content(slug)
    if content is None:
        raise HTTPException(404)
    return HTMLResponse(render(content))
