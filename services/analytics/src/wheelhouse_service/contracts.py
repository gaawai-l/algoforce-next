"""Versioned transport contracts. No host or brokerage dependencies."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Integrations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    broker: Literal["not_connected"]
    market_data: Literal["not_connected"]
    analytics: Literal["not_implemented"]


class ServiceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: Literal["wheelhouse-python"]
    status: Literal["ready"]
    contract_version: Literal["1"]
    service_version: str
    python_version: str
    checked_at: datetime
    read_only: Literal[True]
    integrations: Integrations
    capabilities: list[Literal["service_status"]]


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
