import logging
from datetime import date
from config.settings import DB_PATH
from database.db import get_connection

logger = logging.getLogger(__name__)


def get_current_drawdown(starting_capital: float) -> float:
    """
    Calculate current drawdown from starting capital.
    Using starting capital as baseline prevents partially-deployed
    portfolios from triggering false drawdown alerts after selling positions.
    Returns:
        Current drawdown as a percentage (positive number)
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT total_value FROM portfolio_snapshots WHERE paper = 0 ORDER BY snapshot_date DESC LIMIT 1"
            ).fetchall()

        if not rows:
            return 0.0

        current = rows[0][0]

        if starting_capital <= 0:
            return 0.0

        if current >= starting_capital:
            return 0.0  # We're above starting capital — no drawdown

        drawdown = ((starting_capital - current) / starting_capital) * 100
        return round(drawdown, 2)

    except Exception as e:
        logger.error(f"Drawdown calculation failed: {e}")
        return 0.0


def is_kill_switch_active(max_drawdown_pct: float = 8.0,
                           daily_loss_pct: float = 3.0,
                           starting_capital: float = 10000.0) -> dict:
    """
    Check whether trading should be halted based on drawdown limits.

    Daily loss is calculated from the FIRST snapshot of today (opening value),
    not yesterday's close. This prevents overnight dips that recover intraday
    from falsely triggering the kill switch.

    Args:
        max_drawdown_pct:  Maximum allowable drawdown before kill switch fires
        daily_loss_pct:    Maximum allowable daily loss before kill switch fires
        starting_capital:  Starting portfolio value

    Returns:
        Dict with active flag and reason
    """
    try:
        with get_connection() as conn:
            snapshots = conn.execute(
                "SELECT * FROM portfolio_snapshots WHERE paper = 0 ORDER BY snapshot_date DESC LIMIT 2"
            ).fetchall()

        if len(snapshots) < 2:
            return {"active": False, "reason": "Insufficient history"}

        current_value = snapshots[0]["total_value"]
        previous_value = snapshots[1]["total_value"]

        # Sanity check — ignore snapshots where portfolio looks implausibly low
        # This prevents bad price fetches from triggering the kill switch
        if current_value < 50:
            logger.warning(f"Kill switch skipped — current value £{current_value:.2f} looks like bad price data")
            return {"active": False, "reason": "Bad snapshot detected — skipped"}
        
        # --- Daily loss check ---
        # Compare against today's OPENING value (first snapshot of today),
        # not yesterday's close. Prevents overnight dips that recover intraday
        # from falsely firing the kill switch.
        today_str = str(date.today())

        with get_connection() as conn:
            today_snapshots = conn.execute(
                "SELECT total_value FROM portfolio_snapshots "
                "WHERE paper = 0 AND snapshot_date = ? ORDER BY recorded_at ASC",
                (today_str,)
            ).fetchall()

        if today_snapshots and len(today_snapshots) > 0:
            opening_value = today_snapshots[0]["total_value"]
            logger.debug(f"Daily loss baseline: today's opening £{opening_value:.2f}")
        else:
            # Fallback to yesterday's close if no snapshot yet today
            opening_value = previous_value
            logger.debug(f"Daily loss baseline: yesterday's close £{opening_value:.2f} (fallback)")

        daily_loss_pct_actual = ((opening_value - current_value) / opening_value) * 100

        if daily_loss_pct_actual >= daily_loss_pct:
            reason = f"Daily loss limit hit: {daily_loss_pct_actual:.2f}% >= {daily_loss_pct}%"
            logger.critical(f"KILL SWITCH ACTIVE — {reason}")
            return {"active": True, "reason": reason}

        # --- Max drawdown check ---
        current_drawdown = get_current_drawdown(starting_capital)
        if current_drawdown >= max_drawdown_pct:
            reason = f"Max drawdown hit: {current_drawdown:.2f}% >= {max_drawdown_pct}%"
            logger.critical(f"KILL SWITCH ACTIVE — {reason}")
            return {"active": True, "reason": reason}

        return {
            "active": False,
            "reason": f"OK | Drawdown={current_drawdown:.2f}% | Daily={daily_loss_pct_actual:.2f}%"
        }

    except Exception as e:
        logger.error(f"Kill switch check failed: {e}")
        return {"active": False, "reason": f"Check failed: {e}"}