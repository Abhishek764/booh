"""Prediction boundary budgets, races, retention, and adversarial model tests."""

import asyncio
import logging
from dataclasses import replace
from datetime import timedelta
from threading import Event as ThreadEvent
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from backend.app.main import create_app
from backend.app.models import Baby, Event, Prediction, Summary
from backend.app.prediction_contracts import PredictionAPIError
from backend.app.summary_contracts import SummaryInput, SummaryResult
from backend.tests.test_auth_service import NOW, settings
from backend.tests.test_prediction_routes import (
    PRIVATE,
    FittedModel,
    approved,
    post,
)
from backend.tests.test_prediction_routes import prediction_client as prediction_client
from ml.prediction.contracts import NumericalPrediction


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 10081, True])
def test_invalid_model_minutes_fall_back_without_persisting_invalid_output(prediction_client, value):
    _, login, _, baby, _, _, _, install, _ = prediction_client
    login()
    baby_id = baby(bouts=42)
    output = NumericalPrediction(47, 0.25)
    object.__setattr__(output, "expected_sleep_minutes", value)
    model = install(baby_id, output=output)
    response = post(prediction_client, baby_id)
    assert response.status_code == 201 and response.json()["used_baseline"] and model.closed
    assert response.json()["expected_sleep_minutes"] == response.json()["baseline_minutes"]


def test_invalid_final_engine_output_is_rejected_before_persistence_or_gemma(prediction_client, monkeypatch):
    _, login, _, baby, engine, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    from ml.prediction.service import PredictionService

    original = PredictionService.predict

    def invalid(instance, *args, **kwargs):
        result = original(instance, *args, **kwargs)
        object.__setattr__(result, "expected_sleep_minutes", -1)
        return result

    monkeypatch.setattr(PredictionService, "predict", invalid)
    response = post(prediction_client, baby_id)
    assert response.status_code == 503 and provider.calls == []
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0


def test_prediction_never_fits_models_or_invokes_offline_training(prediction_client, monkeypatch):
    _, login, _, baby, _, _, _, install, _ = prediction_client
    login()
    baby_id = baby(bouts=42)
    install(baby_id)

    def forbidden(*args, **kwargs):
        pytest.fail("HTTP inference must not fit/download/evaluate models")

    monkeypatch.setattr("ml.prediction.tabpfn._fit_offline", forbidden)
    assert post(prediction_client, baby_id).status_code == 201


def test_history_loading_includes_overlapping_and_duration_only_sleeps_but_excludes_foreign_future_and_old_events(prediction_client):
    _, login, _, baby, engine, service, _, _, principal = prediction_client
    login()
    baby_id = baby(history=False)
    other = baby(history=False)
    with Session(engine) as session:
        session.add_all([
            Event(baby_id=baby_id, event_type="sleep", source="manual", start_time=NOW - timedelta(days=8), end_time=NOW - timedelta(days=6)),
            Event(baby_id=baby_id, event_type="sleep", source="manual", start_time=NOW - timedelta(days=8), duration_seconds=2 * 86400),
            Event(baby_id=baby_id, event_type="feed", source="manual", start_time=NOW - timedelta(days=8)),
            Event(baby_id=baby_id, event_type="wake", source="manual", start_time=NOW + timedelta(minutes=1)),
            Event(baby_id=other, event_type="feed", source="manual", start_time=NOW - timedelta(minutes=1)),
        ])
        session.commit()
    context = service._repository.load_context(owner_id=principal().user_id, baby_id=baby_id, as_of=NOW)
    assert len(context.history) == 2 and all(record.baby_id == baby_id and record.event_type == "sleep" for record in context.history)
    assert context.date_of_birth is None and "history" not in repr(context)


