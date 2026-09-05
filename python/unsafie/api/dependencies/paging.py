from fastapi import Query

from unsafie.api.schemas.common import PageParams


def paging(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)) -> PageParams:
    return PageParams(offset=offset, limit=limit)
