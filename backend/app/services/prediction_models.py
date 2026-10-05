"""Owner/baby-bound offline-approved model lifecycle; never fits or loads uploads."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from threading import RLock, Timer
from uuid import UUID

from backend.app.prediction_contracts import PredictionAPIError, PredictionContext
from ml.prediction.contracts import ApprovedModel, PredictionResult, utc_time
from ml.prediction.service import PredictionService


def _close(candidate: ApprovedModel) -> None:
    close = getattr(getattr(candidate, "model", None), "close", None)
    try:
        if callable(close):
            close()
    except Exception:
        pass  # Never reflect SDK/private exception details from lifecycle cleanup.


class PredictionModelRegistry:
    """Two memory-only models, serialized leases, replacement/deletion/TTL close."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._models: dict[tuple[UUID, UUID], tuple[ApprovedModel, str, Timer]] = {}
        self._closed = False

    def install(self, *, owner_id: UUID, context: PredictionContext, candidate: ApprovedModel, now: datetime) -> None:
        try:
            if type(candidate) is not ApprovedModel or not callable(getattr(candidate.model, "close", None)):
                raise PredictionAPIError("model_not_validated")
            candidate.__post_init__()
            ttl = (utc_time(candidate.provenance.trained_until) + timedelta(days=7) - utc_time(now)).total_seconds()
            if candidate.provenance.baby_id != context.baby_id or utc_time(candidate.evidence.validation_end) > utc_time(now) or ttl <= 0:
                raise PredictionAPIError("model_not_validated")
            with self._lock:
                if self._closed:
                    raise PredictionAPIError("prediction_unavailable")
                key = (owner_id, context.baby_id)
                if key not in self._models and len(self._models) >= 2:
                    raise PredictionAPIError("prediction_busy", 429)
                if any(entry[0].model is candidate.model for entry in self._models.values()):
                    raise PredictionAPIError("model_not_validated")
                self.invalidate(owner_id, context.baby_id)
                def expire() -> None:
                    with self._lock:
                        entry = self._models.get(key)
                        if entry is not None and entry[0] is candidate:
                            self.invalidate(owner_id, context.baby_id)

                timer = Timer(ttl, expire)
                timer.daemon = True
                self._models[key] = (candidate, context.revision, timer)
                timer.start()
        except Exception as exc:
            # The rejected candidate belongs to the trusted offline caller.
            with self._lock:
                if not any(entry[0].model is getattr(candidate, "model", None) for entry in self._models.values()):
                    _close(candidate)
            if isinstance(exc, PredictionAPIError):
                raise
            raise PredictionAPIError("model_not_validated") from None

    def run(self, *, owner_id: UUID, context: PredictionContext, infer: Callable[[PredictionService], PredictionResult]) -> PredictionResult:
        with self._lock:
            if self._closed:
                raise PredictionAPIError("prediction_unavailable")
            key = (owner_id, context.baby_id)
            entry = self._models.get(key)
            if entry is not None and entry[1] != context.revision:
                self.invalidate(owner_id, context.baby_id)
                entry = None
            result = infer(PredictionService(tabpfn_model=None if entry is None else entry[0]))
            if entry is not None and result.metadata.fallback_reason not in {None, "missing_features", "outside_model_support"}:
                self.invalidate(owner_id, context.baby_id)
            return result

    def invalidate(self, owner_id: UUID, baby_id: UUID) -> None:
        with self._lock:
            entry = self._models.pop((owner_id, baby_id), None)
            if entry is not None:
                entry[2].cancel()
                _close(entry[0])

    def clear_owner(self, owner_id: UUID) -> None:
        with self._lock:
            for owner, baby in tuple(self._models):
                if owner == owner_id:
                    self.invalidate(owner, baby)

    def discard(self, candidate: ApprovedModel) -> None:
        with self._lock:
            if not any(entry[0].model is getattr(candidate, "model", None) for entry in self._models.values()):
                _close(candidate)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for owner, baby in tuple(self._models):
                self.invalidate(owner, baby)
