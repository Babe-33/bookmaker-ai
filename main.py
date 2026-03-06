from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os

from ai_council import run_ai_council, run_statistician, run_expert, run_pessimist, run_trend, run_bookmaker, fetch_live_web_data, fetch_live_in_play_data, run_live_council

app = FastAPI(title="Bookmaker AI Council API")

# Allow CORS for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In a real app we would cache this so we don't spam the scraper/API
current_matches_cache = []

@app.get("/api/matches")
async def get_matches(force_refresh: bool = False):
    global current_matches_cache
    if not current_matches_cache or force_refresh:
        new_matches = fetch_live_web_data()
        if new_matches or not current_matches_cache:
            current_matches_cache = new_matches
    return {"matches": current_matches_cache}

@app.get("/api/council")
async def get_council_debate():
    global current_matches_cache
    if not current_matches_cache:
        current_matches_cache = fetch_live_web_data()
        
    debate_result = await run_ai_council(current_matches_cache)
    return debate_result

@app.get("/api/council/statistician")
async def get_council_stat():
    global current_matches_cache
    if not current_matches_cache: current_matches_cache = fetch_live_web_data()
    return {"text": await run_statistician(current_matches_cache)}

@app.get("/api/council/expert")
async def get_council_expert():
    global current_matches_cache
    if not current_matches_cache: current_matches_cache = fetch_live_web_data()
    return {"text": await run_expert(current_matches_cache)}

@app.get("/api/council/pessimist")
async def get_council_pessimist():
    global current_matches_cache
    if not current_matches_cache: current_matches_cache = fetch_live_web_data()
    return {"text": await run_pessimist(current_matches_cache)}

@app.get("/api/council/trend")
async def get_council_trend():
    global current_matches_cache
    if not current_matches_cache: current_matches_cache = fetch_live_web_data()
    return {"text": await run_trend(current_matches_cache)}

class TicketRequest(BaseModel):
    stat_text: str
    expert_text: str
    pessimist_text: str
    trend_text: str

@app.post("/api/council/ticket")
async def get_council_ticket(req: TicketRequest):
    global current_matches_cache
    if not current_matches_cache: current_matches_cache = fetch_live_web_data()
    result = await run_bookmaker(current_matches_cache, req.stat_text, req.expert_text, req.pessimist_text, req.trend_text)
    return {"ticket": result["ticket"]}

@app.get("/api/live-matches")
async def get_live_matches():
    live_matches = fetch_live_in_play_data()
    return {"matches": live_matches}

@app.get("/api/live-council")
async def get_live_council():
    live_matches = fetch_live_in_play_data()
    debate_result = run_live_council(live_matches)
    return {"matches": live_matches, "advice": debate_result["advice"]}

# Serve the frontend statically
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    # Attempt to serve index.html from static folder if it exists
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Bookmaker AI API is running. Go to /docs for Swagger UI. Create frontend in static/."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
