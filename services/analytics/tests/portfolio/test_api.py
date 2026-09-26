from fastapi.testclient import TestClient

from wheelhouse_service.http import create_app
from wheelhouse_service.portfolio.broker import BrokerUnavailable, MoomooReader

PREFIX = "/api/wheelhouse/v1/portfolio"


def test_demo_account_wheel_and_risk_have_independent_persistent_routes(tmp_path):
    with TestClient(create_app(tmp_path / "market.sqlite", start_worker=False)) as client:
        assert client.post(PREFIX + "/demo").status_code == 200
        response = client.get(
            PREFIX + "/workspace", params={"source": "demo", "account_id": "wheelhouse-demo"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "simulated"
        assert data["cycles"][0]["premium_received"] == "500"
        assert data["cycles"][0]["realized_net"] == "198"
        assert data["risk"]["dollar_delta"] == "7350"
        assert data["risk"]["theta_daily"] == "5"
        assert data["risk"]["vega_point"] == "-10"
        absent = client.get(
            PREFIX + "/workspace", params={"source": "moomoo", "account_id": "123"}
        ).json()
        assert absent["capture"] is None
        assert client.post(PREFIX + "/place_order").status_code == 404


def test_reader_rejects_missing_sdk_and_unapproved_operations(tmp_path):
    import pytest

    reader = MoomooReader(tmp_path / "absent-python")
    assert reader.status()["sdk_installed"] is False
    with pytest.raises(BrokerUnavailable):
        reader.accounts()
