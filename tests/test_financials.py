from apps.api.app.services.financials import calculate_ratios


def test_ratios_are_deterministic() -> None:
    result = calculate_ratios(
        {
            "revenue": 100,
            "operating_profit": 10,
            "net_profit": 5,
            "equity": 40,
            "assets": 100,
            "debt": 60,
            "current_assets": 50,
            "current_liabilities": 25,
        }
    )
    assert result["operating_margin"] == 0.1
    assert result["equity_ratio"] == 0.4
    assert result["current_ratio"] == 2.0
