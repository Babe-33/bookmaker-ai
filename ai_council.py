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
    """Ultra-fast model discovery with strict 5s limit."""
    global _WORKING_MODEL, _DISCOVERY_DONE
    if _DISCOVERY_DONE: return _WORKING_MODEL

    async with _LOCK:
        if _DISCOVERY_DONE: return _WORKING_MODEL
        
        key = os.getenv("GEMINI_API_KEY")
        if not key: return None
        
        clean_key = "".join(char for char in str(key) if char.isalnum() or char in "_-")
        genai.configure(api_key=clean_key)

        print("AI COUNCIL: Quick Discovery...")
        try:
            # Try a direct probe on the most likely model first (0.5s)
            model = genai.GenerativeModel("gemini-1.5-flash")
            await asyncio.wait_for(asyncio.to_thread(model.generate_content, "t", generation_config={"max_output_tokens": 1}), timeout=2)
            _WORKING_MODEL = "gemini-1.5-flash"
            _DISCOVERY_DONE = True
            return _WORKING_MODEL
        except:
            pass

        try:
            # If probe failed, try a quick list_models (limited to 5 models)
            models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    models.append(m.name)
                    if len(models) >= 3: break
            
            if models:
                _WORKING_MODEL = models[0]
                _DISCOVERY_DONE = True
                return _WORKING_MODEL
        except:
            pass

        # Final absolute fallback
        _WORKING_MODEL = "models/gemini-1.5-flash"
        _DISCOVERY_DONE = True 
        return _WORKING_MODEL

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
        matches = scrape_real_matches(force_refresh=force_refresh)
    except: matches = []
    if matches: set_cache("match_cache_v20", matches)
    return matches

def build_match_context(matches):
    ctx = ""
    for m in matches[:8]: # Limit to 8 for ultra-speed
        odds = m.get('odds', {})
        o_str = f"1:{odds.get('1','-')} N:{odds.get('N','-')} 2:{odds.get('2','-')}"
        ctx += f"#{m.get('id')}: {m.get('homeTeam')} vs {m.get('awayTeam')} ({o_str})\n"
    return ctx

async def run_full_analysis(matches, force_refresh=False):
    """TICKETS ONLY STRATEGY: High-Level Excellence & Direct ROI focus."""
    if not matches: return {"error": "Pas de matchs."}
    
    m_hash = str(len(matches))
    cache_key = f"analysis_tickets_speed_v106_{m_hash}"
    cached = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)

    prompt = """MISSION: ANALYSE PRO. 3 TICKETS (SAFE, BALANCED, RISKY).
    FORMAT JSON STRICT:
    {
      "statistician": "analyse courte math",
      "expert": "analyse courte terrain",
      "pessimist": "analyse courte risques",
      "trend": "analyse courte tendance",
      "predictions": {},
      "tickets": { 
          "safe": {"total_odds": 1.5, "suggested_stake": 5, "selections": [{"match": "X vs Y", "bet": "1", "odds": 1.5, "reason": "..."}]},
          "balanced": {"total_odds": 4.0, "suggested_stake": 3, "selections": []},
          "risky": {"total_odds": 12.0, "suggested_stake": 1, "selections": []}
      }
    }"""

    res = await call_gemini_safe(prompt, context, timeout=25)
    if res == "TIMEOUT": return {"error": "L'IA a mis trop de temps (>30s). Le serveur Render est surchargé. Réessayez."}
    if res == "ERROR:QUOTA": return {"error": "Google API: Quota épuisé."}
    if res == "ERROR:404": return {"error": "Google API: Erreur 404 (Modèle)."}
    if not res: return {"error": "IA inactive. Vérifiez vos clés."}

    data = extract_json(res)
    
    if data and "tickets" in data:
        if "predictions" not in data: data["predictions"] = {}
        for strategy in ["safe", "balanced", "risky"]:
            if strategy not in data["tickets"]: 
                data["tickets"][strategy] = {"total_odds": 0, "suggested_stake": 0, "selections": []}
        set_cache(cache_key, data)
        return data
        
    return {"error": "L'IA a renvoyé une réponse incomplète. Veuillez recommencer."}


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
