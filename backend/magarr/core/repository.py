"""Generic repository over a SQLAlchemy session.

Repositories never commit; the caller owns the unit of work (the session).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from magarr.core.db import ModelBase


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int


class Repository[ModelT: ModelBase]:
    model: type[ModelT]

    def __init__(self, session: Session, model: type[ModelT] | None = None) -> None:
        self.session = session
        if model is not None:
            self.model = model

    def get(self, entity_id: int) -> ModelT | None:
        return self.session.get(self.model, entity_id)

    def list(self, page: int = 1, page_size: int = 50) -> Page[ModelT]:
        page = max(page, 1)
        page_size = max(min(page_size, 1000), 1)
        total = self.session.scalar(select(func.count()).select_from(self.model)) or 0
        stmt = (
            select(self.model)
            .order_by(self.model.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.session.scalars(stmt))
        return Page(items=items, total=total, page=page, page_size=page_size)

    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        self.session.flush()
        return entity

    def update(self, entity: ModelT, **values: Any) -> ModelT:
        for key, value in values.items():
            if not hasattr(entity, key):
                raise AttributeError(f"{self.model.__name__} has no attribute {key!r}")
            setattr(entity, key, value)
        self.session.flush()
        return entity

    def delete(self, entity: ModelT) -> None:
        self.session.delete(entity)
        self.session.flush()
