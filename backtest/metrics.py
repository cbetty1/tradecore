import logging
import numpy as np

logger = logging.getLogger(__name__)


def calculate_metrics(result: dict) -> dict:
    """
    Calculate performance metrics from a backtest result.

    Args:
        result: Dict returned by BacktestEngine.run()

    Returns:
        Dict of performance metrics
    """
    if not result or not result.get("trades"):
        return {}

    trades = result["trades"]
    equity_curve = result["equity_curve"]
    starting_capital = result["starting_capital"]
    final_value = result["final_value"]

    # ── P&L ──────────────────────────────────────────────────────────────────
    total_return = ((final_value - starting_capital) / starting_capital) * 100

    # ── Trade Analysis ────────────────────────────────────────────────────────
    sell_trades = [t for t in trades if t["type"] == "SELL" and "pnl" in t]
    total_trades = len(sell_trades)

    if total_trades == 0:
        return {"total_return_pct": round(total_return, 2), "total_trades": 0}

    winning_trades = [t for t in sell_trades if t["pnl"] > 0]
    losing_trades = [t for t in sell_trades if t["pnl"] <= 0]

    win_rate = (len(winning_trades) / total_trades) * 100
    avg_win = np.mean([t["pnl"] for t in winning_trades]) if winning_trades else 0
    avg_loss = np.mean([t["pnl"] for t in losing_trades]) if losing_trades else 0

    # ── Reward/Risk Ratio ─────────────────────────────────────────────────────
    reward_risk = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    # ── Max Drawdown ──────────────────────────────────────────────────────────
    portfolio_values = [e["portfolio_value"] for e in equity_curve]
    peak = starting_capital
    max_drawdown = 0.0

    for value in portfolio_values:
        if value > peak:
            peak = value
        drawdown = ((peak - value) / peak) * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    # ── Sharpe Ratio (annualised) ─────────────────────────────────────────────
    daily_values = [e["portfolio_value"] for e in equity_curve]
    daily_returns = []
    for i in range(1, len(daily_values)):
        ret = (daily_values[i] - daily_values[i - 1]) / daily_values[i - 1]
        daily_returns.append(ret)

    if len(daily_returns) > 1:
        avg_return = np.mean(daily_returns)
        std_return = np.std(daily_returns)
        sharpe = (avg_return / std_return * np.sqrt(252)) if std_return > 0 else 0
    else:
        sharpe = 0.0

    return {
        "ticker":             result["ticker"],
        "period":             result["period"],
        "starting_capital":   starting_capital,
        "final_value":        round(final_value, 2),
        "total_return_pct":   round(total_return, 2),
        "total_trades":       total_trades,
        "winning_trades":     len(winning_trades),
        "losing_trades":      len(losing_trades),
        "win_rate_pct":       round(win_rate, 2),
        "avg_win_gbp":        round(avg_win, 2),
        "avg_loss_gbp":       round(avg_loss, 2),
        "reward_risk_ratio":  round(reward_risk, 2),
        "max_drawdown_pct":   round(max_drawdown, 2),
        "sharpe_ratio":       round(sharpe, 2)
    }


def print_metrics(metrics: dict):
    """Print a formatted metrics report to console."""
    if not metrics:
        print("No metrics to display.")
        return

    print("\n" + "=" * 50)
    print(f"  BACKTEST RESULTS — {metrics.get('ticker', 'N/A')}")
    print("=" * 50)
    print(f"  Period:           {metrics.get('period')}")
    print(f"  Starting Capital: £{metrics.get('starting_capital'):,.2f}")
    print(f"  Final Value:      £{metrics.get('final_value'):,.2f}")
    print(f"  Total Return:     {metrics.get('total_return_pct'):+.2f}%")
    print("-" * 50)
    print(f"  Total Trades:     {metrics.get('total_trades')}")
    print(f"  Win Rate:         {metrics.get('win_rate_pct'):.1f}%")
    print(f"  Avg Win:          £{metrics.get('avg_win_gbp'):,.2f}")
    print(f"  Avg Loss:         £{metrics.get('avg_loss_gbp'):,.2f}")
    print(f"  Reward/Risk:      {metrics.get('reward_risk_ratio'):.2f}")
    print("-" * 50)
    print(f"  Max Drawdown:     {metrics.get('max_drawdown_pct'):.2f}%")
    print(f"  Sharpe Ratio:     {metrics.get('sharpe_ratio'):.2f}")
    print("=" * 50 + "\n")