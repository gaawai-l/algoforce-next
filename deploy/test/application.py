"""Test-only composition root: public/simulated data, broker collection disabled."""
from wheelhouse_service.http import create_app

app = create_app(start_broker_worker=False)
