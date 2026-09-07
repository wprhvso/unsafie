import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from unsafie import cluster, events, telemetry
from unsafie.api import static
from unsafie.api.routes.admin import admin_router
from unsafie.api.routes.public import public_router, share_router
from unsafie.database import engine
from unsafie.database.upgrade import upgrade
from unsafie.github.cache import sweeper
from unsafie.github.client.base import close_session
from unsafie.github.webhooks.cleanup import cleanup
from unsafie.github.webhooks.worker import worker
from unsafie.janitor import janitor
from unsafie.log import setup
from unsafie.scheduler.runner import runner
from unsafie.settings import settings
from unsafie.ssh.pool import pool
from unsafie.ssh.watchdog import watchdog
from unsafie.telegram import bots
from unsafie.telegram.poller import supervisor
from unsafie.telemetry import attrs

setup()
telemetry.setup()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with telemetry.span("app.startup", kind=telemetry.INTERNAL):
        logger.info("lifespan startup instance=%s role=%s", settings.instance_id, settings.role)
        await cluster.connect()
        with telemetry.detached():
            events.bus.start()
        await upgrade()
        with telemetry.detached():
            for loop in (cleanup, runner, watchdog, sweeper, supervisor, worker, janitor):
                loop.start()
        logger.info("lifespan ready")
    yield
    with telemetry.span("app.shutdown", kind=telemetry.INTERNAL):
        logger.info("lifespan shutdown")
        for loop in (supervisor, janitor, worker, sweeper, watchdog, runner, cleanup):
            await loop.stop()
        await pool.close_all()
        await bots.close_all()
        await close_session()
        await engine.dispose()
        await events.bus.stop()
        await cluster.close()
        logger.info("shutdown complete")
    telemetry.shutdown()


app = FastAPI(title="unsafie", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    telemetry.annotate(**{attrs.REQUEST_ID: request.headers.get("x-request-id")})
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
async def health(response: Response) -> dict[str, object]:
    redis = await cluster.health()
    if redis["status"] != "ok":
        response.status_code = 503
    return {
        "status": "ok" if redis["status"] == "ok" else "degraded",
        "instance": settings.instance_id,
        "role": settings.role,
        "redis": redis,
    }


if (assets := static.assets_dir()) is not None:
    app.mount("/_app", StaticFiles(directory=assets), name="assets")
    logger.info("serving the frontend bundle from %s", assets)
else:
    logger.warning("no frontend bundle at %s; nginx must serve it", settings.static_dir)

app.include_router(share_router)
telemetry.instrument_app(app)
