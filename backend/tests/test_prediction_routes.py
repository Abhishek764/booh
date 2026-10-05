"""Synthetic authenticated cross-layer prediction/persistence/privacy tests."""

import json
import logging
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from backend.app.database import create_database_engine, create_session_factory
from backend.app.main import create_app
from backend.app.models import Base, Event, Prediction, Summary, User
from backend.app.prediction_contracts import PredictionAPIError
from backend.app.repositories.auth import InMemoryAuthRepository
from backend.app.repositories.babies import SqlAlchemyBabyRepository
from backend.app.repositories.events import SqlAlchemyEventRepository
from backend.app.repositories.imports import SqlAlchemyImportRepository
from backend.app.repositories.predictions import SqlAlchemyPredictionRepository
from backend.app.services.auth import AuthService
from backend.app.services.babies import BabyService
from backend.app.services.events import EventService
from backend.app.services.imports import ImportService
from backend.app.services.predictions import PredictionPipelineService
from backend.app.services.summaries import SummaryService
from backend.app.summary_contracts import SummaryResult
from backend.tests.test_auth_service import NOW, settings
from backend.tests.test_baby_routes import MultiUserProvider
from ml.prediction.contracts import (
    BASELINE_VERSION,
    TABPFN_VERSION,
    ApprovedModel,
    EvaluationEvidence,
    ModelProvenance,
    NumericalPrediction,
)

PRIVATE = "synthetic-private-prediction-sentinel"
PROBABILITY = 0.12345678912345678


class SummaryProvider:
    model_version = "gemma-synthetic-test"

    def __init__(self, *, fail=False, malicious=False, engine=None):
        self.fail = fail
        self.malicious = malicious
        self.engine = engine
        self.calls = []

    async def generate(self, prediction):
        self.calls.append(prediction.as_dict())
        if self.engine is not None:
            with Session(self.engine) as session:
                assert session.scalar(select(func.count()).select_from(Prediction)) > 0
                assert session.scalar(select(func.count()).select_from(Summary)) > 0
        if self.fail:
            raise RuntimeError(PRIVATE)
        if self.malicious:
            return json.dumps({"sentences": ["About 999 minutes of sleep may remain."], "baseline_minutes": 999})
        return json.dumps({"sentences": [f"About {prediction.expected_sleep_minutes} minutes of sleep may remain.", "Timing can vary."]})


class FittedModel:
    def __init__(self, baby_id, *, output=None, fail=False):
        self.provenance = ModelProvenance(baby_id, NOW - timedelta(days=2), 31)
        self.output = output or NumericalPrediction(47, PROBABILITY)
        self.fail = fail
        self.calls = []
        self.closed = False

    def predict(self, inputs):
        self.calls.append(inputs)
        if self.fail:
            raise RuntimeError(PRIVATE)
        return self.output

    def close(self):
        self.closed = True


def approved(model):
    return ApprovedModel(model, model.provenance, EvaluationEvidence(
        NOW - timedelta(days=1), NOW - timedelta(hours=1), 5, 10, 1, 0.1, 2, 0.2,
    ))


