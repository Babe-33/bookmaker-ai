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
        new_matches = await scraper.fetch_live_web_data(force_refresh)
        if new_matches or not current_matches_cache:
            current_matches_cache = new_matches
    return {"matches": current_matches_cache}

# --- Shared Analysis Global Cache ---
_LAST_MATCHES = None
_LAST_SCRAPE_TIME = 0

async def get_shared_matches():
    global _LAST_MATCHES, _LAST_SCRAPE_TIME
    now = time.time()
    # Cache matches for 5 minutes during analysis session
    if not _LAST_MATCHES or (now - _LAST_SCRAPE_TIME) > 300:
        print("MAIN: Refreshing shared matches for analysis...")
        _LAST_MATCHES = await scraper.fetch_live_web_data(force_refresh=True)
        _LAST_SCRAPE_TIME = now
    return _LAST_MATCHES

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
    # Legacy support: we'll just return an error and advise using the new buttons if needed,
    # OR we can keep it as a fallback. Let's keep it but make it very robust.
    try:
        matches = await get_shared_matches()
        if not matches: return {"error": "Aucun match disponible."}
        return await council.run_full_analysis(matches, force_refresh=True)
    except Exception as e:
        import traceback
        print(f"Full analysis error: {e}")
        traceback.print_exc()
        return {"error": f"Erreur critique: {str(e)[:50]}"}

# Serve the frontend statically
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Bookmaker AI API is running. Go to /docs for Swagger UI. Create frontend in static/."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
