import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_upcoming_earnings(ticker: str, days_ahead: int = 3) -> bool:
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        calendar = stock.calendar

        if calendar is None:
            return False

        if isinstance(calendar, dict):
            earnings_dates = calendar.get('Earnings Date', [])
            if not earnings_dates:
                return False
        else:
            if calendar.empty:
                return False
            if 'Earnings Date' in calendar.columns:
                earnings_dates = calendar['Earnings Date']
            elif 'Earnings Date' in calendar.index:
                earnings_dates = calendar.loc['Earnings Date']
            else:
                return False

        today = datetime.now().date()
        cutoff = today + timedelta(days=days_ahead)

        if hasattr(earnings_dates, '__iter__'):
            for date in earnings_dates:
                try:
                    if hasattr(date, 'date'):
                        earnings_date = date.date()
                    else:
                        earnings_date = datetime.strptime(str(date), '%Y-%m-%d').date()
                    if today <= earnings_date <= cutoff:
                        logger.info(f"{ticker} has earnings on {earnings_date} — avoiding entry")
                        return True
                except Exception:
                    continue
        return False

    except Exception as e:
        logger.warning(f"Earnings check failed for {ticker}: {e}")
        return False


def is_earnings_safe(ticker: str) -> bool:
    """Returns True if safe to enter — no earnings in next 3 days."""
    return not get_upcoming_earnings(ticker, days_ahead=3)


def had_recent_earnings(ticker: str, days: int = 2) -> bool:
    """
    Returns True if this stock reported earnings in the last X days.
    Used by the earnings drift signal to hunt post-earnings continuation.
    Opposite of is_earnings_safe — we WANT stocks that just reported.
    """
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        calendar = stock.calendar

        if calendar is None:
            return False

        if isinstance(calendar, dict):
            earnings_dates = calendar.get('Earnings Date', [])
            if not earnings_dates:
                return False
        else:
            if calendar.empty:
                return False
            if 'Earnings Date' in calendar.columns:
                earnings_dates = calendar['Earnings Date']
            elif 'Earnings Date' in calendar.index:
                earnings_dates = calendar.loc['Earnings Date']
            else:
                return False

        today = datetime.now().date()
        lookback = today - timedelta(days=days)

        if hasattr(earnings_dates, '__iter__'):
            for date in earnings_dates:
                try:
                    if hasattr(date, 'date'):
                        earnings_date = date.date()
                    else:
                        earnings_date = datetime.strptime(str(date), '%Y-%m-%d').date()
                    if lookback <= earnings_date <= today:
                        logger.info(f"{ticker} reported earnings on {earnings_date} — drift candidate")
                        return True
                except Exception:
                    continue
        return False

    except Exception as e:
        logger.warning(f"Recent earnings check failed for {ticker}: {e}")
        return False