@pytest.fixture
def prediction_client(tmp_path):
    auth_repo = InMemoryAuthRepository()
    users = [auth_repo.get_or_create_identity_user(issuer="https://accounts.google.com", subject=f"subject-{suffix}",
             email=f"{suffix}@example.test", now=NOW) for suffix in ("a", "b")]
    engine = create_database_engine(f"sqlite:///{tmp_path / 'predictions.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with Session(engine) as session:
        session.add_all([User(id=user.id, email=user.email) for user in users])
        session.commit()
    app = create_app(settings())
    models = app.state.prediction_models
    auth = AuthService(settings(), MultiUserProvider(), auth_repo, clock=lambda: NOW)
    provider = SummaryProvider(engine=engine)
    repo = SqlAlchemyPredictionRepository(factory)
    service = PredictionPipelineService(repo, summaries=SummaryService(provider), models=models, clock=lambda: NOW)
    app.state.auth_service = auth
    app.state.baby_service = BabyService(SqlAlchemyBabyRepository(factory), on_change=models.invalidate)
    app.state.event_service = EventService(SqlAlchemyEventRepository(factory), clock=lambda: NOW, on_change=models.invalidate)
    app.state.import_service = ImportService(SqlAlchemyImportRepository(factory), limits=app.state.import_limits,
                                             clock=lambda: NOW, on_change=models.invalidate)
    app.state.prediction_service = service

    with TestClient(app, base_url="https://testserver") as client:
        def login(code="user-a-code"):
            start = auth.start_login()
            state = start.authorization_url.split("state=", 1)[1].split("&", 1)[0]
            result = auth.complete_login(code=code, state=state, oauth_flow_cookie=start.oauth_flow_cookie)
            client.cookies.set(auth.cookie_names.session, result.session_cookie)
            client.cookies.set(auth.cookie_names.csrf, result.csrf_cookie)

        def headers():
            return {"Origin": settings().frontend_origin, "X-CSRF-Token": client.cookies.get(auth.cookie_names.csrf)}

        def baby(*, history=True, durations=(45, 75, 90), bouts=3):
            response = client.post("/api/v1/babies", json={"display_name": "Synthetic baby", "timezone": "UTC"}, headers=headers())
            assert response.status_code == 201
            baby_id = UUID(response.json()["id"])
            if history:
                with Session(engine) as session:
                    for index in range(bouts):
                        start = NOW - timedelta(hours=(bouts - index) * (4 if bouts > 10 else 24))
                        end = start + timedelta(minutes=durations[index % len(durations)])
                        session.add_all([
                            Event(baby_id=baby_id, event_type="feed", source="manual", start_time=start - timedelta(minutes=10)),
                            Event(baby_id=baby_id, event_type="sleep", source="manual", start_time=start, end_time=end),
                            Event(baby_id=baby_id, event_type="wake", source="manual", start_time=end),
                        ])
                    session.commit()
            return baby_id

        def principal():
            return auth.authenticate(client.cookies.get(auth.cookie_names.session))

        def install(baby_id, **kwargs):
            revision = service.training_context(principal(), baby_id=baby_id).revision
            model = FittedModel(baby_id, **kwargs)
            service.install_evaluated_model(principal(), baby_id=baby_id, candidate=approved(model), history_revision=revision)
            return model

        yield client, login, headers, baby, engine, service, provider, install, principal
    engine.dispose()


def post(fixture, baby_id, **kwargs):
    client, _, headers, *_ = fixture
    return client.post(f"/api/v1/babies/{baby_id}/predict", headers=headers(), **kwargs)


def test_unauthorized_requests_stop_before_repository_model_or_summary(prediction_client, monkeypatch):
    client, _, _, _, _, service, provider, *_ = prediction_client

    def forbidden(*args, **kwargs):
        pytest.fail("unauthorized request must not touch prediction data")

    monkeypatch.setattr(service._repository, "owns_baby", forbidden)
    monkeypatch.setattr(service._repository, "list_owned", forbidden)
    for method, suffix in [("post", "predict"), ("get", "predictions")]:
        for identifier in (str(uuid4()), "not-a-uuid"):
            response = getattr(client, method)(f"/api/v1/babies/{identifier}/{suffix}")
            assert response.status_code == 401 and response.json()["error"]["code"] == "authentication_required"
            assert response.headers["Cache-Control"] == "no-store"
    assert provider.calls == []


def test_cross_user_and_missing_babies_have_identical_errors_and_no_history_load(prediction_client, monkeypatch):
    client, login, _, baby, _, service, provider, *_ = prediction_client
    login()
    baby_id = baby()
    assert post(prediction_client, baby_id).status_code == 201
    provider.calls.clear()
    login("user-b-code")

    def forbidden(*args, **kwargs):
        pytest.fail("foreign baby must not load history")

    monkeypatch.setattr(service._repository, "load_context", forbidden)
    for suffix, method in [("predict", "post"), ("predictions", "get")]:
        responses = [post(prediction_client, identifier) if method == "post" else client.get(f"/api/v1/babies/{identifier}/{suffix}")
                     for identifier in (baby_id, uuid4())]
        assert [r.status_code for r in responses] == [404, 404]
        assert responses[0].json() == responses[1].json()
    assert provider.calls == []


@pytest.mark.parametrize("bouts", [0, 1, 2])
def test_insufficient_history_never_persists_or_calls_gemma(prediction_client, bouts):
    _, login, _, baby, engine, _, provider, *_ = prediction_client
    login()
    baby_id = baby(history=bouts > 0, bouts=bouts)
    response = post(prediction_client, baby_id)
    assert response.status_code == 422 and response.json()["error"]["code"] == "insufficient_history"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0
        assert session.scalar(select(func.count()).select_from(Summary)) == 0
    assert provider.calls == []


def test_baseline_fallback_is_explicit_persisted_exactly_and_listed_with_summary(prediction_client):
    client, login, _, baby, engine, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    response = post(prediction_client, baby_id)
    assert response.status_code == 201
    data = response.json()
    assert (data["expected_sleep_minutes"], data["baseline_minutes"], data["wake_probability_60m"]) == (70, 70, 1 / 3)
    assert data["model_version"] == BASELINE_VERSION and data["used_baseline"]
    assert not data["summary_used_fallback"] and "70 minutes" in data["summary"]
    assert set(provider.calls[0]) == {"expected_sleep_minutes", "wake_probability_60m", "baseline_minutes"}
    listed = client.get(f"/api/v1/babies/{baby_id}/predictions")
    assert listed.status_code == 200 and listed.json() == [data]
    assert listed.headers["Cache-Control"] == "no-store"
    assert listed.headers["Referrer-Policy"] == "no-referrer"
    with Session(engine) as session:
        stored = session.scalar(select(Prediction))
        assert stored.wake_probability_within_60m == 1 / 3
        assert stored.feature_metadata["fallback_reason"] == "model_unavailable"
        assert "history" not in stored.feature_metadata


def test_approved_model_prediction_keeps_full_float_probability_through_gemma_and_get(prediction_client):
    client, login, _, baby, engine, _, provider, install, _ = prediction_client
    login()
    baby_id = baby(bouts=42)
    model = install(baby_id)
    response = post(prediction_client, baby_id)
    assert response.status_code == 201
    data = response.json()
    assert data["expected_sleep_minutes"] == 47 and data["wake_probability_60m"] == PROBABILITY
    assert data["model_version"] == TABPFN_VERSION and not data["used_baseline"]
    assert len(model.calls) == 1 and model.calls[0].baby_id == baby_id
    assert provider.calls[0]["wake_probability_60m"] == PROBABILITY
    assert client.get(f"/api/v1/babies/{baby_id}/predictions").json() == [data]
    with Session(engine) as session:
        assert session.scalar(select(Prediction)).wake_probability_within_60m == PROBABILITY


def test_model_failure_uses_baseline_and_closes_failed_artifact(prediction_client, caplog):
    _, login, _, baby, engine, _, _, install, _ = prediction_client
    caplog.set_level(logging.DEBUG)
    login()
    baby_id = baby(bouts=42)
    model = install(baby_id, fail=True)
    response = post(prediction_client, baby_id)
    assert response.status_code == 201
    assert response.json()["used_baseline"] and model.closed
    assert response.json()["expected_sleep_minutes"] == response.json()["baseline_minutes"]
    assert PRIVATE not in response.text and PRIVATE not in caplog.text
    with Session(engine) as session:
        assert session.scalar(select(Prediction)).feature_metadata["fallback_reason"] == "model_unavailable"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1.5, True, "synthetic"])
