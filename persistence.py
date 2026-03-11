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
