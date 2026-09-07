import logging

from unsafie import artifacts
from unsafie.agent.tools.base import ToolContext, error, schema, text
from unsafie.agent.tools.registry import register

logger = logging.getLogger(__name__)

SERVER = "artifact"
TITLE_LIMIT = 200


@register(
    SERVER,
    "create_artifact",
    "Publish markdown as a web page and get a link to it (https://unsafie.com/HTWRPPQDOKIP). "
    "This is where the results of your work go: reports, code, logs, diffs, tables, long answers. "
    "The page renders headings, tables, code with highlighting, math and images. Send the link "
    "to the user with send_message. Make one artifact per result rather than one long page; "
    "several per turn is normal. title — optional, the page title.",
    schema(["content"], content=str, title=str),
)
async def create_artifact(ctx: ToolContext, args: dict) -> dict:
    content = args["content"]
    if not content.strip():
        return error("content is empty")
    title = (args.get("title") or "").strip()[:TITLE_LIMIT] or None
    artifact = await artifacts.publish(
        content=content,
        title=title,
        bot_id=ctx.bot_id,
        chat_id=ctx.chat_id,
        turn_id=ctx.turn_id,
    )
    if artifact is None:
        return error("no free link could be allocated, try again")
    logger.info("%s artifact=%s chars=%s", ctx.prefix, artifact.slug, len(content))
    return text(artifacts.url(artifact.slug))