def test_invalid_model_probability_uses_validated_baseline(prediction_client, value):
    _, login, _, baby, engine, _, _, install, _ = prediction_client
    login()
    baby_id = baby(bouts=42)
    output = NumericalPrediction(47, 0.25)
    object.__setattr__(output, "wake_probability_60m", value)
    model = install(baby_id, output=output)
    response = post(prediction_client, baby_id)
    assert response.status_code == 201 and response.json()["used_baseline"] and model.closed
    assert 0 <= response.json()["wake_probability_60m"] <= 1
    with Session(engine) as session:
        assert session.scalar(select(Prediction)).feature_metadata["fallback_reason"] == "invalid_model_output"


@pytest.mark.parametrize("mode", ["failure", "malicious", "disabled"])
def test_gemma_failure_never_changes_the_persisted_model_numbers(prediction_client, mode):
    client, login, _, baby, _, service, provider, install, _ = prediction_client
    login()
    baby_id = baby(bouts=42)
    install(baby_id)
    if mode == "disabled":
        service._summaries = SummaryService()
    else:
        provider.fail = mode == "failure"
        provider.malicious = mode == "malicious"
    response = post(prediction_client, baby_id)
    assert response.status_code == 201
    data = response.json()
    assert data["expected_sleep_minutes"] == 47 and data["wake_probability_60m"] == PROBABILITY
    assert not data["used_baseline"] and data["summary_used_fallback"]
    assert "47 minutes" in data["summary"] and "Timing can vary." in data["summary"]
    assert "999" not in data["summary"]
    assert client.get(f"/api/v1/babies/{baby_id}/predictions").json() == [data]


