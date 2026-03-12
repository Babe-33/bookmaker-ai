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
        with open(DB_PATH, "w") as f: json.dump(default, f)
        return default
    with open(DB_PATH, "r") as f: 
        try:
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
            
    with open(DB_PATH, "w") as f: json.dump(data, f, indent=4)

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
    
    bet_id = f"bet_{int(time.time())}"
    new_bet = {
        "id": bet_id,
        "timestamp": time.time(),
        "type": ticket_type, # safe, balanced, risky
        "selections": selections,
        "total_odds": total_odds,
        "stake": stake,
        "potential_gain": round(stake * total_odds, 2),
        "status": "PENDING" # PENDING, WON, LOST, VOID
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
    """Calculates ROI, win rate, and other betting stats."""
    db = load_db()
    history = db.get("history", [])
    
    total_bets = len(history)
    settled_bets = [b for b in history if b["status"] in ["WON", "LOST"]]
    
    if not settled_bets:
        return {
            "total_bets": total_bets,
            "win_rate": 0,
            "total_staked": 0,
            "total_returned": 0,
            "roi": 0,
            "net_profit": 0,
            "balance": db["bankroll"]["balance"]
        }
    
    wins = len([b for b in settled_bets if b["status"] == "WON"])
    win_rate = (wins / len(settled_bets)) * 100
    
    total_staked = sum(b["stake"] for b in settled_bets)
    total_returned = sum(b.get("potential_gain", 0) for b in settled_bets if b["status"] == "WON")
    
    net_profit = total_returned - total_staked
    roi = (net_profit / total_staked) * 100 if total_staked > 0 else 0
    
    return {
        "total_bets": total_bets,
        "win_rate": round(win_rate, 1),
        "total_staked": round(total_staked, 2),
        "total_returned": round(total_returned, 2),
        "roi": round(roi, 1),
        "net_profit": round(net_profit, 2),
        "balance": db["bankroll"]["balance"]
    }
