import logging
from config.settings import DB_PATH
from database.db import get_connection

logger = logging.getLogger(__name__)


def get_current_drawdown(starting_capital: float) -> float:
    """
    Calculate current drawdown from peak portfolio value.

    Returns:
        Current drawdown as a percentage (positive number)
    """
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT total_value FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 30"
            ).fetchall()

        if not rows:
            return 0.0

        values = [r[0] for r in rows]
        peak = max(values)
        current = values[0]

        if peak <= 0:
            return 0.0

        drawdown = ((peak - current) / peak) * 100
        return round(drawdown, 2)

    except Exception as e:
        logger.error(f"Drawdown calculation failed: {e}")
        return 0.0


def is_kill_switch_active(max_drawdown_pct: float = 8.0,
                           daily_loss_pct: float = 3.0,
                           starting_capital: float = 10000.0) -> dict:
    """
    Check whether trading should be halted based on drawdown limits.

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
                "SELECT * FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 2"
            ).fetchall()

        if len(snapshots) < 2:
            return {"active": False, "reason": "Insufficient history"}

        current_value = snapshots[0]["total_value"]
        previous_value = snapshots[1]["total_value"]

        # Sanity check — ignore snapshots where portfolio looks implausibly low
        # This prevents bad price fetches from triggering the kill switch
        if current_value < (starting_capital * 0.5):
            logger.warning(f"Kill switch skipped — current value £{current_value:.2f} "
                          f"looks like a bad price fetch, ignoring.")
            return {"active": False, "reason": "Bad snapshot detected — skipped"}

        # Daily loss check
        daily_loss_pct_actual = ((previous_value - current_value) / previous_value) * 100
        if daily_loss_pct_actual >= daily_loss_pct:
            reason = f"Daily loss limit hit: {daily_loss_pct_actual:.2f}% >= {daily_loss_pct}%"
            logger.critical(f"KILL SWITCH ACTIVE — {reason}")
            return {"active": True, "reason": reason}

        # Max drawdown check
        current_drawdown = get_current_drawdown(starting_capital)
        if current_drawdown >= max_drawdown_pct:
            reason = f"Max drawdown hit: {current_drawdown:.2f}% >= {max_drawdown_pct}%"
            logger.critical(f"KILL SWITCH ACTIVE — {reason}")
            return {"active": True, "reason": reason}

        return {
            "active": False,
            "reason": f"OK | Drawdown={current_drawdown:.2f}%"
        }

    except Exception as e:
        logger.error(f"Kill switch check failed: {e}")
        return {"active": False, "reason": f"Check failed: {e}"}