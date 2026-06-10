import logging
from datetime import date
from config.settings import DB_PATH
from database.db import get_connection

logger = logging.getLogger(__name__)

# Minimum plausible portfolio value — below this, assume bad price data
MIN_PLAUSIBLE_VALUE = 300.0


def get_current_drawdown(starting_capital: float) -> float:
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

        if current < MIN_PLAUSIBLE_VALUE:
            logger.warning(f"Drawdown skipped — value £{current:.2f} looks like bad price data")
            return 0.0

        if current >= starting_capital:
            return 0.0

        drawdown = ((starting_capital - current) / starting_capital) * 100
        return round(drawdown, 2)

    except Exception as e:
        logger.error(f"Drawdown calculation failed: {e}")
        return 0.0


def is_kill_switch_active(max_drawdown_pct: float = 8.0,
                           daily_loss_pct: float = 3.0,
                           starting_capital: float = 10000.0) -> dict:
    try:
        with get_connection() as conn:
            snapshots = conn.execute(
                "SELECT * FROM portfolio_snapshots WHERE paper = 0 ORDER BY snapshot_date DESC LIMIT 2"
            ).fetchall()

        if len(snapshots) < 2:
            return {"active": False, "reason": "Insufficient history"}

        current_value = snapshots[0]["total_value"]
        previous_value = snapshots[1]["total_value"]

        if current_value < MIN_PLAUSIBLE_VALUE:
            logger.warning(f"Kill switch skipped — current value £{current_value:.2f} looks like bad price data")
            return {"active": False, "reason": "Bad snapshot detected — skipped"}

        today_str = str(date.today())

        with get_connection() as conn:
            today_snapshots = conn.execute(
                "SELECT total_value FROM portfolio_snapshots "
                "WHERE paper = 0 AND snapshot_date = ? ORDER BY recorded_at ASC",
                (today_str,)
            ).fetchall()

        if today_snapshots and len(today_snapshots) > 0:
            opening_value = today_snapshots[0]["total_value"]
            if opening_value < MIN_PLAUSIBLE_VALUE:
                opening_value = previous_value
                logger.warning(f"Opening snapshot invalid (£{today_snapshots[0]['total_value']:.2f}) — using previous close £{previous_value:.2f}")
            logger.debug(f"Daily loss baseline: today's opening £{opening_value:.2f}")
        else:
            opening_value = previous_value
            logger.debug(f"Daily loss baseline: yesterday's close £{opening_value:.2f} (fallback)")

        daily_loss_pct_actual = ((opening_value - current_value) / opening_value) * 100

        if daily_loss_pct_actual >= daily_loss_pct:
            reason = f"Daily loss limit hit: {daily_loss_pct_actual:.2f}% >= {daily_loss_pct}%"
            logger.critical(f"KILL SWITCH ACTIVE — {reason}")
            return {"active": True, "reason": reason}

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