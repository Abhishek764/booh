from uuid import uuid4

from backend.tests.test_baby_routes import configured_client as configured_client
from backend.tests.test_event_routes import _create_baby
from backend.tests.test_importers import FIXTURES


def upload(client, baby_id, headers, payload, **kwargs):
    return client.post(
        f"/api/v1/babies/{baby_id}/imports",
        content=payload,
        headers={**headers(), "Content-Type": "text/csv; charset=utf-8"},
        **kwargs,
    )


def test_import_summary_persistence_reimport_and_cross_format_duplicates(configured_client):
    client, login, headers, _, _ = configured_client
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    response = upload(client, baby_id, headers, (FIXTURES / "huckleberry.csv").read_bytes())
    assert response.status_code == 200
    assert response.json() == {
        "rows_processed": 6, "rows_imported": 3, "rows_skipped": 2,
        "rows_failed": 1, "duplicates": 1,
        "errors": [{"row": 7, "code": "invalid_date"}], "errors_truncated": False,
    }
    assert response.headers["Cache-Control"] == "no-store"
    events = client.get(f"/api/v1/babies/{baby_id}/events").json()
    assert len(events) == 3
    assert all(event["source"] == "import" for event in events)
    assert all("notes" not in event and "user_id" not in event for event in events)
    for name, duplicates in (("huckleberry.csv", 4), ("generic.csv", 3)):
        response = upload(client, baby_id, headers, (FIXTURES / name).read_bytes())
        assert response.status_code == 200
        assert response.json()["rows_imported"] == 0
        assert response.json()["duplicates"] == duplicates
    assert len(client.get(f"/api/v1/babies/{baby_id}/events").json()) == 3


def test_existing_manual_events_are_duplicates_and_other_babies_are_independent(configured_client):
    client, login, headers, _, _ = configured_client
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    manual = client.post(
        f"/api/v1/babies/{baby_id}/events",
        json={"event_type": "sleep", "start_time": "2025-12-30T22:00:00Z", "end_time": "2025-12-30T23:30:00Z"},
        headers=headers(),
    )
    assert manual.status_code == 201
    response = upload(client, baby_id, headers, (FIXTURES / "generic.csv").read_bytes())
    assert response.json()["duplicates"] == 1
    assert response.json()["rows_imported"] == 2
    other_baby = _create_baby(client, headers)
    assert upload(client, other_baby, headers, (FIXTURES / "generic.csv").read_bytes()).json()["rows_imported"] == 3


def test_import_authentication_csrf_origin_and_cross_user_isolation(configured_client):
    client, login, headers, _, _ = configured_client
    payload = (FIXTURES / "generic.csv").read_bytes()
    path = f"/api/v1/babies/{uuid4()}/imports"
    assert client.post(path, content=payload, headers={"Content-Type": "text/csv"}).status_code == 401
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    path = f"/api/v1/babies/{baby_id}/imports"
    assert client.post(path, content=payload, headers={"Content-Type": "text/csv", "Origin": headers()["Origin"]}).status_code == 403
    assert client.post(path, content=payload, headers={**headers(), "Content-Type": "text/csv", "Origin": "https://attacker.example.test"}).status_code == 403
    assert upload(client, baby_id, headers, payload).status_code == 200
    login("user-b-code")
    foreign = upload(client, baby_id, headers, payload)
    missing = upload(client, uuid4(), headers, payload)
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    own_baby = _create_baby(client, headers)
    assert upload(client, own_baby, headers, payload).json()["duplicates"] == 0
    assert len(client.get(f"/api/v1/babies/{own_baby}/events").json()) == 3


def test_profile_timezone_override_and_invalid_query_contracts(configured_client):
    client, login, headers, _, _ = configured_client
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    assert client.patch(f"/api/v1/babies/{baby_id}", json={"timezone": "America/New_York"}, headers=headers()).status_code == 200
    payload = b"Type,Start\nWake,2025-12-30 22:00\n"
    assert upload(client, baby_id, headers, payload).json()["rows_imported"] == 1
    assert client.get(f"/api/v1/babies/{baby_id}/events").json()[0]["start_time"] == "2025-12-31T03:00:00Z"
    assert upload(client, baby_id, headers, payload, params={"timezone": "UTC"}).json()["rows_imported"] == 1
    for params in ({"format": "python"}, {"date_order": "guess"}, {"user_id": "attacker"}, {"timezone": "../etc/passwd"}):
        response = upload(client, baby_id, headers, payload, params=params)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"
    assert upload(client, "not-a-uuid", headers, payload).status_code == 422


def test_structurally_malformed_csv_aborts_before_persisting_valid_rows(configured_client):
    client, login, headers, _, _ = configured_client
    login("user-a-code")
    baby_id = _create_baby(client, headers)
    payload = b'event_type,start_time\nwake,2025-12-30T22:00:00Z\nsleep,"unterminated\n'
    response = upload(client, baby_id, headers, payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "malformed_csv"
    assert client.get(f"/api/v1/babies/{baby_id}/events").json() == []
