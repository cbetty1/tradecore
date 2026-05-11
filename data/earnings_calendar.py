import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_upcoming_earnings(ticker: str, days_ahead: int = 3) -> bool:
    """
    Check if a stock has earnings due in the next X days.
    Uses yfinance to check earnings dates.

    Args:
        ticker:     Stock ticker
        days_ahead: Number of days to look ahead

    Returns:
        True if earnings due soon — avoid entry
        False if clear — safe to enter
    """
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        calendar = stock.calendar

        if calendar is None:
            return False

# yfinance returns calendar as a dict
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

        # Check if any earnings date falls within window
        if hasattr(earnings_dates, '__iter__'):
            for date in earnings_dates:
                try:
                    if hasattr(date, 'date'):
                        earnings_date = date.date()
                    else:
                        earnings_date = datetime.strptime(
                            str(date), '%Y-%m-%d').date()
                    if today <= earnings_date <= cutoff:
                        logger.info(f"{ticker} has earnings on "
                                   f"{earnings_date} — avoiding entry")
                        return True
                except Exception:
                    continue
        return False

    except Exception as e:
        logger.warning(f"Earnings check failed for {ticker}: {e}")
        return False


def is_earnings_safe(ticker: str) -> bool:
    """
    Returns True if safe to enter — no earnings in next 3 days
    Returns False if earnings approaching — avoid entry
    """
    has_earnings = get_upcoming_earnings(ticker, days_ahead=3)
    return not has_earnings