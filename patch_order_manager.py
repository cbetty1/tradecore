import sys

path = "execution/order_manager.py"

with open(path, "r") as f:
    content = f.read()

old = '''        cash -= size["invest_amount"]
        state["cash"] = cash
        state["positions"][ticker] = {
            "shares": size["shares"],
            "entry_price": current_price,
            "highest_price": current_price,
            "trade_id": trade_id,
            "invested": size["invest_amount"],
            "source": "EdgeScanner" if is_edge else "TradeCore",
            "entry_date": str(datetime.now().date())
        }
        open_tickers.append(ticker)

        actions.append({
            "action": "BUY",
            "ticker": ticker,
            "price": current_price,
            "shares": size["shares"],
            "invest_amount": size["invest_amount"],
            "confidence": final_signal.confidence
        })
        logger.info(f"BUY {ticker} [{mode_label}] | £{size['invest_amount']:.2f} | {size['shares']} shares @ £{current_price:.2f} | {'EDGE' if is_edge else 'TC'}")'''

new = '''        # FIX: only touch live cash/positions for genuinely live trades.
        # Paper-forced tickers (e.g. MOMENTUM blocked from live) must not drain live cash.
        if not paper:
            cash -= size["invest_amount"]
            state["cash"] = cash
            state["positions"][ticker] = {
                "shares": size["shares"],
                "entry_price": current_price,
                "highest_price": current_price,
                "trade_id": trade_id,
                "invested": size["invest_amount"],
                "source": "EdgeScanner" if is_edge else "TradeCore",
                "entry_date": str(datetime.now().date())
            }
            open_tickers.append(ticker)

        actions.append({
            "action": "BUY",
            "ticker": ticker,
            "price": current_price,
            "shares": size["shares"],
            "invest_amount": size["invest_amount"],
            "confidence": final_signal.confidence
        })
        logger.info(f"BUY {ticker} [{'PAPER' if paper else mode_label}] | £{size['invest_amount']:.2f} | {size['shares']} shares @ £{current_price:.2f} | {'EDGE' if is_edge else 'TC'}")'''

if old not in content:
    print("ERROR: old block not found — aborting, no changes made")
else:
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched successfully")