def test_oversized_history_is_rejected_before_numerical_inference(prediction_client, monkeypatch):
    _, login, _, baby, engine, _, provider, *_ = prediction_client
    login()
    baby_id = baby(history=False)
    with Session(engine) as session:
        session.execute(insert(Event), [{"baby_id": baby_id, "event_type": "feed", "source": "manual",
                                        "start_time": NOW - timedelta(minutes=index)} for index in range(10001)])
        session.commit()

    def forbidden(*args, **kwargs):
        pytest.fail("oversized history must not invoke numerical inference")

    monkeypatch.setattr("ml.prediction.service.PredictionService.predict", forbidden)
    response = post(prediction_client, baby_id)
    assert response.status_code == 413 and response.json()["error"]["code"] == "history_too_large"
    assert provider.calls == []


def test_overlapping_history_fails_without_fabricated_prediction(prediction_client):
    _, login, _, baby, engine, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    with Session(engine) as session:
        session.add(Event(baby_id=baby_id, event_type="sleep", source="manual", start_time=NOW - timedelta(days=1), end_time=NOW - timedelta(hours=23)))
        session.commit()
    response = post(prediction_client, baby_id)
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_history" and provider.calls == []


def test_gemma_cannot_leave_outcomes_or_arbitrary_private_metadata_in_storage(prediction_client):
    _, login, _, baby, engine, service, _, *_ = prediction_client
    login()
    baby_id = baby()

    class Summary:
        async def summarize(self, value):
            return SummaryResult(f"About {value.expected_sleep_minutes} minutes of sleep may remain.", False, None,
                                 provider_model=PRIVATE)

    service._summaries = Summary()
    response = post(prediction_client, baby_id)
    assert response.status_code == 201 and response.json()["summary_used_fallback"]
    with Session(engine) as session:
        assert PRIVATE not in str(session.scalar(select(Prediction)).feature_metadata)


def test_authorization_is_rechecked_when_baby_is_deleted_during_gemma(prediction_client):
    client, login, _, baby, engine, service, _, install, principal = prediction_client
    login()
    baby_id = baby(bouts=42)
    model = install(baby_id)
    actor = principal()

    class SummaryService:
        async def summarize(self, value):
            client.app.state.baby_service.delete_baby(actor, baby_id=baby_id)
            return SummaryResult(f"About {value.expected_sleep_minutes} minutes of sleep may remain.", False, None)

    service._summaries = SummaryService()
    response = post(prediction_client, baby_id)
    assert response.status_code == 404 and model.closed
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0
        assert session.scalar(select(func.count()).select_from(Summary)) == 0


def test_stored_invalid_numerical_metadata_fails_with_fixed_private_error(prediction_client, caplog):
    client, login, _, baby, engine, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    assert post(prediction_client, baby_id).status_code == 201
    provider.calls.clear()
    with Session(engine) as session:
        prediction = session.scalar(select(Prediction))
        prediction.feature_metadata = {"baseline_version": PRIVATE, "baseline_sample_count": 3,
                                       "elapsed_sleep_minutes": 0, "fallback_reason": "model_unavailable"}
        session.commit()
    caplog.set_level(logging.DEBUG)
    response = client.get(f"/api/v1/babies/{baby_id}/predictions")
    assert response.status_code == 503 and PRIVATE not in response.text and PRIVATE not in caplog.text and provider.calls == []


def test_slow_stream_body_returns_timeout_without_model_or_provider_calls(prediction_client, monkeypatch):
    client, login, headers, baby, _, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    monkeypatch.setattr("backend.app.routes.predictions.BODY_TIMEOUT_SECONDS", 0.01)

    async def scenario():
        async def chunks():
            yield b"{"
            await asyncio.sleep(1)
            yield b"}"

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="https://testserver", cookies=dict(client.cookies)) as transport:
            return await transport.post(f"/api/v1/babies/{baby_id}/predict", content=chunks(), headers={**headers(), "Content-Type": "application/json"})

    response = asyncio.run(scenario())
    assert response.status_code == 408 and provider.calls == []


