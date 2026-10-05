"""Authenticated upload budgets, CSV orchestration, and safe import summaries."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterable, Callable
from datetime import datetime
from threading import BoundedSemaphore

from starlette.concurrency import run_in_threadpool

from backend.app.config import ImportLimits
from backend.app.importers import (
    CsvImportError,
    DateOrder,
    ImporterKind,
    ImportSummary,
    select_importer,
)
from backend.app.repositories.imports import OwnedImportRepository
from backend.app.security import utc_now
from backend.app.services.auth import Principal
from backend.app.services.events import validate_timezone_name

UPLOAD_TIMEOUT_SECONDS = 30
MAX_CONCURRENT_IMPORTS = 4


def validate_upload_metadata(
    *, content_type: str | None, content_disposition: str | None,
    content_length: str | None, limits: ImportLimits,
) -> None:
    if content_type is None or len(content_type) > 100 or not re.fullmatch(
        r"(?:text/csv|application/csv)(?:\s*;\s*charset=(?:utf-8|\"utf-8\"))?",
        content_type.strip(), re.IGNORECASE,
    ):
        raise CsvImportError("unsupported_media_type", 415)
    if content_disposition is not None:
        # Metadata only: never joined to a path or used to create/open any file.
        if len(content_disposition) > 160 or not re.fullmatch(
            r'attachment;\s*filename="?[A-Za-z0-9][A-Za-z0-9 _-]{0,100}\.csv"?',
            content_disposition, re.IGNORECASE,
        ):
            raise CsvImportError("invalid_filename", 400)
        if content_disposition.count('"') not in {0, 2}:
            raise CsvImportError("invalid_filename", 400)
    if content_length is not None:
        if not re.fullmatch(r"\d{1,10}", content_length):
            raise CsvImportError("invalid_request", 400)
        if int(content_length) > limits.max_upload_bytes:
            raise CsvImportError("upload_too_large", 413)


class ImportService:
    """Receive bounded bytes only after checking the authenticated baby owner."""

    def __init__(
        self, repository: OwnedImportRepository, *, limits: ImportLimits,
        clock: Callable[[], datetime] = utc_now,
        on_change: Callable[[uuid.UUID, uuid.UUID], None] | None = None,
    ) -> None:
        self._repository = repository
        self._limits = limits
        self._clock = clock
        self._on_change = on_change
        self._slots = BoundedSemaphore(MAX_CONCURRENT_IMPORTS)

    def _owned_timezone(self, principal: Principal, baby_id: uuid.UUID) -> str:
        try:
            zone = self._repository.get_owned_timezone(
                baby_id=baby_id, owner_id=principal.user_id
            )
        except Exception:
            raise CsvImportError("service_unavailable", 503) from None
        if zone is None:
            raise CsvImportError("resource_not_found", 404)
        return zone

    async def import_csv(
        self, principal: Principal, *, baby_id: uuid.UUID,
        chunks: AsyncIterable[bytes], content_type: str | None,
        content_disposition: str | None = None, content_length: str | None = None,
        kind: ImporterKind = "auto", timezone_name: str | None = None,
        date_order: DateOrder = "ymd",
    ) -> ImportSummary:
        owned_zone = await run_in_threadpool(self._owned_timezone, principal, baby_id)
        validate_upload_metadata(
            content_type=content_type, content_disposition=content_disposition,
            content_length=content_length, limits=self._limits,
        )
        try:
            zone = validate_timezone_name(timezone_name if timezone_name is not None else owned_zone)
        except ValueError:
            raise CsvImportError("invalid_request") from None
        if not self._slots.acquire(blocking=False):
            raise CsvImportError("import_busy", 429)
        try:
            payload = bytearray()
            try:
                async with asyncio.timeout(UPLOAD_TIMEOUT_SECONDS):
                    async for chunk in chunks:
                        if len(chunk) > self._limits.max_upload_bytes - len(payload):
                            raise CsvImportError("upload_too_large", 413)
                        payload.extend(chunk)
            except TimeoutError:
                raise CsvImportError("upload_timeout", 408) from None
            return await run_in_threadpool(
                self._parse_and_persist, principal, baby_id, payload, kind, zone, date_order
            )
        finally:
            self._slots.release()

    def _parse_and_persist(
        self, principal: Principal, baby_id: uuid.UUID, payload: bytearray,
        kind: ImporterKind, timezone_name: str, date_order: DateOrder,
    ) -> ImportSummary:
        parsed = select_importer(kind, payload).parse(
            payload, limits=self._limits, timezone_name=timezone_name,
            date_order=date_order, now=self._clock(),
        )
        try:
            result = self._repository.import_owned_events(
                baby_id=baby_id, owner_id=principal.user_id, events=parsed.events,
            )
        except Exception:
            raise CsvImportError("service_unavailable", 503) from None
        if result is None:
            raise CsvImportError("resource_not_found", 404)
        parsed.summary.rows_imported = result.imported
        parsed.summary.duplicates += result.duplicates
        parsed.summary.rows_skipped += result.duplicates
        if result.imported and self._on_change is not None:
            self._on_change(principal.user_id, baby_id)
        return parsed.summary
