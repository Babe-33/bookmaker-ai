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

# Global state to find THE working model for this specific key/region
_DISCOVERED_MODEL = None
_DISCOVERY_LOCK = asyncio.Lock()

# List of all possible names for the same models (SDK variations)
CANDIDATE_NAMES = [
    "gemini-1.5-flash", 
    "models/gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro",
    "models/gemini-1.5-pro",
    "gemini-pro",
    "models/gemini-pro"
]

async def discover_working_model():
    """Tests all candidates and finds which one works for THIS user/key."""
    global _DISCOVERED_MODEL
    if _DISCOVERED_MODEL: return _DISCOVERED_MODEL

    async with _DISCOVERY_LOCK:
        if _DISCOVERED_MODEL: return _DISCOVERED_MODEL
        
        key = os.getenv("GEMINI_API_KEY")
        if not key: return None
        key = key.strip('"').strip("'")
        genai.configure(api_key=key)

        print("AI COUNCIL: Starting Model Discovery Phase...")
        for name in CANDIDATE_NAMES:
            try:
                model = genai.GenerativeModel(name)
                # Quick non-blocking test
                response = await asyncio.to_thread(model.generate_content, "test", generation_config={"max_output_tokens": 5})
                if response:
                    _DISCOVERED_MODEL = name
                    print(f"AI COUNCIL: Discovery SUCCESS! Model found: {name}")
                    return name
            except Exception as e:
                print(f"AI COUNCIL: Discovery skip {name} (Error: {str(e)[:50]})")
                continue
        
        return None

async def call_persona_with_retry(prompt, data_context):
    """Call using the discovered working model."""
    key = os.getenv("GEMINI_API_KEY")
    if not key: return "Erreur: Clé API manquante."
    
    key = key.strip('"').strip("'")
    genai.configure(api_key=key)

    working_model = await discover_working_model()
    if not working_model:
        return "Erreur IA: Aucun modèle compatible trouvé pour votre clé (404 persistent)."

    try:
        model = genai.GenerativeModel(working_model)
        full_prompt = f"{prompt}\n\nDONNÉES MATCHS :\n{data_context}"
        response = await asyncio.to_thread(model.generate_content, full_prompt)
        if response and response.text:
            return response.text
    except Exception as e:
        err = str(e).lower()
        if "quota" in err or "429" in err:
            return "ERROR:QUOTA"
        return f"Erreur IA avec {working_model}: {str(e)[:100]}"
            
    return "L'IA n'a pas renvoyé de réponse."

def extract_json(text):
    if not text: return None
    text = re.sub(r'```(?:json)?', '', text)
    text = re.sub(r'```', '', text)
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except:
            pass
    return None

async def fetch_live_web_data(force_refresh=False):
    cached = get_cache("match_cache_v20", ttl=21600)
    if not force_refresh and cached: return cached
    try:
        matches = scrape_real_matches(force_refresh=force_refresh)
    except:
        matches = []
    if matches: set_cache("match_cache_v20", matches)
    return matches

def build_match_context(matches):
    ctx = "Matchs :\n"
    for m in matches[:10]:
        odds = m.get('odds', {})
        ctx += f"- {m.get('homeTeam')} vs {m.get('awayTeam')} | ID: {m.get('id')} | Cotes: {odds.get('1')}/{odds.get('N')}/{odds.get('2')}\n"
    return ctx

SYSTEM_MASTER_COUNCIL = """Tu es une IA de paris. Retourne UN SEUL JSON pur.
Structure : {
  "statistician": "...", "expert": "...", "pessimist": "...", "trend": "...",
  "predictions": { "ID": {"bet": "...", "confidence": 85, "reason": "..."} },
  "tickets": { "safe": {...}, "balanced": {...}, "risky": {...} }
}"""

async def run_full_analysis(matches, force_refresh=False):
    if not matches: return {"error": "Aucun match."}
    
    m_hash = str(len(matches))
    cache_key = f"analysis_bulletproof_v1_{m_hash}"
    cached = get_cache(cache_key, ttl=1800)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)
    res = await call_persona_with_retry(SYSTEM_MASTER_COUNCIL, context)
    
    if "ERROR:QUOTA" in res: return {"error": "QUOTA"}
    if res.startswith("Erreur IA"): return {"error": res}
    
    data = extract_json(res)
    if data:
        # Defaults
        if "tickets" not in data: data["tickets"] = {}
        for k in ["safe", "balanced", "risky"]:
            if k not in data["tickets"]: data["tickets"][k] = {"total_odds": 0, "selections": []}
        set_cache(cache_key, data)
        return data
        
    return {"error": "Format IA invalide."}

async def generate_daily_brief(matches):
    if not matches: return "Aucun match."
    res = await call_persona_with_retry("Fais un briefing Directeur de 2 phrases.", build_match_context(matches[:5]))
    return res

# Wrappers
async def run_statistician(matches):
    d = await run_full_analysis(matches)
    return d.get("statistician", "Erreur.") if isinstance(d, dict) else str(d)
async def run_expert(matches):
    d = await run_full_analysis(matches)
    return d.get("expert", "Erreur.") if isinstance(d, dict) else str(d)
async def run_pessimist(matches):
    d = await run_full_analysis(matches)
    return d.get("pessimist", "Erreur.") if isinstance(d, dict) else str(d)
async def run_trend(matches):
    d = await run_full_analysis(matches)
    return d.get("trend", "Erreur.") if isinstance(d, dict) else str(d)
async def run_ai_council(matches):
    return await run_full_analysis(matches)
async def run_bookmaker(matches):
    return await run_full_analysis(matches)
