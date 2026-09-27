from fastapi.testclient import TestClient

from wheelhouse_service.http import create_app


def test_host_can_distinguish_service_readiness_from_unavailable_integrations(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite", start_worker=False)) as client:
        response = client.get("/api/wheelhouse/v1/status")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
        assert response.json()["contract_version"] == "1"
        assert response.json()["read_only"] is True
        assert response.json()["integrations"]["broker"] == "not_connected"
        assert response.json()["integrations"]["market_data"] == "not_connected"
        assert "historical_replay" in response.json()["capabilities"]
        assert response.json()["integrations"]["analytics"] == "baseline_ready"
        assert len(response.headers["x-request-id"]) == 32


def test_missing_and_write_endpoints_fail_with_traceable_errors(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite", start_worker=False)) as client:
        missing = client.get("/api/wheelhouse/v1/orders")
        assert missing.status_code == 404
        assert missing.json()["code"] == "http_404"
        assert missing.json()["request_id"] == missing.headers["x-request-id"]
        assert client.post("/api/wheelhouse/v1/status").status_code == 405
        assert (
            client.get(
                "/api/wheelhouse/v1/status", headers={"Host": "external.example"}
            ).status_code
            == 400
        )


def test_status_responses_are_not_cached_and_openapi_is_versioned(tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite", start_worker=False)) as client:
        first = client.get("/api/wheelhouse/v1/status")
        second = client.get("/api/wheelhouse/v1/status")
        assert first.headers["cache-control"] == "no-store"
        assert first.headers["x-request-id"] != second.headers["x-request-id"]
        schema = client.get("/api/wheelhouse/v1/openapi.json").json()
        assert "/api/wheelhouse/v1/workspace" in schema["paths"]
        assert not any("orders" in path or "unlock" in path for path in schema["paths"])
        assert set(schema["paths"]["/api/wheelhouse/v1/status"]) == {"get"}
