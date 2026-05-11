import pandas as pd
import ta
import logging
from signals.base_signal import BaseSignal, SignalResult

logger = logging.getLogger(__name__)


class MomentumSignal(BaseSignal):
    """
    Momentum signal using RSI, MACD, and price vs moving averages.

    Scoring breakdown (total 100 points):
        RSI zone          → up to 30 pts
        MACD crossover    → up to 30 pts
        Price vs MA50     → up to 20 pts
        Price vs MA200    → up to 20 pts

    Direction:
        BUY  → score >= 65
        SELL → score <= 35
        WATCH → everything in between
    """

    def __init__(self):
        super().__init__("Momentum")

    def evaluate(self, ticker: str, df: pd.DataFrame) -> SignalResult:
        if not self._validate_df(df, min_rows=50):
            return SignalResult(ticker, "MOMENTUM", "NONE", 0.0, 0.0,
                                notes="Insufficient data")

        try:
            close = df["Close"].squeeze()
            score = 0.0
            notes = []

            # ── RSI (30 pts) ─────────────────────────────────────────────────
            rsi = ta.momentum.RSIIndicator(close=close, window=14).rsi()
            rsi_val = float(rsi.iloc[-1])

            if rsi_val < 35:
                score += 30
                notes.append(f"RSI oversold ({rsi_val:.1f})")
            elif rsi_val < 50:
                score += 20
                notes.append(f"RSI bullish zone ({rsi_val:.1f})")
            elif rsi_val < 60:
                score += 10
                notes.append(f"RSI neutral ({rsi_val:.1f})")
            elif rsi_val > 75:
                score += 0
                notes.append(f"RSI overbought ({rsi_val:.1f})")
            else:
                score += 5
                notes.append(f"RSI ({rsi_val:.1f})")

            # ── MACD (30 pts) ─────────────────────────────────────────────────
            macd_indicator = ta.trend.MACD(close=close)
            macd_line = macd_indicator.macd().squeeze()
            signal_line = macd_indicator.macd_signal().squeeze()

            macd_val = float(macd_line.iloc[-1])
            signal_val = float(signal_line.iloc[-1])
            macd_prev = float(macd_line.iloc[-2])
            signal_prev = float(signal_line.iloc[-2])

            bullish_cross = macd_prev < signal_prev and macd_val > signal_val
            bearish_cross = macd_prev > signal_prev and macd_val < signal_val

            if bullish_cross:
                score += 30
                notes.append("MACD bullish crossover")
            elif macd_val > signal_val:
                score += 20
                notes.append("MACD above signal")
            elif bearish_cross:
                score += 0
                notes.append("MACD bearish crossover")
            else:
                score += 5
                notes.append("MACD below signal")

            # ── Price vs MA50 (20 pts) ────────────────────────────────────────
            ma50 = close.rolling(window=50).mean()
            ma50_val = float(ma50.iloc[-1])
            current_price = float(close.iloc[-1])

            if current_price > ma50_val:
                score += 20
                notes.append(f"Above MA50 ({ma50_val:.2f})")
            else:
                score += 0
                notes.append(f"Below MA50 ({ma50_val:.2f})")

            # ── Price vs MA200 (20 pts) ───────────────────────────────────────
            if len(close) >= 200:
                ma200 = close.rolling(window=200).mean()
                ma200_val = float(ma200.iloc[-1])
                if current_price > ma200_val:
                    score += 20
                    notes.append(f"Above MA200 ({ma200_val:.2f})")
                else:
                    score += 0
                    notes.append(f"Below MA200 ({ma200_val:.2f})")
            else:
                score += 10
                notes.append("MA200 unavailable - neutral")

                # ── Volume Filter (10 pts) ────────────────────────────────────────
            volume = df["Volume"].squeeze()
            avg_volume = float(volume.rolling(20).mean().iloc[-1])
            latest_volume = float(volume.iloc[-1])

            if avg_volume > 0:
                volume_ratio = latest_volume / avg_volume
                if volume_ratio >= 1.5:
                    score += 10
                    notes.append(f"High volume ({volume_ratio:.1f}x avg)")
                elif volume_ratio >= 1.0:
                    score += 5
                    notes.append(f"Normal volume ({volume_ratio:.1f}x avg)")
                else:
                    score -= 5
                    notes.append(f"Low volume ({volume_ratio:.1f}x avg)")

            # ── Direction ─────────────────────────────────────────────────────
            if score >= 65:
                direction = "BUY"
            elif score <= 35:
                direction = "SELL"
            else:
                direction = "WATCH"

            return SignalResult(
                ticker=ticker,
                signal_type="MOMENTUM",
                direction=direction,
                confidence=score,
                price=current_price,
                notes=" | ".join(notes)
            )

        except Exception as e:
            self.logger.error(f"Momentum evaluation failed for {ticker}: {e}")
            return SignalResult(ticker, "MOMENTUM", "NONE", 0.0, 0.0, notes=str(e))