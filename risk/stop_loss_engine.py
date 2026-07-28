import logging

logger = logging.getLogger(__name__)


def calculate_stop_loss(entry_price: float, stop_loss_pct: float = 5.0) -> float:
    """Calculate the initial stop loss price for a position."""
    stop_price = entry_price * (1 - stop_loss_pct / 100)
    logger.debug(f"Stop loss set at £{stop_price:.2f} ({stop_loss_pct}% below £{entry_price:.2f})")
    return round(stop_price, 4)


def calculate_take_profit(entry_price: float, take_profit_pct: float = 15.0,
                           ticker: str = None) -> float:
    """Calculate take profit price, ATR-adjusted if ticker provided."""
    if ticker:
        try:
            import yfinance as yf
            df = yf.download(ticker, period="30d", interval="1d",
                             progress=False, auto_adjust=True)
            if not df.empty:
                high = df["High"].squeeze()
                low = df["Low"].squeeze()
                close = df["Close"].squeeze()
                atr = float((high - low).rolling(14).mean().iloc[-1])
                atr_pct = (atr / float(close.iloc[-1])) * 100

                if atr_pct < 1.5:
                    take_profit_pct = 12.0
                elif atr_pct > 3.0:
                    take_profit_pct = 20.0
                else:
                    take_profit_pct = 15.0

                logger.info(f"{ticker} ATR={atr_pct:.2f}% -> TP set to {take_profit_pct}%")
        except Exception as e:
            logger.warning(f"Dynamic TP failed for {ticker}, using default: {e}")

    take_profit_price = entry_price * (1 + take_profit_pct / 100)
    logger.debug(f"Take profit set at £{take_profit_price:.2f} ({take_profit_pct}% above £{entry_price:.2f})")
    return round(take_profit_price, 4)


def calculate_trailing_stop(current_price: float,
                             highest_price: float,
                             trail_pct: float = 5.0) -> float:
    """Calculate trailing stop loss based on highest price seen."""
    trailing_stop = highest_price * (1 - trail_pct / 100)
    logger.debug(f"Trailing stop: £{trailing_stop:.2f} ({trail_pct}% below high of £{highest_price:.2f})")
    return round(trailing_stop, 4)


def get_edge_trail_pct(pnl_pct: float) -> float:
    """
    Returns the trailing stop percentage for an EdgeScanner position.
    Trail tightens as profit grows to lock in gains.

    Bands:
        0-20%   profit -> 8% trail  (room to breathe at entry)
        20-50%  profit -> 6% trail  (tightening, locking in gains)
        50-150% profit -> 4% trail  (tight, protecting large gains)
        150%+   profit -> 3% trail  (very tight, near rocket peak)
    """
    if pnl_pct >= 150.0:
        return 3.0
    elif pnl_pct >= 50.0:
        return 4.0
    elif pnl_pct >= 20.0:
        return 6.0
    else:
        return 8.0


def check_exit_conditions(current_price: float,
                           entry_price: float,
                           stop_loss_pct: float = 5.0,
                           take_profit_pct: float = 15.0,
                           highest_price: float = None,
                           edge_tightening_trail: bool = False,
                           min_hold_days: int = 0,
                           entry_date: str = None) -> dict:
    """
    Check whether a position should be exited.

    EdgeScanner positions (edge_tightening_trail=True):
        - No hard take profit — rides the full move
        - Trail tightens automatically as profit grows

    TradeCore positions (edge_tightening_trail=False):
        - Hard take profit at take_profit_pct
        - Fixed trailing stop at stop_loss_pct
    """
    pnl_pct = ((current_price - entry_price) / entry_price) * 100
    if min_hold_days > 0 and entry_date:
        from datetime import datetime, date
        try:
            entry = datetime.strptime(entry_date, "%Y-%m-%d").date()
            days_held = (date.today() - entry).days
            if days_held < min_hold_days:
                return {"should_exit": False, "reason": f"MIN_HOLD ({min_hold_days}d) — held {days_held}d", "pnl_pct": round(pnl_pct, 2)}
        except Exception:
            pass

    # EdgeScanner: tightening trail, no hard TP
    if edge_tightening_trail and highest_price is not None:
        trail_pct = get_edge_trail_pct(pnl_pct)
        trailing_stop = calculate_trailing_stop(current_price, highest_price, trail_pct)

        logger.info(f"EdgeScanner trail | PnL={pnl_pct:.1f}% | "
                    f"Trail={trail_pct}% | Stop=£{trailing_stop:.2f} | "
                    f"High=£{highest_price:.2f}")

        if current_price <= trailing_stop:
            return {
                "should_exit": True,
                "reason": f"EDGE_TRAIL_{trail_pct}pct (PnL={pnl_pct:.1f}%)",
                "pnl_pct": round(pnl_pct, 2),
                "stop_price": trailing_stop,
                "take_profit_price": None
            }
        return {
            "should_exit": False,
            "reason": "HOLD",
            "pnl_pct": round(pnl_pct, 2),
            "stop_price": trailing_stop,
            "take_profit_price": None
        }

    # TradeCore: hard TP + trailing stop
    take_profit_price = calculate_take_profit(entry_price, take_profit_pct)

    if current_price >= take_profit_price:
        return {
            "should_exit": True,
            "reason": "TAKE_PROFIT",
            "pnl_pct": round(pnl_pct, 2),
            "stop_price": None,
            "take_profit_price": take_profit_price
        }

    if highest_price is not None:
        trailing_stop = calculate_trailing_stop(current_price, highest_price, stop_loss_pct)
        if current_price <= trailing_stop:
            logger.info(f"Trailing stop hit | Price £{current_price:.2f} <= "
                       f"Stop £{trailing_stop:.2f} (High £{highest_price:.2f})")
            return {
                "should_exit": True,
                "reason": "TRAILING_STOP",
                "pnl_pct": round(pnl_pct, 2),
                "stop_price": trailing_stop,
                "take_profit_price": take_profit_price
            }
        return {
            "should_exit": False,
            "reason": "HOLD",
            "pnl_pct": round(pnl_pct, 2),
            "stop_price": trailing_stop,
            "take_profit_price": take_profit_price
        }

    stop_price = calculate_stop_loss(entry_price, stop_loss_pct)
    if current_price <= stop_price:
        return {
            "should_exit": True,
            "reason": "STOP_LOSS",
            "pnl_pct": round(pnl_pct, 2),
            "stop_price": stop_price,
            "take_profit_price": take_profit_price
        }

    return {
        "should_exit": False,
        "reason": "HOLD",
        "pnl_pct": round(pnl_pct, 2),
        "stop_price": stop_price,
        "take_profit_price": take_profit_price
    }