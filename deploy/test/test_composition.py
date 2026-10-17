"""Test deployment starts public analysis while broker collection remains disabled."""
from unittest.mock import patch

from fastapi.testclient import TestClient
from wheelhouse_service.http import create_app


def test_market_starts_but_broker_and_perps_do_not(tmp_path):
    with patch('wheelhouse_service.http.Runtime.start') as market, patch('wheelhouse_service.portfolio.api.BrokerSync.start') as broker, patch('wheelhouse_service.perps.api.PerpsSync.start') as perps_worker, patch('wheelhouse_service.perps.api.Collectors.start') as perps_collectors:
        with TestClient(create_app(tmp_path/'analytics.sqlite', start_broker_worker=False, start_perps=False)) as client:
            assert client.get('/api/wheelhouse/v1/status').status_code == 200
            market.assert_called_once()
            broker.assert_not_called()
            perps_worker.assert_not_called()
            perps_collectors.assert_not_called()
