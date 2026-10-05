"""Bounded CSV adapters. Uploaded text is data, never code or model input."""

from __future__ import annotations

import codecs
import csv
import io
import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import ClassVar, Literal

from backend.app.config import ImportLimits
from backend.app.event_values import NormalizedEvent, event_identity
from backend.app.models import EventType
from backend.app.services.events import EventError, normalize_event

ImporterKind = Literal["auto", "huckleberry", "generic"]
DateOrder = Literal["ymd", "mdy", "dmy"]
MAX_COLUMNS = 32
MAX_CELL_CHARS = 4096
MAX_RECORD_CHARS = 16384
MAX_REPORTED_ERRORS = 100


class CsvImportError(RuntimeError):
    """Fixed public code, without a filename, header, cell, or parser exception."""

    def __init__(self, code: str, status_code: int = 422) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class RowError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ImportRowError:
    row: int
    code: str


@dataclass(slots=True)
class ImportSummary:
    rows_processed: int = 0
    rows_imported: int = 0
    rows_skipped: int = 0
    rows_failed: int = 0
    duplicates: int = 0
    errors: list[ImportRowError] = field(default_factory=list)
    errors_truncated: bool = False

    def fail(self, row: int, code: str) -> None:
        self.rows_failed += 1
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append(ImportRowError(row=row, code=code))
        else:
            self.errors_truncated = True


@dataclass(slots=True)
class ParsedImport:
    events: list[NormalizedEvent]
    summary: ImportSummary


class _BoundedLines:
    """Bound each logical CSV record, including all quoted physical lines."""

    def __init__(self, text: str) -> None:
        self.stream = io.StringIO(text, newline="")
        self.record_chars = 0

    def __iter__(self) -> "_BoundedLines":
        return self

    def __next__(self) -> str:
        line = self.stream.readline(MAX_RECORD_CHARS + 1)
        if not line:
            raise StopIteration
        self.record_chars += len(line)
        if self.record_chars > MAX_RECORD_CHARS:
            raise CsvImportError("record_too_large", 413)
        return line


def _check_cells(cells: list[str]) -> None:
    if len(cells) > MAX_COLUMNS:
        raise CsvImportError("too_many_columns", 413)
    for cell in cells:
        if len(cell) > MAX_CELL_CHARS:
            raise RowError("cell_too_large")
        if any(
            unicodedata.category(char) in {"Cc", "Cf"} and char not in "\t\r\n"
            for char in cell
        ):
            raise RowError("unsafe_cell")
        if cell.lstrip().startswith(("=", "+", "-", "@")):
            raise RowError("unsafe_cell")


