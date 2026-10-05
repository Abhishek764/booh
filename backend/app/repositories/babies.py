"""Owner-scoped persistence queries for baby profiles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import session_scope
from backend.app.models import Baby

_UPDATABLE_FIELDS = frozenset({"display_name", "date_of_birth", "timezone"})


@dataclass(frozen=True, slots=True)
class BabyRecord:
    """Persistence-independent baby data returned to the service layer."""

    id: uuid.UUID
    owner_id: uuid.UUID
    display_name: str | None
    date_of_birth: date | None
    timezone: str
    created_at: datetime
    updated_at: datetime


class BabyRepository(Protocol):
    """Persistence contract whose methods require the authenticated owner."""

    def list_owned(self, *, owner_id: uuid.UUID) -> list[BabyRecord]: ...

    def get_owned(self, *, baby_id: uuid.UUID, owner_id: uuid.UUID) -> BabyRecord | None: ...

    def create_owned(
        self,
        *,
        owner_id: uuid.UUID,
        display_name: str | None,
        date_of_birth: date | None,
        timezone: str,
    ) -> BabyRecord: ...

    def update_owned(
        self,
        *,
        baby_id: uuid.UUID,
        owner_id: uuid.UUID,
        changes: dict[str, object],
    ) -> BabyRecord | None: ...

    def delete_owned(self, *, baby_id: uuid.UUID, owner_id: uuid.UUID) -> bool: ...


def _record(baby: Baby) -> BabyRecord:
    return BabyRecord(
        id=baby.id,
        owner_id=baby.user_id,
        display_name=baby.display_name,
        date_of_birth=baby.date_of_birth,
        timezone=baby.timezone,
        created_at=baby.created_at,
        updated_at=baby.updated_at,
    )


class SqlAlchemyBabyRepository:
    """SQLAlchemy implementation with owner predicates in every query."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_owned(self, *, owner_id: uuid.UUID) -> list[BabyRecord]:
        with session_scope(self._session_factory) as session:
            babies = session.scalars(
                select(Baby)
                .where(Baby.user_id == owner_id)
                .order_by(Baby.created_at.asc(), Baby.id.asc())
            ).all()
            return [_record(baby) for baby in babies]

    def get_owned(
        self, *, baby_id: uuid.UUID, owner_id: uuid.UUID
    ) -> BabyRecord | None:
        with session_scope(self._session_factory) as session:
            baby = session.scalar(
                select(Baby).where(Baby.id == baby_id, Baby.user_id == owner_id)
            )
            return None if baby is None else _record(baby)

    def create_owned(
        self,
        *,
        owner_id: uuid.UUID,
        display_name: str | None,
        date_of_birth: date | None,
        timezone: str,
    ) -> BabyRecord:
        with session_scope(self._session_factory) as session:
            baby = Baby(
                user_id=owner_id,
                display_name=display_name,
                date_of_birth=date_of_birth,
                timezone=timezone,
            )
            session.add(baby)
            session.flush()
            session.refresh(baby)
            return _record(baby)

    def update_owned(
        self,
        *,
        baby_id: uuid.UUID,
        owner_id: uuid.UUID,
        changes: dict[str, object],
    ) -> BabyRecord | None:
        with session_scope(self._session_factory) as session:
            baby = session.scalar(
                select(Baby).where(Baby.id == baby_id, Baby.user_id == owner_id).with_for_update()
            )
            if baby is None:
                return None
            for field, value in changes.items():
                if field not in _UPDATABLE_FIELDS:
                    raise ValueError("unsupported baby field")
                setattr(baby, field, value)
            session.flush()
            session.refresh(baby)
            return _record(baby)

    def delete_owned(self, *, baby_id: uuid.UUID, owner_id: uuid.UUID) -> bool:
        with session_scope(self._session_factory) as session:
            baby = session.scalar(
                select(Baby).where(Baby.id == baby_id, Baby.user_id == owner_id).with_for_update()
            )
            if baby is None:
                return False
            session.delete(baby)
            return True


__all__ = ["BabyRecord", "BabyRepository", "SqlAlchemyBabyRepository"]
