import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Broker ───────────────────────────────────────────────────────────────────
T212_API_KEY = os.getenv("T212_API_KEY", "")
T212_BASE_URL = os.getenv("T212_BASE_URL", "https://live.trading212.com")

# ── Database ─────────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "tradecore.db")

# ── Data Cache ───────────────────────────────────────────────────────────────
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache")

# ── Trading Parameters ────────────────────────────────────────────────────────
TRADING_CURRENCY = "GBP"
CASH_FLOOR = 20.0             # Minimum trade size in GBP
MAX_POSITION_SIZE = 0.15      # Max 15% of portfolio in one position
DEFAULT_CONFIDENCE_THRESHOLD = 65.0  # Minimum confidence % to act on signal

# ── Market Schedule (London time) ────────────────────────────────────────────
MARKET_OPEN = "08:00"
MARKET_CLOSE = "16:30"
PRE_MARKET_SCAN = "07:00"
AFTERNOON_SCAN = "16:00"
POST_MARKET_REPORT = "17:00"
1
# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

CORRELATION_LIMIT = 0.85

CASH_DEPLOYMENT_THRESHOLD_PCT = 40.0
CASH_DEPLOYMENT_MIN_CONFIDENCE = 80.0

MAX_POSITION_SIZE = 0.15      # Max 15% of portfolio in one position
MAX_OPEN_POSITIONS = 8        # Max number of concurrent open positions