def test_foreign_baby_is_rejected_before_receiving_any_body(prediction_client):
    client, login, headers, baby, _, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    login("user-b-code")

    async def scenario():
        async def chunks():
            pytest.fail("foreign baby request must not read its body")
            yield b"{}"

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="https://testserver", cookies=dict(client.cookies)) as transport:
            return await transport.post(f"/api/v1/babies/{baby_id}/predict", content=chunks(), headers=headers())

    assert asyncio.run(scenario()).status_code == 404 and provider.calls == []


def test_query_size_and_invalid_session_are_bounded_private_errors(prediction_client):
    client, login, _, baby, _, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    response = client.get(f"/api/v1/babies/{baby_id}/predictions?x=" + "x" * 8193)
    assert response.status_code == 400 and response.headers["Cache-Control"] == "no-store"
    client.cookies.clear()
    client.cookies.set(client.app.state.auth_service.cookie_names.session, "synthetic-invalid-cookie")
    assert client.get(f"/api/v1/babies/{baby_id}/predictions").status_code == 401 and provider.calls == []


def test_request_cancellation_before_model_finishes_prevents_prediction_writes(prediction_client):
    _, login, _, baby, engine, service, provider, install, principal = prediction_client
    login()
    baby_id = baby(bouts=42)
    model = install(baby_id)
    entered = ThreadEvent()
    release = ThreadEvent()

    def blocked(inputs):
        entered.set()
        assert release.wait(timeout=2)
        return NumericalPrediction(47, 0.25)

    model.predict = blocked
    actor = principal()

    async def scenario():
        task = asyncio.create_task(service.predict(actor, baby_id=baby_id))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()

    asyncio.run(scenario())  # Waits for the actual worker to release its own slot.
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0
    assert provider.calls == []
    model.predict = lambda inputs: NumericalPrediction(47, 0.25)
    assert post(prediction_client, baby_id).status_code == 201


def test_timeout_returns_safe_error_and_keeps_committed_fallback(prediction_client, monkeypatch):
    client, login, _, baby, _, service, _, *_ = prediction_client
    login()
    baby_id = baby()
    monkeypatch.setattr("backend.app.services.predictions.PIPELINE_TIMEOUT_SECONDS", 0.1)

    class Slow:
        async def summarize(self, value):
            await asyncio.Event().wait()

    service._summaries = Slow()
    response = post(prediction_client, baby_id)
    assert response.status_code == 503 and response.json()["error"]["code"] == "prediction_timeout"
    listed = client.get(f"/api/v1/babies/{baby_id}/predictions")
    assert listed.status_code == 200 and listed.json()[0]["summary_used_fallback"]


def test_busy_service_and_transport_workers_do_not_start_more_work(prediction_client, monkeypatch):
    _, login, _, baby, _, service, provider, *_ = prediction_client
    login()
    baby_id = baby()
    for _ in range(4):
        assert service._slots.acquire(blocking=False)
    try:
        response = post(prediction_client, baby_id)
        assert response.status_code == 429
    finally:
        for _ in range(4):
            service._slots.release()
    from backend.app.services import predictions

    for _ in range(4):
        assert predictions._WORK_SLOTS.acquire(blocking=False)
    try:
        assert post(prediction_client, baby_id).status_code == 429
    finally:
        for _ in range(4):
            predictions._WORK_SLOTS.release()
    assert provider.calls == []


def test_registry_owner_clear_and_app_shutdown_close_owned_models(prediction_client):
    client, login, _, baby, _, service, _, install, principal = prediction_client
    login()
    first = install(baby(bouts=42))
    service._models.clear_owner(principal().user_id)
    assert first.closed
    second = install(baby(bouts=42))
    client.app.state.prediction_models.close()
    assert second.closed


