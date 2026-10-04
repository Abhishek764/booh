from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_health_check_uses_versioned_contract() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "booh-api",
        "version": "0.1.0",
    }


def test_unversioned_health_route_is_not_public() -> None:
    response = client.get("/health")

    assert response.status_code == 404


def test_validation_errors_are_bounded() -> None:
    response = client.get("/api/v1/health", params={"unexpected": "private-value"})

    # The health route has no query contract, so unexpected values do not change
    # its response or get reflected into an error body.
    assert response.status_code == 200
    assert "private-value" not in response.text
