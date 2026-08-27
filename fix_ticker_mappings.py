import json
import os
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

TICKERS_FILE = "config/t212_tickers.json"
WATCHLIST_FILE = "config/watchlist_edge.json"
API_KEY = os.getenv("T212_API_KEY")
API_SECRET = os.getenv("T212_API_SECRET")
BASE_URL = os.getenv("T212_BASE_URL", "https://live.trading212.com")

credentials = f"{API_KEY}:{API_SECRET}"
encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
headers = {
    "Authorization": f"Basic {encoded}",
    "Content-Type": "application/json"
}

with open(TICKERS_FILE) as f:
    data = json.load(f)
ticker_map = data["ticker_map"]

with open(WATCHLIST_FILE) as f:
    universe = [e["ticker"] for e in json.load(f)["universe"]]

missing = [t for t in universe if t not in ticker_map]
print(f"Attempting to map {len(missing)} tickers...")

resp = requests.get(
    f"{BASE_URL}/api/v0/equity/metadata/instruments",
    headers=headers
)
resp.raise_for_status()
instruments = resp.json()

t212_by_base = {}
for inst in instruments:
    code = inst.get("ticker", "")
    base = code.split("_")[0]
    t212_by_base[base] = code

matched = 0
unmatched = []
for t in missing:
    if t in t212_by_base:
        ticker_map[t] = t212_by_base[t]
        matched += 1
    else:
        unmatched.append(t)

print(f"Matched: {matched}")
print(f"Unmatched: {len(unmatched)}")
if unmatched:
    print("First 30 unmatched:", unmatched[:30])

os.rename(TICKERS_FILE, TICKERS_FILE + ".bak")
with open(TICKERS_FILE, "w") as f:
    json.dump(data, f, indent=2)
print(f"Saved. Backup at {TICKERS_FILE}.bak")
