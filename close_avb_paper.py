import json
from database.queries import close_trade

with open('portfolio_state_paper.json') as f:
    state = json.load(f)

if 'AVB' not in state['positions']:
    print("AVB not found in paper positions — nothing to do")
else:
    pos = state['positions']['AVB']
    invested = pos['invested']
    trade_id = pos['trade_id']

    state['cash'] += invested
    del state['positions']['AVB']

    with open('portfolio_state_paper.json', 'w') as f:
        json.dump(state, f, indent=2)

    close_trade(trade_id, 0.0, "MANUAL_VOID_BAD_DATA")

    print(f"Removed AVB paper position. Refunded £{invested:.2f} to cash.")
    print(f"New cash: £{state['cash']:.2f}")
    print(f"Closed trade_id {trade_id} with pnl=0 (reason: MANUAL_VOID_BAD_DATA)")
