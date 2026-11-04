"""Optional paging for list endpoints: ``?page=2&pageSize=100``.

Without the parameters a list comes back whole (as the UI expects); either way the full count
is in the ``X-Total-Count`` header.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Response
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

MAX_PAGE_SIZE = 1000


@dataclass(frozen=True)
class Paging:
    page: int | None
    page_size: int | None

    def apply[T](self, session: Session, stmt: Select[T], response: Response) -> Select[T]:
        """``stmt`` limited to the page, with X-Total-Count set on ``response``."""
        total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        response.headers["X-Total-Count"] = str(total or 0)
        if self.page is None and self.page_size is None:
            return stmt
        size = self.page_size or 100
        return stmt.offset(((self.page or 1) - 1) * size).limit(size)


def _paging(
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(alias="pageSize", ge=1, le=MAX_PAGE_SIZE)] = None,
) -> Paging:
    return Paging(page, page_size)


PagingDep = Annotated[Paging, Depends(_paging)]
