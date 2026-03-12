import os
import json
import time
import requests

DB_PATH = "database.json"

def load_db():
    firebase_url = os.getenv("FIREBASE_URL")
    default = {"bankroll": {"balance": 100.0, "initial_balance": 100.0, "currency": "€"}, "history": [], "caches": {}}
    
    if firebase_url:
        try:
            r = requests.get(f"{firebase_url}/db.json", timeout=5)
            if r.status_code == 200 and r.json():
                return r.json()
            else:
                # Initialize Firebase with default if empty
                requests.put(f"{firebase_url}/db.json", json=default)
                return default
        except Exception as e:
            print(f"Firebase connection error: {e}. Falling back to local DB.")
            pass # Fallback to local file if Firebase fails
            
    if not os.path.exists(DB_PATH):
        with open(DB_PATH, "w", encoding="utf-8") as f: 
            json.dump(default, f, ensure_ascii=False)
        return default
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f: 
            return json.load(f)
    except:
        return default

def save_db(data):
    firebase_url = os.getenv("FIREBASE_URL")
    if firebase_url:
        try:
            requests.put(f"{firebase_url}/db.json", json=data, timeout=5)
            return
        except Exception as e:
            print(f"Firebase save error: {e}. Saving to local DB.")
            pass
            
    try:
        with open(DB_PATH, "w", encoding="utf-8") as f: 
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Local save error: {e}")

def get_cache(key, ttl=3600):
    """
    Retrieves data from the persistent cache if it's not expired.
    Default TTL is 1 hour (3600s).
    """
    db = load_db()
    caches = db.get("caches", {})
    entry = caches.get(key)
    
    if entry:
        ts = entry.get("timestamp", 0)
        if (time.time() - ts) < ttl:
            return entry.get("data")
    return None

def set_cache(key, data):
    """
    Persists data in the cloud cache.
    """
    db = load_db()
    if "caches" not in db:
        db["caches"] = {}
        
    db["caches"][key] = {
        "timestamp": time.time(),
        "data": data
    }
    
    # Cleanup old caches to avoid database bloat (keep only last 50 entries)
    if len(db["caches"]) > 50:
        sorted_keys = sorted(db["caches"].keys(), key=lambda k: db["caches"][k]["timestamp"])
        for k in sorted_keys[:-50]:
            del db["caches"][k]
            
    save_db(db)

def record_bet(ticket_type, selections, total_odds, stake):
    """Records a new bet in the history and deducts the stake from bankroll."""
    db = load_db()
    
    # Check if we have enough balance
    if db["bankroll"]["balance"] < stake:
        return None, "Solde insuffisant."
    
    # Determine primary sport
    primary_sport = "Autre"
    if selections and len(selections) > 0:
        primary_sport = selections[0].get("sport", selections[0].get("match_name", "Autre").split(" vs ")[0])

    new_bet = {
        "id": bet_id,
        "timestamp": time.time(),
        "type": ticket_type,
        "selections": selections,
        "total_odds": total_odds,
        "stake": stake,
        "potential_gain": round(stake * total_odds, 2),
        "status": "PENDING",
        "primary_sport": primary_sport
    }
    
    db["history"].append(new_bet)
    db["bankroll"]["balance"] = round(db["bankroll"]["balance"] - stake, 2)
    save_db(db)
    return bet_id, None

def update_bet_result(bet_id, result):
    """Updates the status of a bet and adjusts the bankroll if won."""
    db = load_db()
    bet = next((b for b in db["history"] if b["id"] == bet_id), None)
    
    if not bet:
        return False, "Pari introuvable."
    
    if bet["status"] != "PENDING":
        return False, f"Le pari est déjà marqué comme {bet['status']}."
    
    bet["status"] = result
    
    if result == "WON":
        db["bankroll"]["balance"] = round(db["bankroll"]["balance"] + bet["potential_gain"], 2)
    elif result == "VOID":
        db["bankroll"]["balance"] = round(db["bankroll"]["balance"] + bet["stake"], 2)
        
    save_db(db)
    return True, None

def get_bankroll_stats():
    """Calculates ROI, win rate, and other betting stats with deep breakdown."""
    db = load_db()
    history = db.get("history", [])
    
    total_bets = len(history)
    settled_bets = [b for b in history if b.get("status") in ["WON", "LOST"]]
    
    # Initialize basic stats
    stats = {
        "total_bets": total_bets,
        "win_rate": 0,
        "total_staked": 0,
        "total_returned": 0,
        "roi": 0,
        "net_profit": 0,
        "balance": db.get("bankroll", {}).get("balance", 0),
        "by_strategy": {
            "safe": {"staked": 0, "profit": 0, "win_rate": 0, "bets": 0},
            "balanced": {"staked": 0, "profit": 0, "win_rate": 0, "bets": 0},
            "risky": {"staked": 0, "profit": 0, "win_rate": 0, "bets": 0}
        },
        "by_sport": {}
    }
    
    if not settled_bets:
        return stats
    
    total_staked = 0
    total_returned = 0
    wins = 0
    
    for bet in settled_bets:
        stake = bet.get("stake", 0)
        gain = bet.get("potential_gain", 0) if bet["status"] == "WON" else 0
        profit = gain - stake
        
        total_staked += stake
        total_returned += gain
        if bet["status"] == "WON": wins += 1
        
        # Strategy Breakdown
        strat = bet.get("type", "safe")
        if strat in stats["by_strategy"]:
            s_data = stats["by_strategy"][strat]
            s_data["staked"] += stake
            s_data["profit"] += profit
            s_data["bets"] += 1
            if bet["status"] == "WON": s_data["win_rate"] += 1 # Temporary count
            
        # Sport Breakdown
        sport = "Autre"
        if bet.get("selections") and len(bet["selections"]) > 0:
            # We take the sport of the first selection as primary sport for themed tickets
            sport = bet["selections"][0].get("sport", "Autre")
        
        if sport not in stats["by_sport"]:
            stats["by_sport"][sport] = {"staked": 0, "profit": 0, "bets": 0}
        
        stats["by_sport"][sport]["staked"] += stake
        stats["by_sport"][sport]["profit"] += profit
        stats["by_sport"][sport]["bets"] += 1
        
    # Finalize percentages
    stats["win_rate"] = round((wins / len(settled_bets)) * 100, 1)
    stats["total_staked"] = round(total_staked, 2)
    stats["total_returned"] = round(total_returned, 2)
    stats["net_profit"] = round(total_returned - total_staked, 2)
    stats["roi"] = round((stats["net_profit"] / total_staked) * 100, 1) if total_staked > 0 else 0
    
    for s in stats["by_strategy"].values():
        if s["bets"] > 0:
            s["win_rate"] = round((s["win_rate"] / s["bets"]) * 100, 1)
            s["profit"] = round(s["profit"], 2)
            s["staked"] = round(s["staked"], 2)
            
    for s in stats["by_sport"].values():
        s["profit"] = round(s["profit"], 2)
        s["staked"] = round(s["staked"], 2)

    return stats