def test_summary_input_mutation_and_forged_return_values_are_rejected(prediction_client):
    client, login, _, baby, _, service, _, install, _ = prediction_client
    login()
    baby_id = baby(bouts=42)
    install(baby_id)

    class MaliciousSummary:
        async def summarize(self, value):
            object.__setattr__(value, "expected_sleep_minutes", 999)
            object.__setattr__(value, "wake_probability_60m", 1)
            object.__setattr__(value, "baseline_minutes", 999)
            return SummaryResult("About 999 minutes of sleep may remain.", False, None)

    service._summaries = MaliciousSummary()
    response = post(prediction_client, baby_id)
    data = response.json()
    assert response.status_code == 201 and data["summary_used_fallback"]
    assert data["expected_sleep_minutes"] == 47 and data["wake_probability_60m"] == PROBABILITY
    assert data["baseline_minutes"] != 999 and "47 minutes" in data["summary"]
    assert client.get(f"/api/v1/babies/{baby_id}/predictions").json() == [data]


@pytest.mark.parametrize("phase", ["insert", "commit", "summary_update"])
def test_persistence_failures_are_private_and_do_not_claim_success(prediction_client, monkeypatch, caplog, phase):
    client, login, _, baby, engine, service, provider, *_ = prediction_client
    login()
    baby_id = baby()
    caplog.set_level(logging.DEBUG)
    if phase == "summary_update":
        monkeypatch.setattr(service._repository, "finish_summary", lambda **kwargs: (_ for _ in ()).throw(RuntimeError(PRIVATE)))
    elif phase == "commit":
        def fail_commit(session):
            if any(isinstance(item, Prediction) for item in session.identity_map.values()):
                raise RuntimeError(PRIVATE)
        event.listen(Session, "before_commit", fail_commit)
    else:
        def fail_insert(mapper, connection, target):
            raise RuntimeError(PRIVATE)
        event.listen(Prediction, "before_insert", fail_insert)
    try:
        response = post(prediction_client, baby_id)
    finally:
        if phase == "commit":
            event.remove(Session, "before_commit", fail_commit)
        elif phase == "insert":
            event.remove(Prediction, "before_insert", fail_insert)
    assert response.status_code == 503 and response.json()["error"]["code"] == "service_unavailable"
    assert PRIVATE not in response.text and PRIVATE not in caplog.text
    with Session(engine) as session:
        expected = int(phase == "summary_update")
        assert session.scalar(select(func.count()).select_from(Prediction)) == expected
        assert session.scalar(select(func.count()).select_from(Summary)) == expected
    if phase != "summary_update":
        assert provider.calls == []
    else:
        stored = client.get(f"/api/v1/babies/{baby_id}/predictions").json()
        assert len(stored) == 1 and stored[0]["summary_used_fallback"]


def test_post_requires_session_bound_csrf_and_exact_origin(prediction_client):
    client, login, headers, baby, _, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    for overrides in [{}, {"Origin": settings().frontend_origin}, {**headers(), "Origin": "https://attacker.example.test"},
                      {**headers(), "X-CSRF-Token": "synthetic-wrong"}]:
        response = client.post(f"/api/v1/babies/{baby_id}/predict", headers=overrides)
        assert response.status_code == 403
    assert provider.calls == []


