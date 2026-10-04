from __future__ import annotations

from uuid import UUID

from backend.tests.test_baby_routes import configured_client


def _create_baby(client, headers) -> UUID:
    response = client.post(
        "/api/v1/babies",
        json={"display_name": "Synthetic event profile", "timezone": "UTC"},
        headers=headers(),
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


def _event_headers(headers) -> dict[str, str]:
    return headers()


def test_event_crud_and_cross_user_access_are_owner_scoped(configured_client) -> None:
    client, login, headers, _, _ = configured_client
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    created = client.post(
        f"/api/v1/babies/{baby_id}/events",
        json={
            "event_type": "sleep",
            "start_time": "2025-12-31T15:00:00-08:00",
            "end_time": "2025-12-31T16:00:00-08:00",
            "duration_seconds": 3600,
            "timezone": "America/Los_Angeles",
        },
        headers=_event_headers(headers),
    )
    assert created.status_code == 201
    event = created.json()
    event_id = UUID(event["id"])
    assert event["baby_id"] == str(baby_id)
    assert event["event_type"] == "sleep"
    assert event["source"] == "manual"
    assert event["start_time"] == "2025-12-31T23:00:00Z"
    assert "user_id" not in event

    listed = client.get(f"/api/v1/babies/{baby_id}/events")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [str(event_id)]

    patched = client.patch(
        f"/api/v1/events/{event_id}",
        json={
            "end_time": "2025-12-31T15:30:00-08:00",
            "duration_seconds": 1800,
            "timezone": "America/Los_Angeles",
        },
        headers=_event_headers(headers),
    )
    assert patched.status_code == 200
    assert patched.json()["duration_seconds"] == 1800

    login("user-b-code")
    other_baby_id = _create_baby(client, headers)
    assert client.get(f"/api/v1/babies/{baby_id}/events").status_code == 404
    assert client.post(
        f"/api/v1/babies/{baby_id}/events",
        json={"event_type": "wake", "start_time": "2025-12-31T23:00:00Z"},
        headers=_event_headers(headers),
    ).status_code == 404
    for method in ("patch", "delete"):
        kwargs = {"headers": _event_headers(headers)}
        if method == "patch":
            kwargs["json"] = {"event_type": "wake"}
        response = getattr(client, method)(f"/api/v1/events/{event_id}", **kwargs)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "resource_not_found"
    assert client.get(f"/api/v1/babies/{other_baby_id}/events").json() == []

    login("user-a-code")
    assert client.delete(
        f"/api/v1/events/{event_id}", headers=_event_headers(headers)
    ).status_code == 204
    assert client.get(f"/api/v1/babies/{baby_id}/events").json() == []


def test_event_validation_rejects_impossible_or_malformed_values(configured_client) -> None:
    client, login, headers, _, _ = configured_client
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    invalid_payloads = [
        {"event_type": "unknown", "start_time": "2025-12-31T23:00:00Z"},
        {"user_id": "attacker", "event_type": "wake", "start_time": "2025-12-31T23:00:00Z"},
        {"source": "import", "event_type": "wake", "start_time": "2025-12-31T23:00:00Z"},
        {
            "event_type": "sleep",
            "start_time": "2025-12-31T23:00:00Z",
            "end_time": "2025-12-31T22:00:00Z",
        },
        {
            "event_type": "sleep",
            "start_time": "2025-12-31T23:00:00Z",
            "duration_seconds": -1,
        },
        {
            "event_type": "sleep",
            "start_time": "2025-12-31T23:00:00Z",
            "end_time": "2026-01-01T00:00:00Z",
            "duration_seconds": 30,
        },
        {
            "event_type": "sleep",
            "start_time": "2025-12-31T23:00:00Z",
            "feed_amount_ml": 120,
        },
        {
            "event_type": "wake",
            "start_time": "2025-12-31T23:00:00Z",
            "end_time": "2025-12-31T23:01:00Z",
        },
        {"event_type": "wake", "start_time": "not-a-timestamp"},
        {
            "event_type": "feed",
            "start_time": "2025-12-31T23:00:00Z",
            "feed_amount_ml": 10001,
        },
        {
            "event_type": "wake",
            "start_time": "2999-12-31T23:00:00Z",
        },
        {
            "event_type": "wake",
            "start_time": "2025-12-31T23:00:00Z",
            "timezone": "PST",
        },
        {
            "event_type": "wake",
            "start_time": "2025-11-02T01:30:00",
            "timezone": "America/New_York",
        },
        {
            "event_type": "wake",
            "start_time": "2025-03-09T02:30:00",
            "timezone": "America/New_York",
        },
    ]
    for payload in invalid_payloads:
        response = client.post(
            f"/api/v1/babies/{baby_id}/events",
            json=payload,
            headers=_event_headers(headers),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    valid = client.post(
        f"/api/v1/babies/{baby_id}/events",
        json={
            "event_type": "feed",
            "start_time": "2025-12-31T18:00:00",
            "end_time": "2025-12-31T18:10:00",
            "duration_seconds": 600,
            "feed_amount_ml": "120.50",
            "timezone": "America/New_York",
        },
        headers=_event_headers(headers),
    )
    assert valid.status_code == 201
    assert valid.json()["start_time"] == "2025-12-31T23:00:00Z"
    assert valid.json()["feed_amount_ml"] == "120.50"


def test_event_patch_rejects_unknown_fields_malformed_ids_and_oversized_body(
    configured_client,
) -> None:
    client, login, headers, _, _ = configured_client
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    created = client.post(
        f"/api/v1/babies/{baby_id}/events",
        json={"event_type": "wake", "start_time": "2025-12-31T23:00:00Z"},
        headers=_event_headers(headers),
    )
    event_id = created.json()["id"]

    for path, payload in (
        (f"/api/v1/events/{event_id}", {"baby_id": str(baby_id)}),
        ("/api/v1/events/not-a-uuid", {"event_type": "wake"}),
    ):
        response = client.patch(
            path, json=payload, headers=_event_headers(headers)
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"

    oversized = client.patch(
        f"/api/v1/events/{event_id}",
        content=b"{}",
        headers={
            **_event_headers(headers),
            "content-type": "application/json",
            "content-length": "4097",
        },
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "invalid_request"


def test_event_mutations_require_csrf_and_server_session(configured_client) -> None:
    client, login, headers, _, _ = configured_client
    assert client.get("/api/v1/babies/not-a-uuid/events").status_code == 401
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    response = client.post(
        f"/api/v1/babies/{baby_id}/events",
        json={"event_type": "wake", "start_time": "2025-12-31T23:00:00Z"},
        headers={"Origin": "https://frontend.example.test"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"