def _header_name(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


def _number(value: str) -> Decimal:
    if not re.fullmatch(r"\d{1,8}(?:\.\d{1,2})?", value):
        raise RowError("invalid_number")
    try:
        return Decimal(value)
    except InvalidOperation:
        raise RowError("invalid_number") from None


def _parse_iso_date(value: str) -> datetime:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?", value):
        raise ValueError("invalid_date")
    return datetime.fromisoformat(value)


class Importer(ABC):
    """Shared parser with provider-specific columns and value interpretation."""

    columns: ClassVar[dict[str, str]]
    event_types: ClassVar[dict[str, EventType]]
    ignored_types: ClassVar[frozenset[str]] = frozenset()

    def detect_columns(self, header: list[str]) -> dict[str, int]:
        mapping: dict[str, int] = {}
        names: set[str] = set()
        try:
            _check_cells(header)
        except RowError:
            raise CsvImportError("invalid_columns") from None
        if not header:
            raise CsvImportError("invalid_columns")
        for index, value in enumerate(header):
            name = _header_name(value)
            target = self.columns.get(name)
            if target is None or name in names or target in mapping:
                raise CsvImportError("invalid_columns")
            names.add(name)
            mapping[target] = index
        if not {"event_type", "start_time"}.issubset(mapping):
            raise CsvImportError("invalid_columns")
        return mapping

    def parse(
        self,
        payload: bytes | bytearray,
        *,
        limits: ImportLimits,
        timezone_name: str,
        date_order: DateOrder,
        now: datetime,
    ) -> ParsedImport:
        if len(payload) > limits.max_upload_bytes:
            raise CsvImportError("upload_too_large", 413)
        if date_order not in {"ymd", "mdy", "dmy"}:
            raise CsvImportError("invalid_request")
        try:
            text = payload.decode("utf-8-sig", errors="strict")
        except UnicodeError:
            raise CsvImportError("invalid_encoding") from None
        lines = _BoundedLines(text)
        reader = csv.reader(lines, dialect="excel", strict=True)
        result = ParsedImport(events=[], summary=ImportSummary())
        seen: set[tuple[object, ...]] = set()
        try:
            header = next(reader, None)
            if header is None:
                raise CsvImportError("empty_csv")
            mapping = self.detect_columns(header)
            while True:
                lines.record_chars = 0
                row_number = reader.line_num + 1
                row = next(reader, None)
                if row is None:
                    break
                if result.summary.rows_processed >= limits.max_rows:
                    raise CsvImportError("too_many_rows", 413)
                result.summary.rows_processed += 1
                try:
                    _check_cells(row)
                    if not row or all(not cell.strip() for cell in row):
                        result.summary.rows_skipped += 1
                        continue
                    if len(row) != len(header):
                        raise RowError("invalid_columns")
                    record = {name: row[index].strip() for name, index in mapping.items()}
                    event = self.normalize_record(
                        record, timezone_name=timezone_name, date_order=date_order, now=now
                    )
                    if event is None:
                        result.summary.rows_skipped += 1
                        continue
                    key = event_identity(event)
                    if key in seen:
                        result.summary.duplicates += 1
                        result.summary.rows_skipped += 1
                    else:
                        seen.add(key)
                        result.events.append(event)
                except RowError as exc:
                    result.summary.fail(row_number, str(exc))
                except (EventError, ValueError, OverflowError):
                    result.summary.fail(row_number, "invalid_event")
        except csv.Error:
            # Structural damage cannot be safely resynchronized. No writes occur.
            raise CsvImportError("malformed_csv") from None
        return result

    @abstractmethod
    def parse_date(self, value: str, date_order: DateOrder) -> datetime:
        """Return an aware timestamp or a local timestamp for explicit conversion."""

    @abstractmethod
    def parse_duration(self, value: str) -> int:
        """Return whole elapsed seconds."""

    def parse_amount(self, record: dict[str, str]) -> Decimal | None:
        value = record.get("feed_amount_ml", "")
        return None if not value else _number(value)

    def normalize_record(
        self,
        record: dict[str, str],
        *,
        timezone_name: str,
        date_order: DateOrder,
        now: datetime,
    ) -> NormalizedEvent | None:
        event_name = record["event_type"].lower()
        if event_name in self.ignored_types:
            return None
        event_type = self.event_types.get(event_name)
        if event_type is None:
            raise RowError("unsupported_event_type")
        start_value = record["start_time"]
        end_value = record.get("end_time", "")
        if record.get("date"):
            start_value = f"{record['date']} {start_value}"
            if end_value:
                end_value = f"{record['date']} {end_value}"
        try:
            start = self.parse_date(start_value, date_order)
            end = self.parse_date(end_value, date_order) if end_value else None
        except ValueError:
            raise RowError("invalid_date") from None
        duration_value = record.get("duration_seconds", "")
        duration = self.parse_duration(duration_value) if duration_value else None
        amount = self.parse_amount(record)
        zone = record.get("timezone") or timezone_name
        normalized = normalize_event(
            event_type=event_type, start_time=start, end_time=end,
            duration_seconds=duration, feed_amount_ml=amount, timezone_name=zone, now=now,
        )
        # Canonical elapsed duration and UTC end make repeated exports idempotent.
        if normalized.end_time is not None and duration is None:
            elapsed = (normalized.end_time - normalized.start_time).total_seconds()
            if not elapsed.is_integer():
                raise RowError("invalid_duration")
            duration = int(elapsed)
        if normalized.end_time is None and duration is not None:
            end = normalized.start_time + timedelta(seconds=duration)
        else:
            end = normalized.end_time
        return normalize_event(
            event_type=event_type, start_time=normalized.start_time, end_time=end,
            duration_seconds=duration, feed_amount_ml=amount, timezone_name=zone, now=now,
        )


class GenericEventImporter(Importer):
    """BOOH's explicit ISO timestamp / seconds / millilitres interchange format."""

    columns: ClassVar[dict[str, str]] = {
        "event type": "event_type", "start time": "start_time", "end time": "end_time",
        "duration seconds": "duration_seconds", "feed amount ml": "feed_amount_ml",
        "timezone": "timezone", "notes": "notes",
    }
    event_types: ClassVar[dict[str, EventType]] = {event.value: event for event in EventType}

    def parse_date(self, value: str, date_order: DateOrder) -> datetime:
        return _parse_iso_date(value)

    def parse_duration(self, value: str) -> int:
        if not re.fullmatch(r"\d{1,6}", value):
            raise RowError("invalid_duration")
        return int(value)


class HuckleberryImporter(Importer):
    """Allowlisted Huckleberry-style exports; no heuristics for ambiguous dates."""

    columns: ClassVar[dict[str, str]] = {
        "type": "event_type", "activity": "event_type", "event type": "event_type",
        "start": "start_time", "start time": "start_time", "end": "end_time",
        "end time": "end_time", "date": "date", "duration": "duration_seconds",
        "amount": "feed_amount_ml", "amount (ml)": "feed_amount_ml",
        "units": "units", "unit": "units", "timezone": "timezone",
        "notes": "notes", "details": "details", "start condition": "start_condition",
        "end condition": "end_condition",
    }
    event_types: ClassVar[dict[str, EventType]] = {
        "sleep": EventType.SLEEP, "nap": EventType.SLEEP,
        "feed": EventType.FEED, "feeding": EventType.FEED, "bottle": EventType.FEED,
        "nursing": EventType.FEED, "breastfeeding": EventType.FEED,
        "wake": EventType.WAKE, "awake": EventType.WAKE,
    }
    ignored_types = frozenset({"diaper", "potty", "growth", "medicine", "pumping", "tummy time", "solids"})

    def parse_date(self, value: str, date_order: DateOrder) -> datetime:
        try:
            return _parse_iso_date(value)
        except ValueError:
            pass
        date_format = {"ymd": "%Y/%m/%d", "mdy": "%m/%d/%Y", "dmy": "%d/%m/%Y"}[date_order]
        # Locale is a caller choice. Never guess US versus day-first slash dates.
        for time_format in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p"):
            try:
                return datetime.strptime(value, f"{date_format} {time_format}")
            except ValueError:
                continue
        raise ValueError("invalid_date")

    def parse_duration(self, value: str) -> int:
        clock = re.fullmatch(r"(\d{1,3}):([0-5]\d)(?::([0-5]\d))?", value)
        if clock:
            hours, minutes, seconds = clock.groups()
            return int(hours) * 3600 + int(minutes) * 60 + int(seconds or 0)
        units = re.fullmatch(r"(?:(\d{1,3})h\s*)?(?:(\d{1,3})m\s*)?(?:(\d{1,3})s)?", value.lower())
        if units and any(part is not None for part in units.groups()):
            hours, minutes, seconds = units.groups()
            return int(hours or 0) * 3600 + int(minutes or 0) * 60 + int(seconds or 0)
        # Bare Huckleberry duration numbers are minutes, not BOOH seconds.
        minutes = _number(value)
        seconds = minutes * 60
        if seconds != seconds.to_integral_value():
            raise RowError("invalid_duration")
        return int(seconds)

    def parse_amount(self, record: dict[str, str]) -> Decimal | None:
        value = record.get("feed_amount_ml", "")
        if not value:
            return None
        match = re.fullmatch(r"(\d{1,8}(?:\.\d{1,2})?)\s*(ml|oz)?", value.lower())
        if match is None:
            raise RowError("invalid_number")
        amount, suffix = match.groups()
        unit = record.get("units", "").lower()
        if suffix and unit and suffix != unit:
            raise RowError("invalid_unit")
        unit = suffix or unit or "ml"
        if unit not in {"ml", "oz"}:
            raise RowError("invalid_unit")
        number = _number(amount)
        if unit == "oz":
            number = (number * Decimal("29.5735295625")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return number


def select_importer(kind: ImporterKind, payload: bytes | bytearray) -> Importer:
    if kind == "huckleberry":
        return HuckleberryImporter()
    if kind == "generic":
        return GenericEventImporter()
    if kind != "auto":
        raise CsvImportError("invalid_request")
    try:
        # Detection examines only a bounded header; parsing validates the whole file.
        decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
        header_text = decoder.decode(payload[:MAX_RECORD_CHARS + 1], final=False)
        reader = csv.reader(_BoundedLines(header_text), strict=True)
        header = next(reader, [])
        if not header:
            raise CsvImportError("empty_csv")
        generic = GenericEventImporter()
        try:
            generic.detect_columns(header)
        except CsvImportError:
            huckleberry = HuckleberryImporter()
            huckleberry.detect_columns(header)
            return huckleberry
        return generic
    except UnicodeError:
        raise CsvImportError("invalid_encoding") from None
    except csv.Error:
        raise CsvImportError("malformed_csv") from None
