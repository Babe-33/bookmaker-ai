import os
import json
import asyncio
import time
import re
from datetime import datetime, timezone
import google.generativeai as genai
from persistence import get_cache, set_cache, load_db
from real_matches_scraper import scrape_real_matches
from dotenv import load_dotenv

load_dotenv()

# Global state for persistent model tracking
_WORKING_MODEL = None
_DISCOVERY_DONE = False
_LOCK = asyncio.Lock()

async def discover_best_model():
    """HARDCODED FOR RENDER FREE QUOTA SAFETY (Speed > Discovery)"""
    key = os.getenv("GEMINI_API_KEY")
    if key:
        clean_key = "".join(char for char in str(key) if char.isalnum() or char in "_-")
        genai.configure(api_key=clean_key)
    return "models/gemini-1.5-flash-latest"

async def call_gemini_safe(prompt, data_context, timeout=25):
    """Call Gemini with sub-30s safety for Cloud platforms."""
    model_name = await discover_best_model()
    
    try:
        model = genai.GenerativeModel(model_name)
        full_prompt = f"{prompt}\n\nDATA:\n{data_context}"
        
        # We use a 25s timeout specifically for the API call to leave 5s for the rest of the request
        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, full_prompt),
            timeout=timeout
        )
        return response.text if response else ""
    except asyncio.TimeoutError:
        return "TIMEOUT"
    except Exception as e:
        err_str = str(e).lower()
        if "quota" in err_str or "429" in err_str: return "ERROR:QUOTA"
        if "404" in err_str: return "ERROR:404"
        return ""

def extract_json(text):
    if not text: return None
    try:
        # Nettoyage brutal du markdown
        text = text.replace('```json', '').replace('```', '')
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
    except Exception as e:
        print(f"Extraction JSON échouée: {e}")
    return None

async def fetch_live_web_data(force_refresh=False):
    cached = get_cache("match_cache_v20", ttl=21600)
    if not force_refresh and cached: return cached
    try:
        # WRAP SYNCHRONOUS SCRAPING IN A THREAD TO PREVENT EVENT LOOP BLOCKING
        matches = await asyncio.to_thread(scrape_real_matches, force_refresh=force_refresh)
    except Exception as e:
        print(f"SCRAPE ERROR: {e}")
        matches = []
    if matches: set_cache("match_cache_v20", matches)
    return matches

def build_match_context(matches):
    ctx = ""
    for m in matches[:8]: # Limit to 8 for ultra-speed
        odds = m.get('odds', {})
        o_str = f"1:{odds.get('1','-')} N:{odds.get('N','-')} 2:{odds.get('2','-')}"
        ctx += f"#{m.get('id')}: {m.get('homeTeam')} vs {m.get('awayTeam')} ({o_str})\n"
    return ctx

async def run_expert_micro(expert_id, matches):
    """Pinpoint analysis for a specific expert."""
    context = build_match_context(matches)
    prompts = {
        "stat": "Analyse mathématiquement ces matchs (value bets). Fais 2 phrases très courtes. PAS DE JSON.",
        "field": "Analyse les dynamiques et enjeux terrain. Fais 2 phrases très courtes. PAS DE JSON.",
        "pessimist": "Quels sont les pièges évidents ? Fais 2 phrases très courtes. PAS DE JSON.",
        "trend": "Quelle est la tendance des parieurs pros ? Fais 2 phrases très courtes. PAS DE JSON."
    }
    prompt = prompts.get(expert_id, "Fais une analyse rapide.")
    res = await call_gemini_safe(prompt, context, timeout=15)
    return res if res not in ["TIMEOUT", "ERROR:QUOTA", "ERROR:404", ""] else "Indisponible actuellement."

async def run_tickets_micro(matches):
    """Pinpoint generation of the 3 tickets only."""
    context = build_match_context(matches)
    prompt = """Tu es le Banquier. Génère UNIQUEMENT ce JSON EXACT pour 3 tickets (Safe, Équililibré, Osé), sans aucun texte autour :
    {
      "tickets": { 
          "safe": {"total_odds": 1.5, "suggested_stake": 5.0, "selections": [{"match": "Match A vs B", "bet": "1", "odds": 1.5, "reason": "Base"}]}, 
          "balanced": {"total_odds": 4.5, "suggested_stake": 3.0, "selections": []}, 
          "risky": {"total_odds": 15.0, "suggested_stake": 1.0, "selections": []} 
      }
    }"""
    res = await call_gemini_safe(prompt, context, timeout=20)
    data = extract_json(res)
    if not data or "tickets" not in data: return None
    return data["tickets"]

async def run_full_analysis(matches, force_refresh=False):
    """Compatibility wrapper for the old 'Full' button, but now uses the new micro-logic."""
    # (Existing logic but calling our new micros to be consistent)
    # This will be used as a fallback or for the 'Full' button if still in use.
    # For maximum stability, we recommend using the individual endpoints.
    stat = await run_expert_micro("stat", matches)
    field = await run_expert_micro("field", matches)
    pessimist = await run_expert_micro("pessimist", matches)
    trend = await run_expert_micro("trend", matches)
    tickets = await run_tickets_micro(matches)
    
    return {
        "statistician": stat,
        "expert": field,
        "pessimist": pessimist,
        "trend": trend,
        "predictions": {},
        "tickets": tickets or {}
    }


async def generate_daily_brief(matches):
    if not matches: return "Aucun match."
    res = await call_gemini_safe("Fais un briefing Directeur de 2 phrases sur les meilleurs matchs.", build_match_context(matches[:5]))
    if res == "TIMEOUT": return "Briefing hors ligne (Délai dépassé)."
    if res == "ERROR:QUOTA": return "Briefing hors ligne (Quota API dépassé)."
    if res == "ERROR:404": return "Briefing hors ligne (Erreur 404 API Google)."
    return res if res else "Briefing indisponible."



# Compatibility wrappers
async def run_statistician(matches):
    d = await run_full_analysis(matches)
    return d.get("statistician", "Erreur.")
async def run_expert(matches):
    d = await run_full_analysis(matches)
    return d.get("expert", "Erreur.")
async def run_pessimist(matches):
    d = await run_full_analysis(matches)
    return d.get("pessimist", "Erreur.")
async def run_trend(matches):
    d = await run_full_analysis(matches)
    return d.get("trend", "Erreur.")
async def run_ai_council(matches):
    return await run_full_analysis(matches)
async def run_bookmaker(matches):
    return await run_full_analysis(matches)
