import logging
from config.settings import CASH_FLOOR, MAX_POSITION_SIZE

logger = logging.getLogger(__name__)


def calculate_position_size(portfolio_value: float,
                             cash_available: float,
                             current_price: float,
                             confidence: float,
                             max_position_pct: float = MAX_POSITION_SIZE) -> dict:
    """
    Calculate the optimal position size for a trade using
    a confidence-weighted fixed fractional method.

    Rules:
        - Never invest more than max_position_pct of portfolio in one trade
        - Scale investment size with confidence level
        - Never trade below the cash floor
        - Never invest more cash than is available

    Args:
        portfolio_value:  Total portfolio value (cash + positions)
        cash_available:   Liquid cash available to invest
        current_price:    Current stock price
        confidence:       Signal confidence 0-100
        max_position_pct: Maximum % of portfolio per position

    Returns:
        Dict with shares, invest_amount, and reasoning
    """
    if not current_price or current_price <= 0 or current_price != current_price:
        return _rejected("Invalid price")

    if cash_available < CASH_FLOOR:
        return _rejected(f"Cash below floor (£{cash_available:.2f} < £{CASH_FLOOR:.2f})")

    # Scale position size by confidence
    # 65% confidence → 60% of max allocation
    # 80% confidence → 80% of max allocation
    # 95% confidence → 100% of max allocation
    confidence_factor = min((confidence - 65) / 35 + 0.6, 1.0)
    confidence_factor = max(confidence_factor, 0.6)

    max_invest = portfolio_value * max_position_pct
    scaled_invest = max_invest * confidence_factor

    # Cap to available cash
    invest_amount = min(scaled_invest, cash_available * 0.95)

    if invest_amount < CASH_FLOOR:
        return _rejected(f"Scaled invest amount below floor (£{invest_amount:.2f})")

    shares = invest_amount / current_price

    logger.info(f"Position size: £{invest_amount:.2f} | "
                f"{shares:.4f} shares @ £{current_price:.2f} | "
                f"Conf factor={confidence_factor:.2f}")

    return {
        "approved": True,
        "invest_amount": round(invest_amount, 2),
        "shares": round(shares, 4),
        "confidence_factor": round(confidence_factor, 2),
        "reason": f"Approved | ConfFactor={confidence_factor:.2f}"
    }


def _rejected(reason: str) -> dict:
    """Return a rejected position size result."""
    logger.warning(f"Position rejected: {reason}")
    return {
        "approved": False,
        "invest_amount": 0.0,
        "shares": 0.0,
        "confidence_factor": 0.0,
        "reason": reason
    }