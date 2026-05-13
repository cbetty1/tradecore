import pandas as pd
import ta
import logging
from signals.base_signal import BaseSignal, SignalResult

logger = logging.getLogger(__name__)


class BreakoutSignal(BaseSignal):
    """
    Breakout signal — detects stocks breaking out of consolidation ranges
    on high volume.

    Catches explosive moves that momentum and mean reversion miss:
    - Momentum sees the trend AFTER it's established
    - Mean reversion catches BOUNCES from oversold
    - Breakout catches the INITIAL SURGE out of a tight range

    Scoring breakdown (total 100 points):
        Price vs resistance (20-day high)  → up to 30 pts
        Volume surge                       → up to 30 pts
        Bollinger Band squeeze             → up to 20 pts
        ADX trend strength                 → up to 20 pts

    Direction:
        BUY  → Bullish breakout above resistance on volume
        SELL → Bearish breakdown below support on volume
        WATCH → No clear breakout
    """

    def __init__(self):
        super().__init__("Breakout")

    def evaluate(self, ticker: str, df: pd.DataFrame) -> SignalResult:
        if not self._validate_df(df, min_rows=50):
            return SignalResult(ticker, "BREAKOUT", "NONE", 0.0, 0.0,
                                notes="Insufficient data")

        try:
            close = df["Close"].squeeze()
            high = df["High"].squeeze()
            low = df["Low"].squeeze()
            volume = df["Volume"].squeeze()
            current_price = float(close.iloc[-1])

            buy_score = 0.0
            sell_score = 0.0
            notes = []

            # ── Price vs 20-Day High/Low (30 pts) ────────────────────────────
            high_20 = float(high.rolling(window=20).max().iloc[-2])  # yesterday's 20d high
            low_20 = float(low.rolling(window=20).min().iloc[-2])    # yesterday's 20d low
            prev_close = float(close.iloc[-2])

            # Bullish breakout — price closing above 20-day high
            if current_price > high_20:
                pct_above = ((current_price - high_20) / high_20) * 100
                if pct_above >= 3.0:
                    buy_score += 30
                    notes.append(f"Strong breakout {pct_above:.1f}% above 20d high")
                elif pct_above >= 1.0:
                    buy_score += 20
                    notes.append(f"Breakout {pct_above:.1f}% above 20d high")
                else:
                    buy_score += 10
                    notes.append(f"Testing 20d high (+{pct_above:.1f}%)")

            # Bearish breakdown — price closing below 20-day low
            elif current_price < low_20:
                pct_below = ((low_20 - current_price) / low_20) * 100
                if pct_below >= 3.0:
                    sell_score += 30
                    notes.append(f"Strong breakdown {pct_below:.1f}% below 20d low")
                elif pct_below >= 1.0:
                    sell_score += 20
                    notes.append(f"Breakdown {pct_below:.1f}% below 20d low")
                else:
                    sell_score += 10
                    notes.append(f"Testing 20d low (-{pct_below:.1f}%)")
            else:
                notes.append("Within 20d range — no breakout")

            # ── Volume Surge (30 pts) ─────────────────────────────────────────
            avg_volume = float(volume.rolling(window=20).mean().iloc[-1])
            latest_volume = float(volume.iloc[-1])

            if avg_volume > 0:
                volume_ratio = latest_volume / avg_volume

                if volume_ratio >= 2.5:
                    vol_pts = 30
                    notes.append(f"Massive volume surge ({volume_ratio:.1f}x avg)")
                elif volume_ratio >= 1.8:
                    vol_pts = 20
                    notes.append(f"Strong volume ({volume_ratio:.1f}x avg)")
                elif volume_ratio >= 1.3:
                    vol_pts = 10
                    notes.append(f"Above avg volume ({volume_ratio:.1f}x avg)")
                elif volume_ratio < 0.7:
                    vol_pts = -10
                    notes.append(f"Low volume — false breakout risk ({volume_ratio:.1f}x avg)")
                else:
                    vol_pts = 0
                    notes.append(f"Normal volume ({volume_ratio:.1f}x avg)")

                # Volume confirms whichever direction is leading
                if buy_score > sell_score:
                    buy_score += max(vol_pts, 0)
                    sell_score += min(vol_pts, 0)
                elif sell_score > buy_score:
                    sell_score += max(vol_pts, 0)
                    buy_score += min(vol_pts, 0)
            else:
                notes.append("Volume data unavailable")

            # ── Bollinger Band Squeeze (20 pts) ──────────────────────────────
            # Tight bands = consolidation, breakout from tight bands is stronger
            bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
            bb_upper = bb.bollinger_hband()
            bb_lower = bb.bollinger_lband()
            bb_width = ((bb_upper - bb_lower) / close).squeeze()

            current_width = float(bb_width.iloc[-1])
            avg_width = float(bb_width.rolling(window=50).mean().iloc[-1])

            if avg_width > 0:
                squeeze_ratio = current_width / avg_width

                if squeeze_ratio <= 0.5:
                    squeeze_pts = 20
                    notes.append(f"Tight BB squeeze ({squeeze_ratio:.2f}x avg width)")
                elif squeeze_ratio <= 0.75:
                    squeeze_pts = 15
                    notes.append(f"Moderate BB squeeze ({squeeze_ratio:.2f}x avg width)")
                elif squeeze_ratio <= 1.0:
                    squeeze_pts = 10
                    notes.append(f"Slightly compressed BBs ({squeeze_ratio:.2f}x avg width)")
                else:
                    squeeze_pts = 0
                    notes.append(f"Wide BBs — already expanded ({squeeze_ratio:.2f}x avg width)")

                buy_score += squeeze_pts
                sell_score += squeeze_pts
            else:
                notes.append("BB width unavailable")

            # ── ADX Trend Strength (20 pts) ──────────────────────────────────
            # ADX rising = breakout has momentum behind it
            adx_indicator = ta.trend.ADXIndicator(
                high=high, low=low, close=close, window=14
            )
            adx_val = float(adx_indicator.adx().iloc[-1])
            adx_prev = float(adx_indicator.adx().iloc[-5])  # 5 days ago
            adx_rising = adx_val > adx_prev

            if adx_val >= 25 and adx_rising:
                adx_pts = 20
                notes.append(f"ADX strong and rising ({adx_val:.1f})")
            elif adx_val >= 20 and adx_rising:
                adx_pts = 15
                notes.append(f"ADX building ({adx_val:.1f})")
            elif adx_rising:
                adx_pts = 10
                notes.append(f"ADX rising from low base ({adx_val:.1f})")
            elif adx_val < 15:
                adx_pts = 5
                notes.append(f"ADX weak — range-bound ({adx_val:.1f})")
            else:
                adx_pts = 0
                notes.append(f"ADX flat/declining ({adx_val:.1f})")

            buy_score += adx_pts
            sell_score += adx_pts

            # ── Final Direction ───────────────────────────────────────────────
            if buy_score >= 65 and buy_score > sell_score:
                direction = "BUY"
                final_score = min(buy_score, 100.0)
            elif sell_score >= 65 and sell_score > buy_score:
                direction = "SELL"
                final_score = min(sell_score, 100.0)
            elif max(buy_score, sell_score) <= 35:
                direction = "WATCH"
                final_score = max(buy_score, sell_score)
            else:
                direction = "WATCH"
                final_score = max(buy_score, sell_score)

            return SignalResult(
                ticker=ticker,
                signal_type="BREAKOUT",
                direction=direction,
                confidence=final_score,
                price=current_price,
                notes=" | ".join(notes)
            )

        except Exception as e:
            self.logger.error(f"Breakout evaluation failed for {ticker}: {e}")
            return SignalResult(ticker, "BREAKOUT", "NONE", 0.0, 0.0,
                                notes=str(e))