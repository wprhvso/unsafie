import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from unsafie.api import static
from unsafie.api.routes.admin import admin_router
from unsafie.api.routes.public import public_router, share_router
from unsafie.database import SessionLocal, engine
from unsafie.database.repositories.delivery import DeliveryRepository
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.upgrade import upgrade
from unsafie.github.cache import sweeper
from unsafie.github.client.base import close_session
from unsafie.github.webhooks.cleanup import cleanup
from unsafie.log import setup
from unsafie.scheduler.runner import runner
from unsafie.settings import settings
from unsafie.ssh.pool import pool
from unsafie.ssh.watchdog import watchdog
from unsafie.telegram.lifecycle import start_all, stop_all

setup()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("lifespan startup")
    await upgrade()
    async with SessionLocal() as session:
        stale_turns = await TurnRepository(session).mark_stale_running()
        stale_deliveries = await DeliveryRepository(session).mark_stale()
    if stale_turns:
        logger.warning("%s turn(s) were running at shutdown, marked failed", stale_turns)
    if stale_deliveries:
        logger.warning("%s webhook delivery(ies) were unprocessed at shutdown", stale_deliveries)
    await start_all()
    for loop in (cleanup, runner, watchdog, sweeper):
        loop.start()
    logger.info("lifespan ready")
    yield
    logger.info("lifespan shutdown")
    for loop in (sweeper, watchdog, runner, cleanup):
        await loop.stop()
    await pool.close_all()
    await stop_all()
    await close_session()
    await engine.dispose()
    logger.info("shutdown complete")


app = FastAPI(title="unsafie", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "http !! %s %s failed after %.1fms",
            request.method,
            request.url.path,
            (time.perf_counter() - started) * 1000,
        )
        raise
    logger.info(
        "http %s %s status=%s %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


app.include_router(public_router)
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


if (assets := static.assets_dir()) is not None:
    app.mount("/_app", StaticFiles(directory=assets), name="assets")
    logger.info("serving the frontend bundle from %s", assets)
else:
    logger.warning("no frontend bundle at %s; nginx must serve it", settings.static_dir)

app.include_router(share_router)
