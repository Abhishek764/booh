"""Minimal numerical summary input and bounded, privacy-safe JSON contracts."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

MAX_SUMMARY_CHARS = 300
MAX_SENTENCE_CHARS = 120
MAX_OUTPUT_JSON_CHARS = 1024
MAX_PREDICTION_MINUTES = 10080
SUMMARY_VERSION = "sleep-summary-v1"


class SummaryValidationError(ValueError):
    """Errors contain fixed codes only, never the rejected text or input."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True, repr=False)
class SummaryInput:
    expected_sleep_minutes: int
    wake_probability_60m: float
    baseline_minutes: int

    def __post_init__(self) -> None:
        for value in (self.expected_sleep_minutes, self.baseline_minutes):
            if type(value) is not int or not 0 <= value <= MAX_PREDICTION_MINUTES:
                raise SummaryValidationError("invalid_summary_input")
        probability = self.wake_probability_60m
        if type(probability) not in {int, float} or not 0 <= probability <= 1 or not math.isfinite(probability):
            raise SummaryValidationError("invalid_summary_input")

    @classmethod
    def from_mapping(cls, value: object) -> SummaryInput:
        required = {"expected_sleep_minutes", "wake_probability_60m", "baseline_minutes"}
        if not isinstance(value, dict) or type(value) is not dict or len(value) != 3 or set(value) != required:
            raise SummaryValidationError("invalid_summary_input")
        # Revalidate scalar types before constructing the immutable input.
        expected = value["expected_sleep_minutes"]
        probability = value["wake_probability_60m"]
        baseline = value["baseline_minutes"]
        if type(expected) is not int or type(baseline) is not int or not isinstance(probability, (int, float)) or type(probability) not in {int, float}:
            raise SummaryValidationError("invalid_summary_input")
        if not 0 <= probability <= 1 or not math.isfinite(probability):
            raise SummaryValidationError("invalid_summary_input")
        return cls(expected, float(probability), baseline)

    def as_dict(self) -> dict[str, int | float]:
        self.__post_init__()
        return {
            "expected_sleep_minutes": self.expected_sleep_minutes,
            "wake_probability_60m": float(self.wake_probability_60m),
            "baseline_minutes": self.baseline_minutes,
        }


def probability_percent(prediction: SummaryInput) -> str:
    """Exact decimal rendering of the supplied scalar, without rounding guesses."""

    if prediction.wake_probability_60m == 0:
        return "0"
    with localcontext(Context(prec=32)):
        value = format(Decimal(str(prediction.wake_probability_60m)).scaleb(2), "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def sentence_choices(prediction: SummaryInput) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Closed, grounded language: expected estimate, optional comparison, uncertainty."""

    expected = prediction.expected_sleep_minutes
    baseline = prediction.baseline_minutes
    first = (
        f"About {expected} minutes of sleep may remain.",
        f"Estimated sleep remaining is about {expected} minutes.",
        f"Sleep may last about {expected} more minutes.",
    )
    detail = (
        f"The baseline estimate is about {baseline} minutes.",
        f"The seven-day baseline estimate is {baseline} minutes.",
        f"Estimated chance of waking within 60 minutes is {probability_percent(prediction)}%.",
    )
    uncertainty = ("Timing can vary.", "This is an estimate, not a guarantee.", "Actual timing may vary.")
    return first, tuple(sentence for sentence in detail if len(sentence) <= MAX_SENTENCE_CHARS), uncertainty


def deterministic_summary(prediction: SummaryInput | None) -> str:
    if prediction is None:
        return "A reliable sleep estimate is unavailable. Timing can vary."
    first, detail, uncertainty = sentence_choices(prediction)
    probability = next((sentence for sentence in detail if sentence.startswith("Estimated chance")), None)
    return " ".join((first[0], probability or detail[0], uncertainty[0]))


def strict_json_object(text: str) -> dict[str, object]:
    """Reject duplicate keys/nonfinite constants, without reflecting parser errors."""

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise SummaryValidationError("invalid_summary_output")
            result[key] = value
        return result

    def invalid_constant(value: str) -> object:
        raise SummaryValidationError("invalid_summary_output")

    try:
        decoded = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, TypeError, RecursionError):
        raise SummaryValidationError("invalid_summary_output") from None
    if not isinstance(decoded, dict):
        raise SummaryValidationError("invalid_summary_output")
    return decoded


class OutputValidator:
    """Only accept reviewed grounded sentences; new facts/advice cannot pass."""

    def validate(self, output: object, prediction: SummaryInput) -> str:
        prediction.__post_init__()
        if (
            type(output) is not str or len(output) > MAX_OUTPUT_JSON_CHARS
            or not output.strip()
            or not output.isascii()
        ):
            raise SummaryValidationError("invalid_summary_output")
        decoded = strict_json_object(output)
        if set(decoded) != {"sentences"}:
            raise SummaryValidationError("invalid_summary_output")
        sentences = decoded["sentences"]
        if (
            type(sentences) is not list or not 1 <= len(sentences) <= 3
            or any(type(sentence) is not str or not 1 <= len(sentence) <= MAX_SENTENCE_CHARS for sentence in sentences)
        ):
            raise SummaryValidationError("invalid_summary_output")
        first, detail, uncertainty = sentence_choices(prediction)
        if sentences[0] not in first:
            raise SummaryValidationError("ungrounded_summary_output")
        if len(sentences) == 2 and sentences[1] not in detail + uncertainty:
            raise SummaryValidationError("ungrounded_summary_output")
        if len(sentences) == 3 and (sentences[1] not in detail or sentences[2] not in uncertainty):
            raise SummaryValidationError("ungrounded_summary_output")
        text = " ".join(sentences)
        if len(text) > MAX_SUMMARY_CHARS:
            raise SummaryValidationError("invalid_summary_output")
        return text


@dataclass(frozen=True, slots=True, repr=False)
class SummaryResult:
    text: str
    used_fallback: bool
    reason: str | None
    summary_version: str = SUMMARY_VERSION
    provider_model: str | None = None
