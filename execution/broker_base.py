from abc import ABC, abstractmethod


class BrokerBase(ABC):
    """
    Abstract base class for all broker integrations.
    Every broker must implement these methods.
    """

    @abstractmethod
    def get_account_balance(self) -> dict:
        """Return current cash balance and portfolio value."""
        pass

    @abstractmethod
    def get_open_positions(self) -> list:
        """Return list of currently open positions."""
        pass

    @abstractmethod
    def place_buy_order(self, ticker: str, amount: float) -> dict:
        """Place a buy order for a given cash amount."""
        pass

    @abstractmethod
    def place_sell_order(self, ticker: str, shares: float) -> dict:
        """Place a sell order for a given number of shares."""
        pass

    @abstractmethod
    def get_latest_price(self, ticker: str) -> float:
        """Get the latest price for a ticker."""
        pass