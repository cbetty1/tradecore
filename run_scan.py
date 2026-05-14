import logging
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

from execution.order_manager import run_scan

# Market hours check
_now = datetime.now()
_hour = _now.hour
_minute = _now.minute
if not ((8 <= _hour < 16) or (_hour == 16 and _minute <= 30)):
    print(f"\n⚠️  WARNING: Running outside market hours ({_hour:02d}:{_minute:02d})")
    print("   Stop losses may use stale prices.")
    print("   Best to run between 08:00 - 16:30\n")

with open('config/watchlist.json') as f:
    watchlist = json.load(f)['watchlist']

actions = run_scan(watchlist)

print('\n--- ACTIONS TAKEN ---')
for a in actions:
    print(a)