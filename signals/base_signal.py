from abc import ABC, abstractmethod
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class SignalResult:
    """Represents the output of a signal evaluation."""

    def __init__(self, ticker: str, signal_type: str, direction: str, confidence: float,
                 price: float, regime: str = None, notes: str = None):
        self.ticker = ticker
        self.signal_type = signal_type
        self.direction = direction      # BUY, SELL, WATCH, NONE
        self.confidence = confidence    # 0.0 - 100.0
        self.price = price
        self.regime = regime
        self.notes = notes

    def is_actionable(self, threshold: float = 65.0) -> bool:
        """Returns True if confidence meets the minimum threshold."""
        return self.direction in ("BUY", "SELL") and self.confidence >= threshold

    def __repr__(self):
        return (f"SignalResult({self.ticker} | {self.direction} | "
                f"Confidence: {self.confidence:.1f}% | Price: {self.price:.2f})")


class BaseSignal(ABC):
    """
    Abstract base class for all TradeCore signals.
    Every signal must implement the evaluate() method.
    """

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"signals.{name}")

    @abstractmethod
    def evaluate(self, ticker: str, df: pd.DataFrame) -> SignalResult:
        """
        Evaluate a signal against price data.

        Args:
            ticker: Stock ticker symbol
            df:     OHLCV DataFrame from price feed

        Returns:
            SignalResult object
        """
        pass

    def _validate_df(self, df: pd.DataFrame, min_rows: int = 50) -> bool:
        """Check DataFrame has enough data to run indicators."""
        if df is None or df.empty:
            self.logger.warning("DataFrame is empty or None.")
            return False
        if len(df) < min_rows:
            self.logger.warning(f"Insufficient data: {len(df)} rows (need {min_rows})")
            return False
        return True
    