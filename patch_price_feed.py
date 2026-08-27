import re

path = "data/price_feed.py"
with open(path, "r") as f:
    content = f.read()

old = '''        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        raw_price = float(df["Close"].iloc[-1])
        return _to_gbp(raw_price, ticker)'''

new = '''        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Reject stale/flat data: a row with zero volume is not a real trade
        latest_volume = float(df["Volume"].iloc[-1])
        if latest_volume == 0:
            logger.warning(f"Rejected stale price for {ticker}: Volume=0")
            return None

        raw_price = float(df["Close"].iloc[-1])
        return _to_gbp(raw_price, ticker)'''

if old not in content:
    print("ERROR: old block not found — file may have changed, aborting")
else:
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched successfully")
