"""
TradeCore — Signal Backtest Comparison
Run all three signals against the same stocks and compare performance.

Usage:
    cd /opt/tradecore/tradecore
    python run_backtest_compare.py
"""

from backtest.engine import BacktestEngine
from backtest.metrics import calculate_metrics
from signals.momentum import MomentumSignal
from signals.mean_reversion import MeanReversionSignal
from signals.breakout import BreakoutSignal


def run_comparison():
    tickers = ["NVDA", "ASML", "TSLA", "AAPL", "AMD"]
    signals = [
        ("Momentum", MomentumSignal()),
        ("Mean Reversion", MeanReversionSignal()),
        ("Breakout", BreakoutSignal()),
    ]

    print("=" * 80)
    print("  TradeCore — Signal Backtest Comparison (2 Year)")
    print("=" * 80)

    for ticker in tickers:
        print(f"\n{'─' * 80}")
        print(f"  {ticker}")
        print(f"{'─' * 80}")
        print(f"  {'Signal':<20} {'Return':>10} {'Trades':>8} {'Win Rate':>10} "
              f"{'Sharpe':>8} {'Max DD':>10} {'R/R':>8}")
        print(f"  {'─' * 18:<20} {'─' * 8:>10} {'─' * 6:>8} {'─' * 8:>10} "
              f"{'─' * 6:>8} {'─' * 8:>10} {'─' * 6:>8}")

        for name, signal in signals:
            engine = BacktestEngine(
                starting_capital=10000,
                signal=signal,
            )
            result = engine.run(ticker, period="2y")

            if not result:
                print(f"  {name:<20} {'NO DATA':>10}")
                continue

            m = calculate_metrics(result)
            total_return = m.get("total_return_pct", 0)
            total_trades = m.get("total_trades", 0)
            win_rate = m.get("win_rate_pct", 0)
            sharpe = m.get("sharpe_ratio", 0)
            max_dd = m.get("max_drawdown_pct", 0)
            rr = m.get("reward_risk_ratio", 0)

            ret_color = "+" if total_return >= 0 else ""

            print(f"  {name:<20} {ret_color}{total_return:>8.2f}% {total_trades:>8} "
                  f"{win_rate:>9.1f}% {sharpe:>8.2f} {max_dd:>9.2f}% {rr:>8.2f}")

    print(f"\n{'=' * 80}")
    print("  Done. Compare results above to decide whether to enable breakout.")
    print("=" * 80)


if __name__ == "__main__":
    run_comparison()