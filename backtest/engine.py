import logging
import pandas as pd
from datetime import datetime
from data.price_feed import get_historical_data
from signals.momentum import MomentumSignal
from signals.confidence_scorer import score_signal
from config.settings import DEFAULT_CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)


class BacktestEngine:
    """
    Simulates trading signals against historical price data.
    Tracks every trade, P&L, and portfolio value over time.
    """

    def __init__(self, starting_capital: float = 10000.0,
                 confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
                 stop_loss_pct: float = 5.0,
                 take_profit_pct: float = 15.0,
                 paper: bool = True):

        self.starting_capital = starting_capital
        self.confidence_threshold = confidence_threshold
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.paper = paper
        self.signal = MomentumSignal()

    def run(self, ticker: str, period: str = "2y") -> dict:
        """
        Run a full backtest for a single ticker.

        Args:
            ticker: Stock ticker e.g. 'NVDA'
            period: Lookback period e.g. '1y', '2y'

        Returns:
            Dict containing all trades and performance metrics
        """
        logger.info(f"Starting backtest for {ticker} | period={period}")

        df = get_historical_data(ticker, period=period, interval="1d")
        if df is None or df.empty:
            logger.error(f"No data for {ticker}")
            return {}

        cash = self.starting_capital
        position = 0.0        # Number of shares held
        entry_price = 0.0
        trades = []
        equity_curve = []

        # Walk forward through each trading day
        for i in range(50, len(df)):
            window = df.iloc[:i].copy()
            current_price = float(df["Close"].squeeze().iloc[i])
            date = str(df.index[i].date())

            # Evaluate signal on current window
            raw = self.signal.evaluate(ticker, window)

            # Skip scoring on backtest to avoid live API calls for every bar
            # Use raw momentum score only for speed
            confidence = raw.confidence
            direction = raw.direction

            portfolio_value = cash + (position * current_price)
            equity_curve.append({
                "date": date,
                "portfolio_value": round(portfolio_value, 2),
                "cash": round(cash, 2),
                "position_value": round(position * current_price, 2)
            })

            # ── Entry Logic ───────────────────────────────────────────────────
            if direction == "BUY" and confidence >= self.confidence_threshold and position == 0:
                # Invest 95% of available cash
                invest_amount = cash * 0.95
                shares = invest_amount / current_price
                position = shares
                entry_price = current_price
                cash -= invest_amount

                trades.append({
                    "type": "BUY",
                    "date": date,
                    "price": current_price,
                    "shares": round(shares, 4),
                    "value": round(invest_amount, 2),
                    "confidence": confidence
                })
                logger.debug(f"BUY {ticker} @ {current_price:.2f} | Conf={confidence:.1f}%")

            # ── Exit Logic ────────────────────────────────────────────────────
            elif position > 0:
                pnl_pct = ((current_price - entry_price) / entry_price) * 100

                hit_take_profit = pnl_pct >= self.take_profit_pct
                hit_stop_loss = pnl_pct <= -self.stop_loss_pct
                sell_signal = direction == "SELL" and confidence >= self.confidence_threshold

                if hit_take_profit or hit_stop_loss or sell_signal:
                    sell_value = position * current_price
                    pnl = sell_value - (position * entry_price)
                    cash += sell_value

                    exit_reason = ("TAKE_PROFIT" if hit_take_profit
                                   else "STOP_LOSS" if hit_stop_loss
                                   else "SELL_SIGNAL")

                    trades.append({
                        "type": "SELL",
                        "date": date,
                        "price": current_price,
                        "shares": round(position, 4),
                        "value": round(sell_value, 2),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 2),
                        "exit_reason": exit_reason,
                        "confidence": confidence
                    })

                    logger.debug(f"SELL {ticker} @ {current_price:.2f} | "
                                 f"P&L={pnl:.2f} ({pnl_pct:.1f}%) | {exit_reason}")
                    position = 0.0
                    entry_price = 0.0

        # Close any open position at end of backtest
        if position > 0:
            final_price = float(df["Close"].squeeze().iloc[-1])
            sell_value = position * final_price
            pnl = sell_value - (position * entry_price)
            cash += sell_value
            trades.append({
                "type": "SELL",
                "date": str(df.index[-1].date()),
                "price": final_price,
                "shares": round(position, 4),
                "value": round(sell_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(((final_price - entry_price) / entry_price) * 100, 2),
                "exit_reason": "END_OF_BACKTEST",
                "confidence": 0.0
            })

        final_value = cash
        return {
            "ticker": ticker,
            "period": period,
            "starting_capital": self.starting_capital,
            "final_value": round(final_value, 2),
            "trades": trades,
            "equity_curve": equity_curve
        }