from typing import SupportsFloat


def safe_ratio(numerator: SupportsFloat | None, denominator: SupportsFloat | None) -> float | None:
    if numerator is None or denominator is None:
        return None
    den = float(denominator)
    if den == 0:
        return None
    return float(numerator) / den


def calculate_ratios(data: dict[str, float | int | None]) -> dict[str, float | None]:
    revenue = data.get("revenue")
    operating_profit = data.get("operating_profit")
    net_profit = data.get("net_profit")
    equity = data.get("equity")
    assets = data.get("assets")
    current_assets = data.get("current_assets")
    current_liabilities = data.get("current_liabilities")
    debt = data.get("debt")
    return {
        "operating_margin": safe_ratio(operating_profit, revenue),
        "net_margin": safe_ratio(net_profit, revenue),
        "equity_ratio": safe_ratio(equity, assets),
        "debt_ratio": safe_ratio(debt, assets),
        "current_ratio": safe_ratio(current_assets, current_liabilities),
    }
