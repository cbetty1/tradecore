import sys

path = "execution/order_manager.py"
with open(path, "r") as f:
    content = f.read()

old = '''        open_db_trades = get_open_trades(paper=0)
        if any(row["ticker"] == ticker for row in open_db_trades):
                    logger.info(f"Skipping {ticker} — open trade already exists in DB")
                    continue'''

new = '''        open_db_trades_live = get_open_trades(paper=0)
        open_db_trades_paper = get_open_trades(paper=1)
        if any(row["ticker"] == ticker for row in open_db_trades_live) or \\\\
           any(row["ticker"] == ticker for row in open_db_trades_paper):
                    logger.info(f"Skipping {ticker} — open trade already exists in DB")
                    continue'''

if old not in content:
    print("ERROR: old block not found — aborting, no changes made")
    sys.exit(1)

content = content.replace(old, new, 1)
with open(path, "w") as f:
    f.write(content)
print("Patched successfully")
