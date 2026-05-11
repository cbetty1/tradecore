import os
import logging
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from config.settings import CACHE_DIR

logger = logging.getLogger(__name__)

# Ensure cache directory exists
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(ticker: str) -> str:
    """Return the local Parquet cache file path for a ticker."""
    return os.path.join(CACHE_DIR, f"{ticker.replace('.', '_')}.parquet")


def _load_from_cache(ticker: str) -> pd.DataFrame | None:
    """Load cached price data if it exists and is from today."""
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_parquet(path)
        # If cache was written today, use it
        modified = datetime.fromtimestamp(os.path.getmtime(path))
        if modified.date() == datetime.today().date():
            logger.debug(f"Cache hit for {ticker}")
            return df
        return None
    except Exception as e:
        logger.warning(f"Cache read failed for {ticker}: {e}")
        return None


def _save_to_cache(ticker: str, df: pd.DataFrame):
    """Save price data to local Parquet cache."""
    try:
        df.to_parquet(_cache_path(ticker))
        logger.debug(f"Cached {ticker} to parquet.")
    except Exception as e:
        logger.warning(f"Cache write failed for {ticker}: {e}")


def get_historical_data(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame | None:
    """
    Fetch historical OHLCV data for a ticker.
    Uses local cache if available and fresh, otherwise fetches from yfinance.

    Args:
        ticker:   Stock ticker e.g. 'NVDA' or 'VWCE.L'
        period:   Lookback period e.g. '1mo', '3mo', '6mo', '1y', '2y'
        interval: Bar size e.g. '1d', '1h', '15m'

    Returns:
        DataFrame with columns: Open, High, Low, Close, Volume
        or None if fetch fails.
    """
    # Only cache daily data
    if interval == "1d":
        cached = _load_from_cache(ticker)
        if cached is not None:
            return cached

    try:
        logger.info(f"Fetching {ticker} | period={period} | interval={interval}")
        df = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)

        if df.empty:
            logger.warning(f"No data returned for {ticker}")
            return None

        # Flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.dropna(inplace=True)

        if interval == "1d":
            _save_to_cache(ticker, df)

        return df

    except Exception as e:
        logger.error(f"Failed to fetch data for {ticker}: {e}")
        return None


def get_latest_price(ticker: str) -> float | None:
    """
    Fetch the latest live price for a ticker.
    Bypasses cache and fetches directly from yfinance.

    Returns:
        Latest close price as float, or None if unavailable.
    """
    try:
        df = yf.download(
            ticker, period="5d", interval="1d",
            progress=False, auto_adjust=True
        )
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.error(f"Failed to get latest price for {ticker}: {e}")
        return None


def get_bulk_latest_prices(tickers: list) -> dict:
    """
    Fetch latest prices for a list of tickers.

    Returns:
        Dict of {ticker: price}
    """
    prices = {}
    for ticker in tickers:
        price = get_latest_price(ticker)
        if price is not None:
            prices[ticker] = price
        else:
            logger.warning(f"Could not fetch price for {ticker}")
    return prices