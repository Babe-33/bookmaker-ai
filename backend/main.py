from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import json
import requests
from datetime import datetime

import time
import asyncio
import ai_council as council
import real_matches_scraper as scraper
from persistence import load_db, save_db, record_bet, update_bet_result, get_bankroll_stats

# --- Models ---
class TicketAction(BaseModel):
    ticket_id: str
    action: str # "won", "lost", "delete"

class BankrollUpdate(BaseModel):
    new_balance: float

class BetPlayRequest(BaseModel):
    type: str # safe, balanced, risky
    selections: List[dict]
    total_odds: float
    stake: float

class BetResultRequest(BaseModel):
    bet_id: str
    result: str # WON, LOST, VOID

app = FastAPI(title="Bookmaker AI Council API")

# Allow CORS for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cache for real match data
current_matches_cache = []

@app.get("/api/bankroll")
async def get_bankroll():
    return load_db()

@app.post("/api/bankroll/update")
async def update_bankroll(data: BankrollUpdate):
    db = load_db()
    db["bankroll"]["balance"] = data.new_balance
    db["bankroll"]["initial_balance"] = data.new_balance # Reset reference
    save_db(db)
    return db

@app.post("/api/ticket/save")
async def save_ticket(ticket: dict):
    db = load_db()
    # Add unique ID if missing
    if "id" not in ticket:
        ticket["id"] = f"t_{int(datetime.now().timestamp())}"
    ticket["status"] = "pending"
    ticket["created_at"] = datetime.now().isoformat()
    db["history"].insert(0, ticket)
    # Limit history to last 50
    db["history"] = db["history"][:50]
    save_db(db)
    return {"status": "success", "ticket_id": ticket["id"]}

@app.post("/api/ticket/action")
async def handle_ticket_action(data: TicketAction):
    db = load_db()
    for t in db["history"]:
        if t["id"] == data.ticket_id:
            if data.action == "won":
                t["status"] = "won"
                # Update balance: profit = stake * (odds - 1)
                stake = t.get("suggested_stake_value", 0)
                odds = t.get("total_odds", 1)
                db["bankroll"]["balance"] += (stake * odds) - stake # We only add the net profit
            elif data.action == "lost":
                t["status"] = "lost"
                stake = t.get("suggested_stake_value", 0)
                db["bankroll"]["balance"] -= stake
            elif data.action == "delete":
                db["history"] = [x for x in db["history"] if x["id"] != data.ticket_id]
                break
    save_db(db)
    return db

@app.get("/api/bankroll/stats")
async def get_stats():
    return get_bankroll_stats()

@app.post("/api/bet/play")
async def play_bet(data: BetPlayRequest):
    bet_id, error = record_bet(data.type, data.selections, data.total_odds, data.stake)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return {"status": "success", "bet_id": bet_id, "stats": get_bankroll_stats()}

@app.post("/api/bet/result")
async def set_bet_result(data: BetResultRequest):
    success, error = update_bet_result(data.bet_id, data.result)
    if not success:
        raise HTTPException(status_code=400, detail=error)
    return {"status": "success", "stats": get_bankroll_stats()}

@app.get("/api/matches")
async def get_matches(force_refresh: bool = False):
    global current_matches_cache
    if not current_matches_cache or force_refresh:
        new_matches = await council.fetch_live_web_data(force_refresh)
        if new_matches or not current_matches_cache:
            current_matches_cache = new_matches
    return {"matches": current_matches_cache}

# --- Shared Analysis Global Cache ---
_LAST_MATCHES = None
_LAST_SCRAPE_TIME = 0
_scrape_lock = asyncio.Lock()  # PREVENT PARALLEL SCRAPING EMBARRASSMENT

