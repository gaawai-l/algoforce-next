from datetime import timedelta

from test_ledger import NOW, PUT

from wheelhouse_service.portfolio.models import FxRate, PortfolioCapture, Position, Quote
from wheelhouse_service.portfolio.risk import calculate_risk


def test_short_option_normalization_nonstandard_multiplier_and_fx():
    instrument = PUT.model_copy(update={"multiplier": "10", "currency": "SGD"})
    capture = PortfolioCapture(
        source="demo",
        account_id="demo",
        captured_at=NOW,
        positions=[Position(code=instrument.code, quantity="-2", observed_at=NOW)],
        instruments=[instrument],
        quotes=[
            Quote(
                code=instrument.code,
                spot="100",
                delta="-0.3",
                gamma="0.02",
                theta="-0.05",
                vega="0.1",
                units="per_share",
                theta_basis="day",
                vega_basis="percentage_point",
                observed_at=NOW,
                source="fixture",
            )
        ],
        fx=[FxRate(currency="SGD", to_base="0.75", observed_at=NOW, source="fixture")],
        raw={},
        errors={},
    )
    risk = calculate_risk(capture, at=NOW)
    assert risk.state == "complete"
    assert risk.exposures[0].share_delta == "6"
    assert risk.exposures[0].share_gamma == "-0.4"
    assert risk.dollar_delta == "450"
    assert risk.theta_daily == "0.75"
    assert risk.vega_point == "-1.5"
    stale = calculate_risk(capture, at=NOW + timedelta(hours=1))
    assert stale.dollar_delta is None
    assert stale.state == "unavailable"


def test_per_contract_year_theta_unit_vega_and_missing_fx():
    quote = Quote(
        code=PUT.code,
        spot="100",
        delta="-30",
        gamma="2",
        theta="-365",
        vega="1000",
        units="per_contract",
        theta_basis="year",
        vega_basis="unit_volatility",
        observed_at=NOW,
        source="fixture",
    )
    capture = PortfolioCapture(
        source="demo",
        account_id="demo",
        captured_at=NOW,
        positions=[Position(code=PUT.code, quantity="-1", observed_at=NOW)],
        instruments=[PUT],
        quotes=[quote],
        fx=[],
        raw={},
        errors={},
    )
    result = calculate_risk(capture, at=NOW)
    assert result.exposures[0].share_delta == "30"
    assert result.theta_daily == "1"
    assert result.vega_point == "-10"
    missing = capture.model_copy(update={"base_currency": "SGD"})
    result = calculate_risk(missing, at=NOW)
    assert result.exposures[0].share_delta == "30"
    assert result.dollar_delta is None
