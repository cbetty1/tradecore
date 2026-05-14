import logging
import pandas as pd
import ta
import yfinance as yf
from signals.base_signal import SignalResult

logger = logging.getLogger(__name__)


def get_market_regime() -> str:
    """
    Determine the current market regime based on SPY vs its 200-day MA and VIX level.

    Returns:
        'BULL'    - SPY above MA200, VIX low
        'BEAR'    - SPY below MA200, VIX high
        'CHOPPY'  - Mixed signals
    """
    try:
        spy = yf.download("SPY", period="2y", interval="1d", progress=False, auto_adjust=True)
        vix = yf.download("^VIX", period="5d", interval="1d", progress=False, auto_adjust=True)

        if spy.empty or vix.empty:
            logger.warning("Could not fetch regime data, defaulting to CHOPPY")
            return "CHOPPY"

        spy_close = spy["Close"].squeeze()
        ma200 = spy_close.rolling(200).mean()
        spy_current = float(spy_close.iloc[-1])
        ma200_current = float(ma200.iloc[-1])
        vix_current = float(vix["Close"].squeeze().iloc[-1])

        spy_above_ma200 = spy_current > ma200_current

        if spy_above_ma200 and vix_current < 20:
            regime = "BULL"
        elif not spy_above_ma200 and vix_current > 25:
            regime = "BEAR"
        else:
            regime = "CHOPPY"

        logger.info(f"Market regime: {regime} | SPY={spy_current:.2f} MA200={ma200_current:.2f} VIX={vix_current:.1f}")
        return regime

    except Exception as e:
        logger.error(f"Regime detection failed: {e}")
        return "CHOPPY"


def get_volume_confirmation(df: pd.DataFrame) -> float:
    """
    Check if recent volume confirms the price move.
    Compares latest volume to 20-day average volume.

    Returns:
        Adjustment score between -10.0 and +10.0
    """
    try:
        volume = df["Volume"].squeeze()
        avg_volume = float(volume.rolling(20).mean().iloc[-1])
        latest_volume = float(volume.iloc[-1])

        ratio = latest_volume / avg_volume if avg_volume > 0 else 1.0

        if ratio >= 1.5:
            return 10.0    # Strong volume confirmation
        elif ratio >= 1.1:
            return 5.0     # Moderate confirmation
        elif ratio >= 0.8:
            return 0.0     # Neutral
        else:
            return -10.0   # Low volume — weak signal

    except Exception as e:
        logger.warning(f"Volume confirmation failed: {e}")
        return 0.0


def get_sector_adjustment(ticker: str) -> float:
    """
    Check the relative strength of the ticker's sector ETF.
    Compares sector ETF momentum against SPY.

    Returns:
        Adjustment score between -10.0 and +10.0
    """
    # Map tickers to their sector ETF
    sector_map = {
        "NVDA": "XLK", "AMD": "XLK", "MSFT": "XLK", "AAPL": "XLK",
        "GOOGL": "XLC", "META": "XLC",
        "AMZN": "XLY",
        "PLTR": "XLK",
        "IBM": "XLK",
        "ASML": "XLK",
        "TSLA": "XLY"
    }

    sector_etf = sector_map.get(ticker.upper())
    if not sector_etf:
        return 0.0  # No adjustment for unmapped tickers (ETFs etc.)

    try:
        etf_data = yf.download(sector_etf, period="1mo", interval="1d",
                               progress=False, auto_adjust=True)
        spy_data = yf.download("SPY", period="3mo", interval="1d",
                               progress=False, auto_adjust=True)

        if etf_data.empty or spy_data.empty:
            return 0.0

        etf_return = float(etf_data["Close"].squeeze().pct_change(20).iloc[-1])
        spy_return = float(spy_data["Close"].squeeze().pct_change(20).iloc[-1])

        relative_strength = etf_return - spy_return

        if relative_strength > 0.02:
            return 10.0    # Sector outperforming — boost confidence
        elif relative_strength > 0:
            return 5.0
        elif relative_strength > -0.02:
            return 0.0
        else:
            return -10.0   # Sector underperforming — reduce confidence

    except Exception as e:
        logger.warning(f"Sector adjustment failed for {ticker}: {e}")
        return 0.0


def apply_regime_adjustment(confidence: float, direction: str, regime: str) -> float:
    """
    Adjust confidence based on market regime.

    Bull market  → boost BUY signals, reduce SELL signals
    Bear market  → boost SELL signals, reduce BUY signals
    Choppy       → reduce all signals slightly
    """
    if regime == "BULL":
        if direction == "BUY":
            return min(confidence + 10.0, 100.0)
        elif direction == "SELL":
            return max(confidence - 10.0, 0.0)

    elif regime == "BEAR":
        if direction == "SELL":
            return min(confidence + 10.0, 100.0)
        elif direction == "BUY":
            return max(confidence - 10.0, 0.0)

    elif regime == "CHOPPY":
        return max(confidence - 5.0, 0.0)

    return confidence


def score_signal(result: SignalResult, df: pd.DataFrame) -> SignalResult:
    """
    Apply full confidence scoring pipeline to a raw signal result.

    Pipeline:
        1. Get market regime
        2. Apply regime adjustment
        3. Apply volume confirmation
        4. Apply sector adjustment
        5. Clamp final score to 0-100
        6. Re-evaluate direction based on final score

    Args:
        result: Raw SignalResult from a signal evaluator
        df:     OHLCV DataFrame used to generate the signal

    Returns:
        Updated SignalResult with refined confidence
    """
    if result.direction == "NONE":
        return result

    original_confidence = result.confidence
    notes = result.notes or ""

    # Step 1 — Market regime
    regime = get_market_regime()
    result.regime = regime

    # Step 2 — Regime adjustment
    confidence = apply_regime_adjustment(result.confidence, result.direction, regime)

    # Step 3 — Volume confirmation
    volume_adj = get_volume_confirmation(df)
    confidence += volume_adj

    # Step 4 — Sector adjustment
    sector_adj = get_sector_adjustment(result.ticker)
    confidence += sector_adj

    # Step 5 — Clamp
    confidence = max(0.0, min(confidence, 100.0))

    # Step 6 — Re-evaluate direction
    if confidence >= 65:
        direction = "BUY"
    elif confidence <= 35:
        direction = "SELL"
    else:
        direction = "WATCH"

    result.confidence = round(confidence, 1)
    result.direction = direction
    result.notes = (f"{notes} | Regime={regime} | "
                    f"VolAdj={volume_adj:+.1f} | SectorAdj={sector_adj:+.1f} | "
                    f"Raw={original_confidence:.1f} → Final={confidence:.1f}")

    return result