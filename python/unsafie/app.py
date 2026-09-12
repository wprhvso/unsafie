import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from unsafie import cluster, events, telemetry
from unsafie.agent import turns
from unsafie.agent.client import close_session as close_gemini
from unsafie.agent.recovery import recovery_supervisor
from unsafie.api import static
from unsafie.api.routes.admin import admin_router
from unsafie.api.routes.cli import cli_router
from unsafie.api.routes.machines import router as machines_router
from unsafie.api.routes.public import artifact_router, public_router
from unsafie.database import engine
from unsafie.database.upgrade import upgrade
from unsafie.github.cache import sweeper
from unsafie.github.client.base import close_session
from unsafie.github.webhooks.worker import worker
from unsafie.janitor import janitor
from unsafie.log import bind_contextvars, clear_contextvars, get_logger, setup
from unsafie.pool.ci.supervisor import ci_supervisor
from unsafie.pool.keeper import keeper
from unsafie.presence import presence
from unsafie.scheduler.runner import runner
from unsafie.settings import settings
from unsafie.ssh.pool import pool
from unsafie.ssh.watchdog import watchdog
from unsafie.telegram import bots
from unsafie.telegram.webhook import supervisor
from unsafie.telemetry import attrs

setup()
telemetry.setup()
logger = get_logger(__name__)

LOOPS = (runner, watchdog, sweeper, supervisor, worker, janitor, presence, keeper, ci_supervisor, recovery_supervisor)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with telemetry.span("app.startup", kind=telemetry.INTERNAL):
        logger.info("app.lifespan.startup", instance_id=settings.instance_id, role=settings.role)
        await cluster.connect()
        with telemetry.detached():
            events.bus.start()
        await upgrade()
        with telemetry.detached():
            await recovery_supervisor.startup_sweep()
            for loop in LOOPS:
                loop.start()
        logger.info("app.lifespan.ready")
    yield
    with telemetry.span("app.shutdown", kind=telemetry.INTERNAL):
        logger.info("app.lifespan.shutdown")
        await supervisor.pause()
        if left := await turns.drain(settings.shutdown_grace):
            logger.warning("app.lifespan.turns_draining", running_turns_count=len(left), turns=left)
        for loop in reversed(LOOPS):
            await loop.stop()
        await pool.close_all()
        await bots.close_all()
        await close_session()
        await close_gemini()
        await engine.dispose()
        await events.bus.stop()
        await cluster.close()
        logger.info("app.lifespan.complete")
    telemetry.shutdown()


app = FastAPI(title="unsafie", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    clear_contextvars()
    req_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    bind_contextvars(
        request_id=req_id,
        http_method=request.method,
        http_path=request.url.path,
        client_ip=request.client.host if request.client else None,
    )
    telemetry.annotate(**{attrs.REQUEST_ID: req_id})
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.exception(
            "http.request.failed",
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
        )
        raise
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "http.request.completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
    )
    return response


app.include_router(public_router)
app.include_router(admin_router)
app.include_router(cli_router)
app.include_router(machines_router)


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
    logger.info("serving frontend bundle", assets=assets)
else:
    logger.warning("no frontend bundle found", static_dir=str(settings.static_dir))

app.include_router(artifact_router)
telemetry.instrument_app(app)
