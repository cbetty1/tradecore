import logging
import pandas as pd
from data.price_feed import get_historical_data

logger = logging.getLogger(__name__)


def get_correlation(ticker_a: str, ticker_b: str, period: str = "3mo") -> float | None:
    """
    Calculate the price correlation between two tickers.

    Returns:
        Correlation coefficient between -1.0 and 1.0, or None if unavailable
    """
    try:
        df_a = get_historical_data(ticker_a, period=period)
        df_b = get_historical_data(ticker_b, period=period)

        if df_a is None or df_b is None:
            return None

        close_a = df_a["Close"].squeeze()
        close_b = df_b["Close"].squeeze()

        combined = pd.DataFrame({"a": close_a, "b": close_b}).dropna()

        if len(combined) < 20:
            return None

        correlation = combined["a"].corr(combined["b"])
        return round(float(correlation), 4)

    except Exception as e:
        logger.error(f"Correlation check failed for {ticker_a}/{ticker_b}: {e}")
        return None


def is_too_correlated(new_ticker: str,
                       open_positions: list,
                       correlation_limit: float = 0.85) -> dict:
    """
    Check if a new position would be too correlated with existing open positions.

    Args:
        new_ticker:        Ticker being considered for entry
        open_positions:    List of currently held ticker strings
        correlation_limit: Maximum allowed correlation coefficient

    Returns:
        Dict with blocked flag and reason
    """
    if not open_positions:
        return {"blocked": False, "reason": "No open positions to correlate against"}

    for held_ticker in open_positions:
        if held_ticker == new_ticker:
            return {"blocked": True, "reason": f"Already holding {new_ticker}"}

        corr = get_correlation(new_ticker, held_ticker)
        if corr is None:
            continue

        if corr >= correlation_limit:
            reason = (f"{new_ticker} is too correlated with {held_ticker} "
                      f"(corr={corr:.2f} >= limit={correlation_limit})")
            logger.warning(f"Correlation block: {reason}")
            return {"blocked": True, "reason": reason}

    return {"blocked": False, "reason": "Correlation check passed"}