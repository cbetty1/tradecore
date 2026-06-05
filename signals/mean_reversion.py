import pandas as pd
import ta
import logging
from signals.base_signal import BaseSignal, SignalResult

logger = logging.getLogger(__name__)


class MeanReversionSignal(BaseSignal):
    """
    Mean reversion signal using Bollinger Bands and RSI extremes.

    Looks for oversold stocks that are likely to bounce back.

    Scoring breakdown (total 100 points):
        Bollinger Band position  → up to 40 pts
        RSI extreme              → up to 30 pts
        Price vs MA20            → up to 30 pts

    Direction:
        BUY  → Oversold — likely to bounce up
        SELL → Overbought — likely to pull back
        WATCH → Neutral
    """

    def __init__(self):
        super().__init__("MeanReversion")

    def evaluate(self, ticker: str, df: pd.DataFrame) -> SignalResult:
        if not self._validate_df(df, min_rows=30):
            return SignalResult(ticker, "MEAN_REVERSION", "NONE", 0.0, 0.0,
                                notes="Insufficient data")

        try:    
            close = df["Close"].squeeze()
            score = 0.0
            notes = []

            # ── ATR volatility filter ─────────────────────────────────────────
            atr = ta.volatility.AverageTrueRange(
                high=df["High"].squeeze(),
                low=df["Low"].squeeze(),
                close=close,
                window=14
            ).average_true_range()
            atr_pct = float(atr.iloc[-1]) / float(close.iloc[-1]) * 100
            if atr_pct > 3.5:
                return SignalResult(ticker, "MEAN_REVERSION", "NONE", 0.0,
                                    float(close.iloc[-1]),
                                    notes=f"Skipped — too volatile for mean reversion (ATR {atr_pct:.1f}%)")

            # ── Bollinger Bands (40 pts) ──────────────────────────────────────

            bb = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
            bb_upper = float(bb.bollinger_hband().iloc[-1])
            bb_lower = float(bb.bollinger_lband().iloc[-1])
            bb_mid = float(bb.bollinger_mavg().iloc[-1])
            current_price = float(close.iloc[-1])

            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                bb_position = (current_price - bb_lower) / bb_range
            else:
                bb_position = 0.5

            if bb_position <= 0.1:
                score += 40
                notes.append(f"At lower BB — strong oversold ({bb_position:.2f})")
            elif bb_position <= 0.25:
                score += 30
                notes.append(f"Near lower BB — oversold ({bb_position:.2f})")
            elif bb_position <= 0.4:
                score += 15
                notes.append(f"Below BB midline ({bb_position:.2f})")
            elif bb_position >= 0.9:
                score += 0
                notes.append(f"At upper BB — overbought ({bb_position:.2f})")
            elif bb_position >= 0.75:
                score += 5
                notes.append(f"Near upper BB ({bb_position:.2f})")
            else:
                score += 10
                notes.append(f"BB neutral ({bb_position:.2f})")

            # ── RSI Extreme (30 pts) ──────────────────────────────────────────
            rsi = ta.momentum.RSIIndicator(close=close, window=14).rsi()
            rsi_val = float(rsi.iloc[-1])

            if rsi_val < 25:
                score += 30
                notes.append(f"RSI extremely oversold ({rsi_val:.1f})")
            elif rsi_val < 35:
                score += 20
                notes.append(f"RSI oversold ({rsi_val:.1f})")
            elif rsi_val < 45:
                score += 10
                notes.append(f"RSI below midline ({rsi_val:.1f})")
            elif rsi_val > 75:
                score += 0
                notes.append(f"RSI overbought ({rsi_val:.1f})")
            else:
                score += 5
                notes.append(f"RSI neutral ({rsi_val:.1f})")

            # ── Price vs MA20 (30 pts) ────────────────────────────────────────
            ma20 = close.rolling(window=20).mean()
            ma20_val = float(ma20.iloc[-1])
            deviation = ((current_price - ma20_val) / ma20_val) * 100

            if deviation <= -5:
                score += 30
                notes.append(f"5%+ below MA20 — strong reversion candidate")
            elif deviation <= -2:
                score += 20
                notes.append(f"Below MA20 by {abs(deviation):.1f}%")
            elif deviation <= 0:
                score += 10
                notes.append(f"Slightly below MA20")
            elif deviation >= 5:
                score += 0
                notes.append(f"5%+ above MA20 — overbought")
            else:
                score += 5
                notes.append(f"Above MA20 by {deviation:.1f}%")

            # ── Direction ─────────────────────────────────────────────────────
            if score >= 65:
                direction = "BUY"
            elif score <= 35:
                direction = "SELL"
            else:
                direction = "WATCH"

            return SignalResult(
                ticker=ticker,
                signal_type="MEAN_REVERSION",
                direction=direction,
                confidence=score,
                price=current_price,
                notes=" | ".join(notes)
            )

        except Exception as e:
            self.logger.error(f"Mean reversion evaluation failed for {ticker}: {e}")
            return SignalResult(ticker, "MEAN_REVERSION", "NONE", 0.0, 0.0,
                                notes=str(e))