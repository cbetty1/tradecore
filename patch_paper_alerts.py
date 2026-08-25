import sys

path1 = "execution/order_manager.py"
with open(path1, "r") as f:
    content = f.read()

old1 = '''                    actions.append({
                        "action": "SELL",
                        "ticker": ticker,
                        "price": current_price,
                        "shares": shares,
                        "sell_value": round(sell_value, 2),
                        "pnl": round(pnl, 2),
                        "reason": exit_check["reason"]
                    })'''
new1 = '''                    actions.append({
                        "action": "SELL",
                        "ticker": ticker,
                        "price": current_price,
                        "shares": shares,
                        "sell_value": round(sell_value, 2),
                        "pnl": round(pnl, 2),
                        "reason": exit_check["reason"],
                        "paper": paper
                    })'''

old2 = '''            actions.append({
                "action": "SELL",
                "ticker": ticker,
                "price": current_price,
                "shares": shares,
                "sell_value": round(sell_value, 2),
                "pnl": round(pnl, 2),'''
new2 = '''            actions.append({
                "action": "SELL",
                "ticker": ticker,
                "price": current_price,
                "shares": shares,
                "sell_value": round(sell_value, 2),
                "pnl": round(pnl, 2),
                "paper": paper,'''

old3 = '''        actions.append({
            "action": "BUY",
            "ticker": ticker,
            "price": current_price,
            "shares": size["shares"],
            "invest_amount": size["invest_amount"],
            "confidence": final_signal.confidence
        })'''
new3 = '''        actions.append({
            "action": "BUY",
            "ticker": ticker,
            "price": current_price,
            "shares": size["shares"],
            "invest_amount": size["invest_amount"],
            "confidence": final_signal.confidence,
            "paper": paper
        })'''

for old, new, label in [(old1, new1, "SELL block 1"), (old2, new2, "SELL block 2"), (old3, new3, "BUY block")]:
    if old not in content:
        print(f"ERROR: {label} not found — aborting, no changes made")
        sys.exit(1)
    content = content.replace(old, new, 1)

with open(path1, "w") as f:
    f.write(content)
print("Patched order_manager.py successfully (3 blocks)")