async def get_shared_matches():
    global _LAST_MATCHES, _LAST_SCRAPE_TIME
    
    # Fast path: cache valid (PHASE 115: 12-hour Hard Cache)
    now = time.time()
    if _LAST_MATCHES and (now - _LAST_SCRAPE_TIME) < 43200:
        return _LAST_MATCHES

    # Protected path: only one request can refresh at a time
    async with _scrape_lock:
        now = time.time()
        if not _LAST_MATCHES or (now - _LAST_SCRAPE_TIME) > 43200:
            print("MAIN: Emergency 12h Cache Refresh...")
            # Use False to allow the scraper's internal persistences to work
            _LAST_MATCHES = await council.fetch_live_web_data(force_refresh=False)
            _LAST_SCRAPE_TIME = now
    return _LAST_MATCHES

@app.get("/api/health/ai")
async def health_ai():
    """Diagnostic: Tests Gemini connection and lists models on failure."""
    start = time.time()
    try:
        # PHASE 122: Try without 'models/' prefix
        res = await council.call_gemini_safe("Dis 'OK'", "Test", timeout=10)
        
        if "ERROR" in str(res):
            # If it fails, list available models to find the right name
            import google.generativeai as genai
            model_list = [m.name for m in genai.list_models()]
            return {
                "status": "partial_success",
                "error_from_gemini": res,
                "available_models": model_list[:10],
                "render_ip": requests.get("https://api.ipify.org").text
            }

        return {
            "status": "connected",
            "latency": f"{round(time.time() - start, 2)}s",
            "response": res,
            "render_ip": requests.get("https://api.ipify.org").text
        }
    except Exception as e:
        return {"status": "critical_error", "error": str(e)}

@app.get("/api/admin/clear-cache")
async def clear_cache():
    global _LAST_MATCHES, _LAST_SCRAPE_TIME
    _LAST_MATCHES = None
    _LAST_SCRAPE_TIME = 0
    return {"message": "Cache réinitialisé."}

@app.get("/api/briefing")
async def get_daily_brief_endpoint():
    try:
        matches = await get_shared_matches()
        if not matches: return {"text": "Désolé, aucun match disponible."}
        text = await council.generate_daily_brief(matches)
        return {"text": text}
    except Exception as e:
        return {"text": f"Briefing indisponible: {str(e)[:50]}"}

@app.get("/api/council/stat")
async def get_council_stat():
    matches = await get_shared_matches()
    if not matches: return {"text": "Désolé, aucun match disponible."}
    return {"text": await council.run_expert_micro("stat", matches)}

@app.get("/api/council/field")
async def get_council_field():
    matches = await get_shared_matches()
    if not matches: return {"text": "Désolé, aucun match disponible."}
    return {"text": await council.run_expert_micro("field", matches)}

@app.get("/api/council/pessimist")
async def get_council_pessimist():
    matches = await get_shared_matches()
    if not matches: return {"text": "Désolé, aucun match disponible."}
    return {"text": await council.run_expert_micro("pessimist", matches)}

@app.get("/api/council/trend")
async def get_council_trend():
    matches = await get_shared_matches()
    if not matches: return {"text": "Désolé, aucun match disponible."}
    return {"text": await council.run_expert_micro("trend", matches)}

@app.get("/api/council/tickets")
async def get_council_tickets():
    matches = await get_shared_matches()
    if not matches: return {"error": "Aucun match disponible."}
    tickets = await council.run_tickets_micro(matches)
    if not tickets: return {"error": "L'IA n'a pas pu générer les tickets (Timeout). Réessayez."}
    return {"tickets": tickets}

@app.get("/api/council/full")
async def get_council_all():
    try:
        matches = await get_shared_matches()
        if not matches: return {"error": "Aucun match disponible."}
        # Use existing matches without forcing a slow scrape
        return await council.run_full_analysis(matches, force_refresh=False)
    except Exception as e:
        import traceback
        print(f"Full analysis error: {e}")
        traceback.print_exc()
        return {"error": f"Erreur critique: {str(e)[:50]}"}

# --- Static Files & Frontend ---
# PHASE 120: Absolute path resolution to fix Render 'Directory static does not exist' error
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def read_index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Interface indisponible. Vérifiez le dossier static/."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
