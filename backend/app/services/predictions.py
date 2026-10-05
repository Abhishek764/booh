"""Authenticated history → numerical model/baseline → persistence → safe summary."""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from threading import BoundedSemaphore, Event, Lock
from typing import ParamSpec, TypeVar
from uuid import UUID

from backend.app.prediction_contracts import (
    PredictionAPIError,
    PredictionContext,
    PredictionRecord,
    validated_numerical,
)
from backend.app.repositories.predictions import OwnedPredictionRepository
from backend.app.security import utc_now
from backend.app.services.auth import Principal
from backend.app.services.prediction_models import PredictionModelRegistry
from backend.app.services.summaries import SummaryService
from backend.app.summary_contracts import (
    SUMMARY_VERSION,
    OutputValidator,
    SummaryInput,
    SummaryResult,
    deterministic_summary,
)
from ml.features import FeatureValidationError, normalize_history
from ml.prediction.contracts import (
    ApprovedModel,
    PredictionError,
    PredictionResult,
    utc_time,
)
from ml.prediction.service import PredictionService

PIPELINE_TIMEOUT_SECONDS = 45.0
_WORK_SLOTS = BoundedSemaphore(4)
P = ParamSpec("P")
T = TypeVar("T")


def _bounded(function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    # Cancellation of a coroutine cannot release a still-running DB/model worker.
    if not _WORK_SLOTS.acquire(blocking=False):
        raise PredictionAPIError("prediction_busy", 429)
    try:
        return function(*args, **kwargs)
    finally:
        _WORK_SLOTS.release()


class _Admission:
    def __init__(self) -> None:
        self._lock = Lock()
        self._attempts: dict[UUID, deque[float]] = {}

    def admit(self, owner_id: UUID) -> None:
        now = time.monotonic()
        with self._lock:
            for owner, attempts in tuple(self._attempts.items()):
                while attempts and attempts[0] <= now - 60:
                    attempts.popleft()
                if not attempts:
                    del self._attempts[owner]
            if owner_id not in self._attempts and len(self._attempts) >= 1024:
                raise PredictionAPIError("prediction_busy", 429)
            attempts = self._attempts.setdefault(owner_id, deque())
            if len(attempts) >= 10:
                raise PredictionAPIError("prediction_rate_limited", 429)
            attempts.append(now)


class PredictionPipelineService:
    def __init__(self, repository: OwnedPredictionRepository, *, summaries: SummaryService,
                 models: PredictionModelRegistry, clock: Callable[[], datetime] = utc_now) -> None:
        self._repository = repository
        self._summaries = summaries
        self._models = models
        self._clock = clock
        self._slots = BoundedSemaphore(4)
        self._admission = _Admission()

    async def authorize_baby(self, principal: Principal, *, baby_id: UUID) -> None:
        try:
            async with asyncio.timeout(PIPELINE_TIMEOUT_SECONDS):
                owned = await asyncio.to_thread(_bounded, self._repository.owns_baby, owner_id=principal.user_id, baby_id=baby_id)
                if not owned:
                    raise PredictionAPIError("resource_not_found", 404)
        except PredictionAPIError:
            raise
        except Exception:
            raise PredictionAPIError("service_unavailable") from None

    def _generate(self, principal: Principal, baby_id: UUID, cancelled: Event) -> PredictionRecord:
        try:
            if not self._repository.owns_baby(owner_id=principal.user_id, baby_id=baby_id):
                self._models.invalidate(principal.user_id, baby_id)
                raise PredictionAPIError("resource_not_found", 404)
            self._admission.admit(principal.user_id)
            as_of = utc_time(self._clock())
            context = self._repository.load_context(owner_id=principal.user_id, baby_id=baby_id, as_of=as_of)
            if context is None:
                raise PredictionAPIError("resource_not_found", 404)
            if context.baby_id != baby_id:
                raise PredictionAPIError("prediction_unavailable")
            records = normalize_history(context.history, baby_id=baby_id)
            # Most recent unclosed/not-yet-completed sleep, unless a later wake ended it.
            latest_sleep = max((event for event in records if event.event_type == "sleep"),
                               key=lambda event: (event.start_time, event.end_time is not None), default=None)
            latest_wake = max((event.start_time for event in records if event.event_type == "wake"), default=None)
            sleep_start = None
            if (latest_sleep is not None and (latest_sleep.end_time is None or latest_sleep.end_time > as_of)
                    and (latest_wake is None or latest_wake < latest_sleep.start_time)):
                sleep_start = latest_sleep.start_time

            def infer(engine: PredictionService) -> PredictionResult:
                if cancelled.is_set():
                    raise PredictionAPIError("prediction_unavailable")
                return engine.predict(records, baby_id=baby_id, as_of=as_of, timezone_name=context.timezone_name,
                                      date_of_birth=context.date_of_birth, sleep_started_at=sleep_start)

            numerical = validated_numerical(self._models.run(owner_id=principal.user_id, context=context, infer=infer), as_of=as_of)
            if cancelled.is_set():
                raise PredictionAPIError("prediction_unavailable")
            persisted = self._repository.create_owned(owner_id=principal.user_id, context=context, numerical=numerical)
            if persisted is None:
                self._models.invalidate(principal.user_id, baby_id)
                raise PredictionAPIError("resource_not_found", 404)
            if persisted.baby_id != baby_id or persisted.numerical != numerical:
                raise PredictionAPIError("prediction_unavailable")
            return persisted
        except PredictionAPIError:
            raise
        except PredictionError as exc:
            if exc.code == "insufficient_history":
                raise PredictionAPIError("insufficient_history", 422) from None
            if exc.code == "overlapping_sleep_history":
                raise PredictionAPIError("invalid_history", 422) from None
            raise PredictionAPIError("prediction_unavailable") from None
        except FeatureValidationError:
            raise PredictionAPIError("invalid_history", 422) from None
        except Exception:
            raise PredictionAPIError("service_unavailable") from None

    async def predict(self, principal: Principal, *, baby_id: UUID) -> PredictionRecord:
        if not self._slots.acquire(blocking=False):
            raise PredictionAPIError("prediction_busy", 429)
        cancelled = Event()
        try:
            async with asyncio.timeout(PIPELINE_TIMEOUT_SECONDS):
                record = await asyncio.to_thread(_bounded, self._generate, principal, baby_id, cancelled)
                numbers = record.numerical
                minimal = SummaryInput(numbers.expected_sleep_minutes, numbers.wake_probability_60m, numbers.baseline_minutes)
                try:
                    summary = await self._summaries.summarize(SummaryInput.from_mapping(minimal.as_dict()))
                    OutputValidator().validate_text(summary.text, minimal)
                    if (type(summary) is not SummaryResult or type(summary.used_fallback) is not bool
                            or summary.summary_version != SUMMARY_VERSION
                            or summary.used_fallback != (summary.reason is not None)
                            or summary.provider_model is not None and (type(summary.provider_model) is not str
                                or re.fullmatch(r"(?:google/)?gemma[A-Za-z0-9._:-]{0,80}", summary.provider_model, re.IGNORECASE) is None)
                            or summary.reason not in {None, "invalid_summary_input", "provider_disabled", "provider_configuration_invalid",
                                                      "provider_busy", "provider_timeout", "provider_failed", "invalid_summary_output"}):
                        raise ValueError("invalid_summary_output")
                except Exception:
                    summary = SummaryResult(deterministic_summary(minimal), True, "invalid_summary_output")
                finished = await asyncio.to_thread(_bounded, self._repository.finish_summary, owner_id=principal.user_id,
                                                 prediction_id=record.id, summary=summary)
                if finished is None:
                    await asyncio.to_thread(_bounded, self._models.invalidate, principal.user_id, baby_id)
                    raise PredictionAPIError("resource_not_found", 404)
                if finished.numerical != numbers or finished.id != record.id or finished.baby_id != baby_id:
                    raise PredictionAPIError("prediction_unavailable")
                return finished
        except PredictionAPIError:
            raise
        except TimeoutError:
            raise PredictionAPIError("prediction_timeout") from None
        except Exception:
            raise PredictionAPIError("service_unavailable") from None
        finally:
            cancelled.set()
            self._slots.release()

    async def list_predictions(self, principal: Principal, *, baby_id: UUID, limit: int, offset: int) -> list[PredictionRecord]:
        if not self._slots.acquire(blocking=False):
            raise PredictionAPIError("prediction_busy", 429)
        try:
            async with asyncio.timeout(PIPELINE_TIMEOUT_SECONDS):
                result = await asyncio.to_thread(_bounded, self._repository.list_owned, owner_id=principal.user_id,
                                                baby_id=baby_id, limit=limit, offset=offset)
                if result is None:
                    raise PredictionAPIError("resource_not_found", 404)
                return result
        except PredictionAPIError:
            raise
        except TimeoutError:
            raise PredictionAPIError("prediction_timeout") from None
        except Exception:
            raise PredictionAPIError("service_unavailable") from None
        finally:
            self._slots.release()

    def training_context(self, principal: Principal, *, baby_id: UUID) -> PredictionContext:
        """Authorized bounded snapshot for a trusted offline job, never an HTTP fit."""
        try:
            context = self._repository.load_context(owner_id=principal.user_id, baby_id=baby_id, as_of=utc_time(self._clock()))
            if context is None:
                raise PredictionAPIError("resource_not_found", 404)
            if context.baby_id != baby_id:
                raise PredictionAPIError("prediction_unavailable")
            return context
        except PredictionAPIError:
            raise
        except Exception:
            raise PredictionAPIError("service_unavailable") from None

    def install_evaluated_model(self, principal: Principal, *, baby_id: UUID, candidate: ApprovedModel,
                                history_revision: str) -> None:
        """Trusted offline integration only. There is no model-upload/training route."""
        try:
            now = utc_time(self._clock())
            with self._repository.locked_context(owner_id=principal.user_id, baby_id=baby_id, as_of=now) as context:
                if context is None:
                    raise PredictionAPIError("resource_not_found", 404)
                if context.baby_id != baby_id:
                    raise PredictionAPIError("prediction_unavailable")
                if history_revision != context.revision:
                    raise PredictionAPIError("history_changed", 409)
                self._models.install(owner_id=principal.user_id, context=context, candidate=candidate, now=now)
        except PredictionAPIError:
            self._models.discard(candidate)
            raise
        except Exception:
            self._models.discard(candidate)
            raise PredictionAPIError("service_unavailable") from None