@pytest.mark.parametrize("payload", [{"user_id": "synthetic"}, {"baby_id": str(uuid4())}, {"as_of": NOW.isoformat()},
                                    {"expected_sleep_minutes": 999}, {"baseline_minutes": 999}, {"wake_probability_60m": 1},
                                    {"model": "other"}, {"base_url": "http://169.254.169.254"}, {"notes": PRIVATE}])
def test_prediction_body_cannot_assign_scope_numbers_models_or_prompt_content(prediction_client, payload):
    _, login, _, baby, _, _, provider, *_ = prediction_client
    login()
    response = post(prediction_client, baby(), json=payload)
    assert response.status_code == 422 and PRIVATE not in response.text and provider.calls == []


@pytest.mark.parametrize("body,mime,length,status", [
    (b"x" * 1025, "application/json", "1", 413), (b"{}", "application/json", "1025", 413),
    (b"{}", "application/json", "-1", 400), (b"{}", "text/html", None, 415),
    (b"\xff", "application/json", None, 422), (b'{"x":1,"x":2}', "application/json", None, 422),
    (b"null", "application/json", None, 422), (b"[]", "application/json", None, 422),
])
def test_streamed_input_is_bounded_and_strict_even_with_false_content_length(prediction_client, body, mime, length, status):
    client, login, headers, baby, _, _, provider, *_ = prediction_client
    login()
    extra = {"Content-Type": mime, **headers()}
    if length is not None:
        extra["Content-Length"] = length
    response = client.post(f"/api/v1/babies/{baby()}/predict", content=body, headers=extra)
    assert response.status_code == status and provider.calls == []


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "offset=10001", "sort=private", "owner_id=synthetic", "limit=NaN"])
def test_list_pagination_and_query_fields_are_bounded_and_allowlisted(prediction_client, query):
    client, login, _, baby, *_ = prediction_client
    login()
    response = client.get(f"/api/v1/babies/{baby()}/predictions?{query}")
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request"


def test_empty_owned_history_and_bounded_stable_prediction_pagination(prediction_client):
    client, login, _, baby, _, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    assert client.get(f"/api/v1/babies/{baby_id}/predictions").json() == []
    records = [post(prediction_client, baby_id).json() for _ in range(3)]
    expected = sorted(records, key=lambda record: record["id"], reverse=True)
    assert client.get(f"/api/v1/babies/{baby_id}/predictions?limit=1&offset=1").json() == expected[1:2]
    assert len(provider.calls) == 3
    other = baby()
    assert client.get(f"/api/v1/babies/{other}/predictions").json() == []


def test_active_sleep_uses_elapsed_time_and_later_wake_resets_to_bout_start(prediction_client):
    _, login, headers, baby, engine, _, _, *_ = prediction_client
    login()
    baby_id = baby(durations=(60, 90, 120))
    with Session(engine) as session:
        session.add(Event(baby_id=baby_id, event_type="sleep", source="manual", start_time=NOW - timedelta(minutes=30)))
        session.commit()
    data = post(prediction_client, baby_id).json()
    assert (data["expected_sleep_minutes"], data["wake_probability_60m"]) == (60, 2 / 3)
    with Session(engine) as session:
        session.add(Event(baby_id=baby_id, event_type="wake", source="manual", start_time=NOW - timedelta(minutes=5)))
        session.commit()
    data = post(prediction_client, baby_id).json()
    assert (data["expected_sleep_minutes"], data["wake_probability_60m"]) == (90, 1 / 3)


def test_history_change_between_inference_and_persist_returns_conflict(prediction_client, monkeypatch):
    _, login, _, baby, engine, service, provider, *_ = prediction_client
    login()
    baby_id = baby()
    original = service._repository.create_owned

    def changed(**kwargs):
        with Session(engine) as session:
            session.add(Event(baby_id=baby_id, event_type="feed", source="manual", start_time=NOW - timedelta(minutes=5)))
            session.commit()
        return original(**kwargs)

    monkeypatch.setattr(service._repository, "create_owned", changed)
    response = post(prediction_client, baby_id)
    assert response.status_code == 409 and response.json()["error"]["code"] == "history_changed"
    assert provider.calls == []