@pytest.mark.parametrize("invalid", ["future", "stale", "foreign", "worse"])
def test_offline_registry_rejects_invalid_evidence_scope_or_staleness(prediction_client, invalid):
    _, login, _, baby, _, service, _, _, principal = prediction_client
    login()
    baby_id = baby(bouts=42)
    model = FittedModel(baby_id)
    candidate = approved(model)
    if invalid == "future":
        object.__setattr__(candidate.evidence, "validation_end", NOW + timedelta(minutes=1))
    elif invalid == "stale":
        model.provenance = replace(model.provenance, trained_until=NOW - timedelta(days=8))
        candidate = approved(model)
    elif invalid == "foreign":
        model.provenance = replace(model.provenance, baby_id=uuid4())
        candidate = approved(model)
    else:
        object.__setattr__(candidate.evidence, "mae_minutes", 999)
    with pytest.raises(PredictionAPIError):
        service.install_evaluated_model(principal(), baby_id=baby_id, candidate=candidate,
                                       history_revision=service.training_context(principal(), baby_id=baby_id).revision)
    assert model.closed


def test_registry_budget_and_replaced_expiry_do_not_close_new_model(prediction_client, monkeypatch):
    _, login, _, baby, _, service, _, install, _ = prediction_client
    login()
    callbacks = []

    class Timer:
        def __init__(self, ttl, callback):
            callbacks.append(callback)

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr("backend.app.services.prediction_models.Timer", Timer)
    baby_id = baby(bouts=42)
    first = install(baby_id)
    second = install(baby_id)
    assert first.closed and not second.closed
    callbacks[0]()  # A cancelled timer that had already fired must not evict its replacement.
    assert not second.closed
    callbacks[1]()
    assert second.closed
    install(baby(bouts=42))
    install(baby(bouts=42))
    with pytest.raises(PredictionAPIError):
        install(baby(bouts=42))


def test_sensitive_profile_history_and_exceptions_are_absent_from_response_logs_and_reprs(prediction_client, caplog, capsys):
    _, login, _, baby, engine, service, provider, *_ = prediction_client
    login()
    baby_id = baby()
    with Session(engine) as session:
        session.scalar(select(Baby).where(Baby.id == baby_id)).display_name = PRIVATE
        session.commit()
    provider.fail = True
    caplog.set_level(logging.DEBUG)
    response = post(prediction_client, baby_id)
    assert response.status_code == 201 and PRIVATE not in response.text and PRIVATE not in caplog.text
    assert "feature_metadata" not in response.text and "baseline_sample_count" not in response.text and "user_id" not in response.text
    captured = capsys.readouterr()
    assert PRIVATE not in captured.out and PRIVATE not in captured.err


def test_production_auth_environment_cannot_be_downgraded_for_gemma_by_ambient_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GEMMA_PROVIDER", "openai")
    monkeypatch.setenv("GEMMA_BASE_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("GEMMA_MODEL", "gemma-synthetic-test")
    monkeypatch.delenv("GEMMA_API_KEY", raising=False)
    application = create_app(replace(settings(), app_env="production"))
    result = asyncio.run(application.state.summary_service.summarize(SummaryInput(47, 0.25, 53)))
    assert result.used_fallback and result.reason == "provider_configuration_invalid"


def test_candidate_fitted_before_history_change_cannot_be_installed(prediction_client):
    client, login, headers, baby, _, service, _, _, principal = prediction_client
    login()
    baby_id = baby(bouts=42)
    revision = service.training_context(principal(), baby_id=baby_id).revision
    candidate = approved(FittedModel(baby_id))
    response = client.post(f"/api/v1/babies/{baby_id}/events", json={"event_type": "feed", "start_time": NOW.isoformat()}, headers=headers())
    assert response.status_code == 201
    with pytest.raises(PredictionAPIError) as failure:
        service.install_evaluated_model(principal(), baby_id=baby_id, candidate=candidate, history_revision=revision)
    assert failure.value.status_code == 409 and candidate.model.closed
