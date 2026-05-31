import logging

logger = logging.getLogger(__name__)


def calculate_stop_loss(entry_price: float, stop_loss_pct: float = 5.0) -> float:
    """
    Calculate the initial stop loss price for a position.

    Args:
        entry_price:    Price at which the position was entered
        stop_loss_pct:  Percentage below entry to place stop loss

    Returns:
        Stop loss price
    """
    stop_price = entry_price * (1 - stop_loss_pct / 100)
    logger.debug(f"Stop loss set at £{stop_price:.2f} "
                f"({stop_loss_pct}% below £{entry_price:.2f})")
    return round(stop_price, 4)


def calculate_take_profit(entry_price: float, take_profit_pct: float = 15.0,
                           ticker: str = None) -> float:
    """
    Calculate take profit price. If ticker is provided, adjusts based on
    the stock's recent volatility (ATR-based). High volatility = wider TP,
    low volatility = tighter TP.

    Returns:
        Take profit price
    """
    if ticker:
        try:
            import yfinance as yf
            df = yf.download(ticker, period="30d", interval="1d",
                             progress=False, auto_adjust=True)
            if not df.empty:
                high = df["High"].squeeze()
                low = df["Low"].squeeze()
                close = df["Close"].squeeze()
                # ATR as % of price
                atr = float((high - low).rolling(14).mean().iloc[-1])
                atr_pct = (atr / float(close.iloc[-1])) * 100

                # Scale TP: base 15%, adjusted by how volatile the stock is
                # ATR < 1.5% = tight stock → TP 12%
                # ATR 1.5–3% = normal → TP 15%
                # ATR > 3% = volatile → TP 20%
                if atr_pct < 1.5:
                    take_profit_pct = 12.0
                elif atr_pct > 3.0:
                    take_profit_pct = 20.0
                else:
                    take_profit_pct = 15.0

                logger.info(f"{ticker} ATR={atr_pct:.2f}% → TP set to {take_profit_pct}%")
        except Exception as e:
            logger.warning(f"Dynamic TP failed for {ticker}, using default: {e}")

    take_profit_price = entry_price * (1 + take_profit_pct / 100)
    logger.debug(f"Take profit set at £{take_profit_price:.2f} "
                 f"({take_profit_pct}% above £{entry_price:.2f})")
    return round(take_profit_price, 4)


def calculate_trailing_stop(current_price: float,
                             highest_price: float,
                             trail_pct: float = 5.0) -> float:
    """
    Calculate trailing stop loss based on highest price seen.

    The trailing stop follows the price upward but never moves down.
    It is always trail_pct% below the highest price seen.

    Args:
        current_price:  Current market price
        highest_price:  Highest price seen since entry
        trail_pct:      Trailing percentage below highest price

    Returns:
        Trailing stop price
    """
    trailing_stop = highest_price * (1 - trail_pct / 100)
    logger.debug(f"Trailing stop: £{trailing_stop:.2f} "
                f"({trail_pct}% below high of £{highest_price:.2f})")
    return round(trailing_stop, 4)


def check_exit_conditions(current_price: float,
                           entry_price: float,
                           stop_loss_pct: float = 5.0,
                           take_profit_pct: float = 15.0,
                           highest_price: float = None) -> dict:
    """
    Check whether a position should be exited based on
    stop loss, trailing stop, or take profit levels.

    Args:
        current_price:    Current market price
        entry_price:      Entry price of the position
        stop_loss_pct:    Stop loss percentage
        take_profit_pct:  Take profit percentage
        highest_price:    Highest price seen since entry
                         If provided trailing stop is used
                         If None fixed stop loss is used

    Returns:
        Dict with should_exit flag, reason, and P&L
    """
    take_profit_price = calculate_take_profit(entry_price, take_profit_pct)
    pnl_pct = ((current_price - entry_price) / entry_price) * 100

    # ── Take Profit ───────────────────────────────────────────────────────────
    if current_price >= take_profit_price:
        return {
            "should_exit": True,
            "reason": "TAKE_PROFIT",
            "pnl_pct": round(pnl_pct, 2),
            "stop_price": None,
            "take_profit_price": take_profit_price
        }

    # ── Trailing Stop Loss ────────────────────────────────────────────────────
    if highest_price is not None:
        trailing_stop = calculate_trailing_stop(current_price,
                                                highest_price,
                                                stop_loss_pct)
        if current_price <= trailing_stop:
            logger.info(f"Trailing stop hit — "
                       f"Price £{current_price:.2f} <= "
                       f"Trail stop £{trailing_stop:.2f} "
                       f"(High was £{highest_price:.2f})")
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

    # ── Fixed Stop Loss ───────────────────────────────────────────────────────
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