"""
Test the Hold/Exit Decision Logic
Shows what decision will appear for each trade based on market movement
"""
import json
from pathlib import Path

# Load trades
with open('data/auto_trade_log.json', encoding='utf-8-sig') as f:
    trades = json.load(f)

def analyze_hold_exit(trade):
    """Analyze hold/exit decision"""
    try:
        ep = float(trade.get("entry_price", 0) or 0)
        cur = float(trade.get("current_ltp", ep) or ep)
        pnl = float(trade.get("current_pnl", 0) or 0)
        direction = str(trade.get("direction", "buy")).lower().strip()
        status = str(trade.get("status", "Open")).lower()
        
        if status != "open":
            return "—", "—", "—"
        
        if ep <= 0 or cur <= 0:
            return "⚪", "Hold", "Insufficient data"
        
        # Market movement
        moved_up = cur > ep
        is_profitable = pnl >= 0
        
        # For BUY trades (expecting upside)
        if "buy" in direction or "long" in direction:
            if moved_up and is_profitable:
                return "🟢", "HOLD", "Market up + Profit ✓ Thesis working, stay"
            elif moved_up and not is_profitable:
                return "🟡", "REASSESS", "Market up but Loss ✗ Wrong entry level, consider exit"
            elif not moved_up and is_profitable:
                return "🟢", "HOLD", "Market down yet Profitable ✓ Unusual but good, hold SL"
            else:
                return "🔴", "EXIT", "Market down + Loss ✗ Thesis broken, exit now"
        
        # For SELL trades (expecting downside)
        elif "sell" in direction or "short" in direction:
            if not moved_up and is_profitable:
                return "🟢", "HOLD", "Market down + Profit ✓ Thesis working, stay"
            elif not moved_up and not is_profitable:
                return "🟡", "REASSESS", "Market down but Loss ✗ Wrong entry level, consider exit"
            elif moved_up and is_profitable:
                return "🟢", "HOLD", "Market up yet Profitable ✓ Unusual but good, hold SL"
            else:
                return "🔴", "EXIT", "Market up + Loss ✗ Thesis broken, exit now"
        
        return "⚪", "Hold", "Direction unclear"
        
    except Exception as e:
        return "⚪", "—", f"Error: {str(e)}"

print("\n" + "=" * 150)
print("HOLD / EXIT DECISION ANALYSIS FOR AUTO TRADES")
print("=" * 150 + "\n")

print(f"{'Strategy':<20} {'Direction':<10} {'Entry ₹':<12} {'Current ₹':<12} {'P&L ₹':<12} {'Market':<12} {'Decision':<20} {'Reason':<50}")
print("-" * 150)

for trade in trades:
    if trade.get("status") != "Open":
        continue
    
    strategy = trade.get("strategy_type", "?")
    direction = trade.get("direction", "?").capitalize()
    entry = float(trade.get("entry_price", 0) or 0)
    current = float(trade.get("current_ltp", entry) or entry)
    pnl = float(trade.get("current_pnl", 0) or 0)
    
    # Market direction
    if current > entry:
        market_move = "↑ UP"
    elif current < entry:
        market_move = "↓ DOWN"
    else:
        market_move = "→ FLAT"
    
    icon, decision, reason = analyze_hold_exit(trade)
    
    print(f"{strategy:<20} {direction:<10} ₹{entry:<11.2f} ₹{current:<11.2f} ₹{pnl:<11.2f} {market_move:<12} {icon} {decision:<15} {reason[:48]:<50}")

print("\n" + "=" * 150)
print("DECISION LEGEND:")
print("-" * 150)
print("🟢 HOLD    = Market moved as expected + making profit → thesis is working, stay in trade")
print("🟡 REASSESS = Market moved as expected BUT losing money → entry level was wrong, consider exiting")
print("🔴 EXIT    = Market moved opposite to thesis + losing money → thesis is broken, exit immediately")
print("🟢 HOLD*   = Market moved opposite BUT still profitable → unusual situation, hold with tight stop loss")
print("=" * 150 + "\n")
