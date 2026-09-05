import logging

import uvicorn

from unsafie import telemetry
from unsafie.log import setup
from unsafie.settings import settings


def main() -> None:
    setup()
    telemetry.setup()
    logging.getLogger(__name__).info(
        "starting uvicorn host=%s port=%s reload=%s model=%s",
        settings.host,
        settings.port,
        settings.reload,
        settings.claude_model,
    )
    uvicorn.run(
        "unsafie.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_config=None,
        access_log=False,
    )
