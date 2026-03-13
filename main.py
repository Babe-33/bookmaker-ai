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

from ai_council import run_ai_council, run_statistician, run_expert, run_pessimist, run_trend, run_bookmaker, fetch_live_web_data, generate_daily_brief
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
        new_matches = await fetch_live_web_data(force_refresh)
        if new_matches or not current_matches_cache:
            current_matches_cache = new_matches
    return {"matches": current_matches_cache}

@app.get("/api/journal/brief")
async def get_daily_brief_endpoint():
    global current_matches_cache
    try:
        if not current_matches_cache: current_matches_cache = await fetch_live_web_data()
        text = await generate_daily_brief(current_matches_cache)
        return {"text": text}
    except Exception as e:
        return {"text": f"Briefing indisponible: {str(e)[:50]}"}

@app.get("/api/council/statistician")
async def get_council_stat():
    global current_matches_cache
    try:
        if not current_matches_cache: current_matches_cache = await fetch_live_web_data()
        return {"text": await run_statistician(current_matches_cache)}
    except Exception as e:
        return {"text": f"Erreur Stat: {str(e)[:50]}"}

@app.get("/api/council/expert")
async def get_council_expert():
    global current_matches_cache
    try:
        if not current_matches_cache: current_matches_cache = await fetch_live_web_data()
        return {"text": await run_expert(current_matches_cache)}
    except Exception as e:
        return {"text": f"Erreur Expert: {str(e)[:50]}"}

@app.get("/api/council/pessimist")
async def get_council_pessimist():
    global current_matches_cache
    if not current_matches_cache: current_matches_cache = await fetch_live_web_data()
    return {"text": await run_pessimist(current_matches_cache)}

@app.get("/api/council/trend")
async def get_council_trend():
    global current_matches_cache
    if not current_matches_cache: current_matches_cache = await fetch_live_web_data()
    return {"text": await run_trend(current_matches_cache)}

class TicketRequest(BaseModel):
    stat_text: str
    expert_text: str
    pessimist_text: str
    trend_text: str

@app.post("/api/council/ticket")
async def get_council_ticket(req: TicketRequest):
    global current_matches_cache
    if not current_matches_cache: current_matches_cache = await fetch_live_web_data()
    result = await run_bookmaker(current_matches_cache, req.stat_text, req.expert_text, req.pessimist_text, req.trend_text)
    return {"ticket": result["ticket"]}

@app.get("/api/council/full")
async def get_council_all():
    global current_matches_cache
    try:
        if not current_matches_cache: 
            current_matches_cache = await fetch_live_web_data()
        
        if not current_matches_cache:
            return {"error": "Aucun match disponible pour l'analyse."}
            
        result = await run_bookmaker(current_matches_cache)
        return result
    except Exception as e:
        import traceback
        print(f"Full analysis error: {e}")
        traceback.print_exc()
        return {"error": f"Erreur critique lors de l'analyse: {str(e)[:100]}"}

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
