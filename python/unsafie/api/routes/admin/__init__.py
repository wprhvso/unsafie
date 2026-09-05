from fastapi import APIRouter, Depends

from unsafie.api.dependencies.auth import admin_required
from unsafie.api.routes.admin import (
    bots,
    chats,
    config,
    credentials,
    deliveries,
    events,
    github,
    overview,
    schedule,
    shares,
    ssh,
    stats,
    subscriptions,
    turns,
    users,
    watches,
)

admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin_required)])

for module in (
    overview,
    bots,
    credentials,
    config,
    users,
    chats,
    turns,
    github,
    subscriptions,
    deliveries,
    schedule,
    watches,
    ssh,
    shares,
    stats,
    events,
):
    admin_router.include_router(module.router)

__all__ = ["admin_router"]