def test_stored_summary_is_revalidated_and_list_never_calls_gemma(prediction_client):
    client, login, _, baby, engine, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    assert post(prediction_client, baby_id).status_code == 201
    provider.calls.clear()
    with Session(engine) as session:
        stored = session.scalar(select(Summary))
        stored.summary_text = "<script>" + PRIVATE + "</script>"
        session.commit()
    response = client.get(f"/api/v1/babies/{baby_id}/predictions")
    assert response.status_code == 200 and PRIVATE not in response.text
    assert response.json()[0]["summary_used_fallback"] and provider.calls == []


def test_baby_deletion_cascades_outputs_and_closes_owned_worker(prediction_client):
    client, login, headers, baby, engine, _, _, install, _ = prediction_client
    login()
    baby_id = baby(bouts=42)
    model = install(baby_id)
    assert post(prediction_client, baby_id).status_code == 201
    response = client.delete(f"/api/v1/babies/{baby_id}", headers=headers())
    assert response.status_code == 204 and model.closed
    assert client.get(f"/api/v1/babies/{baby_id}/predictions").status_code == 404
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0
        assert session.scalar(select(func.count()).select_from(Summary)) == 0


@pytest.mark.parametrize("change", ["event_create", "event_update", "event_delete", "profile_update", "import"])
def test_history_profile_mutations_invalidate_the_evaluated_artifact(prediction_client, change):
    client, login, headers, baby, engine, _, _, install, _ = prediction_client
    login()
    baby_id = baby(bouts=42)
    model = install(baby_id)
    if change == "event_create":
        response = client.post(f"/api/v1/babies/{baby_id}/events", json={"event_type": "feed", "start_time": NOW.isoformat()}, headers=headers())
    elif change in {"event_update", "event_delete"}:
        with Session(engine) as session:
            record = session.scalar(select(Event).where(Event.baby_id == baby_id, Event.event_type == "feed"))
            event_id = record.id
        response = client.patch(f"/api/v1/events/{event_id}", json={"feed_amount_ml": "10.00"}, headers=headers()) if change == "event_update" else client.delete(f"/api/v1/events/{event_id}", headers=headers())
    elif change == "profile_update":
        response = client.patch(f"/api/v1/babies/{baby_id}", json={"timezone": "America/New_York"}, headers=headers())
    else:
        response = client.post(f"/api/v1/babies/{baby_id}/imports", content=f"event_type,start_time\nfeed,{NOW.isoformat()}\n".encode(), headers={**headers(), "Content-Type": "text/csv"})
    assert response.status_code in {200, 201, 204} and model.closed
    assert post(prediction_client, baby_id).json()["used_baseline"]


def test_offline_installation_checks_ownership_and_replacement_closes_previous_model(prediction_client):
    _, login, _, baby, _, service, _, install, principal = prediction_client
    login()
    baby_id = baby(bouts=42)
    first = install(baby_id)
    second = install(baby_id)
    assert first.closed and not second.closed
    login("user-b-code")
    foreign = FittedModel(baby_id)
    with pytest.raises(PredictionAPIError) as failure:
        service.install_evaluated_model(principal(), baby_id=baby_id, candidate=approved(foreign), history_revision="0" * 64)
    assert failure.value.status_code == 404 and not second.closed
    assert post(prediction_client, baby_id).status_code == 404 and foreign.calls == [] and foreign.closed


def test_per_owner_rate_limit_prevents_additional_inference_or_summary_calls(prediction_client):
    _, login, _, baby, _, _, provider, *_ = prediction_client
    login()
    baby_id = baby()
    for _ in range(10):
        assert post(prediction_client, baby_id).status_code == 201
    response = post(prediction_client, baby_id)
    assert response.status_code == 429 and response.json()["error"]["code"] == "prediction_rate_limited"
    assert len(provider.calls) == 10
