from pydantic import BaseModel


class PageParams(BaseModel):
    offset: int = 0
    limit: int = 50


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int
    limit: int

    @classmethod
    def of(cls, items: list[T], total: int, params: PageParams) -> "Page[T]":
        return cls(items=items, total=total, offset=params.offset, limit=params.limit)


class Ok(BaseModel):
    ok: bool = True
    detail: str | None = None
