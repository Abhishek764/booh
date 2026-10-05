"""Gemma → OutputValidator → safe text/fallback, without numerical mutation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from threading import BoundedSemaphore

from backend.app.config import ConfigurationError
from backend.app.providers.gemma import GemmaProvider, SummaryProvider
from backend.app.summary_config import GemmaSettings
from backend.app.summary_contracts import (
    OutputValidator,
    SummaryInput,
    SummaryResult,
    SummaryValidationError,
    deterministic_summary,
)
from ml.prediction.contracts import PredictionResult

SUMMARY_TIMEOUT_SECONDS = 5.0


class SummaryService:
    def __init__(self, provider: SummaryProvider | None = None, *, unavailable_reason: str = "provider_disabled") -> None:
        self._provider = provider
        self._unavailable_reason = unavailable_reason
        self._validator = OutputValidator()
        self._slots = BoundedSemaphore(4)

    async def summarize(self, value: SummaryInput | dict[str, object]) -> SummaryResult:
        try:
            if type(value) is SummaryInput:
                # Copy only approved fields; provider never sees the caller's object.
                prediction = SummaryInput(value.expected_sleep_minutes, value.wake_probability_60m, value.baseline_minutes)
            else:
                prediction = SummaryInput.from_mapping(value)
        except (SummaryValidationError, TypeError, ValueError, AttributeError):
            return SummaryResult(deterministic_summary(None), True, "invalid_summary_input")
        fallback = deterministic_summary(prediction)
        if self._provider is None:
            return SummaryResult(fallback, True, self._unavailable_reason)
        if not self._slots.acquire(blocking=False):
            return SummaryResult(fallback, True, "provider_busy")
        provider_model = None
        try:
            provider_model = self._provider.model_version
            async with asyncio.timeout(SUMMARY_TIMEOUT_SECONDS):
                provider_input = SummaryInput.from_mapping(prediction.as_dict())
                output = await self._provider.generate(provider_input)
            text = self._validator.validate(output, prediction)
            return SummaryResult(text, False, None, provider_model=provider_model)
        except SummaryValidationError:
            return SummaryResult(fallback, True, "invalid_summary_output", provider_model=provider_model)
        except TimeoutError:
            return SummaryResult(fallback, True, "provider_timeout", provider_model=provider_model)
        except Exception:
            return SummaryResult(fallback, True, "provider_failed", provider_model=provider_model)
        finally:
            self._slots.release()

    async def summarize_prediction(self, prediction: PredictionResult) -> SummaryResult:
        try:
            if type(prediction) is not PredictionResult:
                raise SummaryValidationError("invalid_summary_input")
            prediction.__post_init__()
            minimal = SummaryInput(
                prediction.expected_sleep_minutes, prediction.wake_probability_60m,
                prediction.baseline_minutes,
            )
        except (TypeError, ValueError, AttributeError):
            return SummaryResult(deterministic_summary(None), True, "invalid_summary_input")
        return await self.summarize(minimal)


def build_summary_service(environ: Mapping[str, str] | None = None) -> SummaryService:
    try:
        settings = GemmaSettings.from_environment(environ)
        if settings.provider == "disabled":
            return SummaryService()
        return SummaryService(GemmaProvider(settings))
    except ConfigurationError:
        # Fail closed for provider use while preserving the safe local summary.
        return SummaryService(unavailable_reason="provider_configuration_invalid")
