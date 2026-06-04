import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from signals.base_signal import BaseSignal, SignalResult

logger = logging.getLogger(__name__)

class EarningsDriftSignal(BaseSignal):
    """
    Post-earnings announcement drift (PEAD) signal.
    Fires the morning AFTER earnings when a significant gap + volume confirms
    the market is repricing. Catches the multi-day continuation drift.
    """

    def evaluate(self, ticker: str, df: pd.DataFrame, earnings_date: str = None) -> SignalResult:
        try:
            if df is None or len(df) < 30:
                return self._none(ticker, "Insufficient data")

            # We need at least yesterday and today
            if len(df) < 2:
                return self._none(ticker, "Not enough price history")

            today = df.iloc[-1]
            yesterday = df.iloc[-2]
            prior_close = yesterday["Close"]
            today_open = today["Open"]
            today_close = today["Close"]
            today_volume = today["Volume"]

            # --- Gap calculation (using today open vs yesterday close) ---
            gap_pct = ((today_open - prior_close) / prior_close) * 100

            # --- Volume confirmation ---
            avg_volume_20d = df["Volume"].iloc[-21:-1].mean()
            volume_ratio = today_volume / avg_volume_20d if avg_volume_20d > 0 else 1.0

            # --- Price held (didn't reverse hard after open) ---
            # If gap up, we want close to hold above prior close
            # If gap down, we want close to hold below prior close
            held_gap = False
            if gap_pct > 0:
                held_gap = today_close > prior_close * 1.01  # closed at least 1% above prior close
            elif gap_pct < 0:
                held_gap = today_close < prior_close * 0.99  # closed at least 1% below prior close

            # --- Momentum continuation (close near high of day) ---
            day_range = today["High"] - today["Low"]
            if day_range > 0:
                close_position = (today_close - today["Low"]) / day_range  # 0=low, 1=high
            else:
                close_position = 0.5

            # --- Score it ---
            score = 0.0
            notes = []

            # Gap size (max 40 points)
            abs_gap = abs(gap_pct)
            if abs_gap >= 8:
                score += 40
                notes.append(f"Large gap {gap_pct:+.1f}%")
            elif abs_gap >= 5:
                score += 30
                notes.append(f"Significant gap {gap_pct:+.1f}%")
            elif abs_gap >= 3:
                score += 20
                notes.append(f"Moderate gap {gap_pct:+.1f}%")
            elif abs_gap >= 1.5:
                score += 10
                notes.append(f"Small gap {gap_pct:+.1f}%")
            else:
                notes.append(f"Gap too small {gap_pct:+.1f}%")

            # Volume confirmation (max 30 points)
            if volume_ratio >= 3.0:
                score += 30
                notes.append(f"Massive volume ({volume_ratio:.1f}x avg)")
            elif volume_ratio >= 2.0:
                score += 22
                notes.append(f"High volume ({volume_ratio:.1f}x avg)")
            elif volume_ratio >= 1.5:
                score += 15
                notes.append(f"Above avg volume ({volume_ratio:.1f}x avg)")
            else:
                score += 5
                notes.append(f"Weak volume ({volume_ratio:.1f}x avg)")

            # Gap held (max 20 points)
            if held_gap:
                score += 20
                notes.append("Gap held into close")
            else:
                notes.append("Gap faded — caution")

            # Close position in day range (max 10 points)
            if close_position >= 0.7:
                score += 10
                notes.append("Closed near high of day")
            elif close_position >= 0.4:
                score += 5
                notes.append("Closed mid-range")
            else:
                notes.append("Closed near low — weak")

            # Determine direction
            if gap_pct > 0:
                direction = "BUY"
            elif gap_pct < -3 and score >= 60:
                # Strong down gap — could short but we don't, just flag SELL for existing positions
                direction = "SELL"
            else:
                direction = "WATCH"

            # Minimum threshold — needs gap + volume at minimum
            if abs_gap < 1.5 or volume_ratio < 1.5:
                direction = "NONE"
                score = 0

            return SignalResult(
                ticker=ticker,
                signal_type="EARNINGS_DRIFT",
                direction=direction,
                confidence=min(score, 100.0),
                price=float(today_close),
                notes=" | ".join(notes)
            )

        except Exception as e:
            logger.error(f"EarningsDriftSignal error for {ticker}: {e}")
            return self._none(ticker, f"Error: {e}")

    def _none(self, ticker: str, reason: str) -> SignalResult:
        return SignalResult(
            ticker=ticker,
            signal_type="EARNINGS_DRIFT",
            direction="NONE",
            confidence=0.0,
            price=0.0,
            notes=reason
        )