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
    """Records a new bet with extreme robustness."""
    try:
        db = load_db()
        
        # Ensure bankroll exists
        if "bankroll" not in db:
            db["bankroll"] = {"balance": 100.0, "initial_balance": 100.0, "currency": "€"}
        
        balance = db["bankroll"].get("balance", 0)
        
        # Check if we have enough balance
        if balance < stake:
            return None, "Solde insuffisant."
        
        # Determine primary sport and ID
        bet_id = f"bet_{int(time.time())}"
        primary_sport = "Autre"
        if selections and len(selections) > 0:
            first_sel = selections[0]
            if isinstance(first_sel, dict):
                primary_sport = first_sel.get("sport", first_sel.get("match_name", "Autre").split(" vs ")[0])

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
        
        if "history" not in db: db["history"] = []
        db["history"].append(new_bet)
        db["bankroll"]["balance"] = round(balance - stake, 2)
        save_db(db)
        return bet_id, None
    except Exception as e:
        print(f"ERROR record_bet: {e}")
        return None, f"Erreur serveur: {str(e)}"


def get_bankroll_stats():
    """Calculates summary statistics with extreme safety and standardization."""
    try:
        db = load_db()
        bankroll = db.get("bankroll", {"balance": 100.0, "initial_balance": 100.0})
        history = db.get("history", [])
        
        # Standardized stats object matching app.js expectations
        stats = {
            "balance": round(bankroll.get("balance", 100.0), 2),
            "current_balance": round(bankroll.get("balance", 100.0), 2),
            "net_profit": round(bankroll.get("balance", 100.0) - bankroll.get("initial_balance", 100.0), 2),
            "win_rate": 0,
            "roi": 0,
            "total_bets": len(history),
            "total_staked": 0,
            "total_returned": 0,
            "by_strategy": {
                "safe": {"staked": 0, "profit": 0, "win_rate": 0, "bets": 0},
                "balanced": {"staked": 0, "profit": 0, "win_rate": 0, "bets": 0},
                "risky": {"staked": 0, "profit": 0, "win_rate": 0, "bets": 0}
            },
            "by_sport": {}
        }
        
        wins = 0
        settled_bets = [b for b in history if isinstance(b, dict) and b.get("status") in ["WON", "LOST"]]
        
        for bet in settled_bets:
            stake = bet.get("stake", 0)
            status = bet.get("status", "PENDING")
            gain = bet.get("potential_gain", 0) if status == "WON" else 0
            profit = gain - stake
            
            stats["total_staked"] += stake
            stats["total_returned"] += gain
            if status == "WON": wins += 1
            
            # Strategy Breakdown
            strat = str(bet.get("type", "safe")).lower()
            if "sûr" in strat or "safe" in strat: strat = "safe"
            elif "balanced" in strat: strat = "balanced"
            elif "risky" in strat: strat = "risky"
            
            if strat in stats["by_strategy"]:
                s = stats["by_strategy"][strat]
                s["staked"] += stake
                s["profit"] += profit
                s["bets"] += 1
                if status == "WON": s["win_rate"] += 1
                
            # Sport Breakdown
            sport = "Autre"
            if bet.get("selections") and isinstance(bet["selections"], list) and len(bet["selections"]) > 0:
                first_sel = bet["selections"][0]
                if isinstance(first_sel, dict):
                    sport = first_sel.get("sport", "Autre")
            
            if sport not in stats["by_sport"]:
                stats["by_sport"][sport] = {"staked": 0, "profit": 0, "bets": 0}
            
            stats["by_sport"][sport]["staked"] += stake
            stats["by_sport"][sport]["profit"] += profit
            stats["by_sport"][sport]["bets"] += 1

        # Post-process calculations
        if stats["total_staked"] > 0:
            stats["roi"] = round(((stats["total_returned"] - stats["total_staked"]) / stats["total_staked"]) * 100, 1)
        
        if len(settled_bets) > 0:
            stats["win_rate"] = round((wins / len(settled_bets)) * 100, 1)
            
        for s in stats["by_strategy"].values():
            if s["bets"] > 0:
                s["win_rate"] = round((s["win_rate"] / s["bets"]) * 100, 1)
                s["profit"] = round(s["profit"], 2)
            
        for s in stats["by_sport"].values():
            s["profit"] = round(s["profit"], 2)
                
        return stats
    except Exception as e:
        print(f"CRITICAL get_bankroll_stats error: {e}")
        # Return mandatory defaults to prevent frontend toFixed crashes
        return {
            "balance": 100.0, "current_balance": 100.0, "net_profit": 0.0, 
            "win_rate": 0, "roi": 0, "total_bets": 0, "total_staked": 0.0,
            "total_returned": 0.0, "by_strategy": {}, "by_sport": {}
        }

def update_bet_result(bet_id, result):
    """Updates the status of a bet with extreme robustness and handles payouts."""
    try:
        db = load_db()
        history = db.get("history", [])
        found = False
        
        for bet in history:
            if bet.get("id") == bet_id:
                if bet.get("status") != "PENDING":
                    return False, "Pari déjà réglé."
                    
                bet["status"] = result
                if "bankroll" not in db: db["bankroll"] = {"balance": 100.0, "initial_balance": 100.0}
                
                if result == "WON":
                    gain = bet.get("potential_gain", 0)
                    db["bankroll"]["balance"] = round(db["bankroll"].get("balance", 0) + gain, 2)
                elif result == "VOID":
                    # Refund the stake
                    stake = bet.get("stake", 0)
                    db["bankroll"]["balance"] = round(db["bankroll"].get("balance", 0) + stake, 2)
                
                found = True
                break
        
        if not found:
            return False, "Pari non trouvé."
            
        save_db(db)
        return True, None
    except Exception as e:
        print(f"ERROR update_bet_result: {e}")
        return False, str(e)
