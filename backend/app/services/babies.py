"""Baby profile workflows and ownership policy."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Callable

from sqlalchemy.exc import SQLAlchemyError

from backend.app.repositories.babies import BabyRecord, BabyRepository
from backend.app.services.auth import Principal


class BabyError(RuntimeError):
    """Safe, client-facing baby resource failure."""

    def __init__(self, code: str, status_code: int = 404) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class BabyService:
    """Apply authenticated ownership to every baby repository operation."""

    def __init__(
        self,
        repository: BabyRepository,
        *,
        error_factory: Callable[[Exception], BabyError] | None = None,
        on_change: Callable[[uuid.UUID, uuid.UUID], None] | None = None,
    ) -> None:
        self._repository = repository
        self._error_factory = error_factory or self._default_error
        self._on_change = on_change

    def list_babies(self, principal: Principal) -> list[BabyRecord]:
        try:
            return self._repository.list_owned(owner_id=principal.user_id)
        except Exception as exc:
            raise self._error_factory(exc) from None

    def create_baby(
        self,
        principal: Principal,
        *,
        display_name: str | None,
        date_of_birth: date | None,
        timezone: str,
    ) -> BabyRecord:
        try:
            return self._repository.create_owned(
                owner_id=principal.user_id,
                display_name=display_name,
                date_of_birth=date_of_birth,
                timezone=timezone,
            )
        except Exception as exc:
            raise self._error_factory(exc) from None

    def get_baby(self, principal: Principal, *, baby_id: uuid.UUID) -> BabyRecord:
        try:
            baby = self._repository.get_owned(
                baby_id=baby_id, owner_id=principal.user_id
            )
        except Exception as exc:
            raise self._error_factory(exc) from None
        if baby is None:
            raise BabyError("resource_not_found", 404)
        return baby

    def update_baby(
        self,
        principal: Principal,
        *,
        baby_id: uuid.UUID,
        changes: dict[str, object],
    ) -> BabyRecord:
        if not changes or not set(changes).issubset(
            {"display_name", "date_of_birth", "timezone"}
        ):
            raise BabyError("invalid_request", 422)
        try:
            baby = self._repository.update_owned(
                baby_id=baby_id, owner_id=principal.user_id, changes=changes
            )
        except Exception as exc:
            raise self._error_factory(exc) from None
        if baby is None:
            raise BabyError("resource_not_found", 404)
        if self._on_change is not None:
            self._on_change(principal.user_id, baby_id)
        return baby

    def delete_baby(self, principal: Principal, *, baby_id: uuid.UUID) -> None:
        try:
            deleted = self._repository.delete_owned(
                baby_id=baby_id, owner_id=principal.user_id
            )
        except Exception as exc:
            raise self._error_factory(exc) from None
        if not deleted:
            raise BabyError("resource_not_found", 404)
        if self._on_change is not None:
            self._on_change(principal.user_id, baby_id)

    @staticmethod
    def _default_error(exc: Exception) -> BabyError:
        if isinstance(exc, BabyError):
            return exc
        if isinstance(exc, SQLAlchemyError):
            return BabyError("service_unavailable", 503)
        return BabyError("service_unavailable", 503)


__all__ = ["BabyError", "BabyService"]
