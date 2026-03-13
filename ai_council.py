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

# Global state
_WORKING_MODEL = None
_DISCOVERY_DONE = False
_LOCK = asyncio.Lock()

async def discover_best_model():
    """Uses list_models() to find the best available model, or falls back to brute force."""
    global _WORKING_MODEL, _DISCOVERY_DONE
    if _DISCOVERY_DONE: return _WORKING_MODEL

    async with _LOCK:
        if _DISCOVERY_DONE: return _WORKING_MODEL
        
        key = os.getenv("GEMINI_API_KEY")
        if not key: return None
        key = key.strip('"').strip("'")
        genai.configure(api_key=key)

        print("AI COUNCIL: Starting Advanced Discovery...")
        try:
            # Try to list models to see exactly what is allowed
            available_models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name)
            
            if available_models:
                # Prioritize Flash 1.5 for speed
                flash_models = [m for m in available_models if "flash" in m and "1.5" in m]
                if flash_models:
                    _WORKING_MODEL = flash_models[0]
                else:
                    _WORKING_MODEL = available_models[0]
                
                print(f"AI COUNCIL: Auto-discovered model -> {_WORKING_MODEL}")
                _DISCOVERY_DONE = True
                return _WORKING_MODEL
        except Exception as e:
            print(f"AI COUNCIL: list_models() failed: {e}. Switching to Brute Force.")

        # Brute Force Fallback if list_models() is restricted
        candidates = [
            "gemini-1.5-flash", 
            "models/gemini-1.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.5-pro",
            "models/gemini-2.0-flash-exp",
            "gemini-pro"
        ]
        
        for name in candidates:
            try:
                model = genai.GenerativeModel(name)
                # Quick test
                await asyncio.to_thread(model.generate_content, "test", generation_config={"max_output_tokens": 5})
                _WORKING_MODEL = name
                _DISCOVERY_DONE = True
                print(f"AI COUNCIL: Brute Force Success -> {name}")
                return name
            except:
                continue
        
        return None

async def call_persona_with_retry(prompt, data_context):
    model_name = await discover_best_model()
    if not model_name:
        return "Erreur IA: Clé API non autorisée ou invalide sur Render (404/403)."

    try:
        model = genai.GenerativeModel(model_name)
        full_prompt = f"{prompt}\n\nDONNÉES MATCHS :\n{data_context}"
        response = await asyncio.to_thread(model.generate_content, full_prompt)
        if response and response.text:
            return response.text
    except Exception as e:
        err = str(e).lower()
        if "quota" in err or "429" in err: return "ERROR:QUOTA"
        return f"Erreur IA ({model_name}): {str(e)[:100]}"
            
    return "Aucune réponse de l'IA."

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
    ctx = "Voici les matchs :\n"
    for m in matches[:10]:
        ctx += f"- {m.get('homeTeam')} vs {m.get('awayTeam')} | ID: {m.get('id')} | Cotes: {m.get('odds')}\n"
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
    cache_key = f"analysis_final_v1_{m_hash}"
    cached = get_cache(cache_key, ttl=1800)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)
    res = await call_persona_with_retry(SYSTEM_MASTER_COUNCIL, context)
    
    if "ERROR:QUOTA" in res: return {"error": "QUOTA"}
    if res.startswith("Erreur IA"): return {"error": res}
    
    data = extract_json(res)
    if data:
        if "tickets" not in data: data["tickets"] = {}
        for k in ["safe", "balanced", "risky"]:
            if k not in data["tickets"]: data["tickets"][k] = {"total_odds": 0, "selections": []}
        set_cache(cache_key, data)
        return data
        
    return {"error": "IA a renvoyé un format invalide."}

async def generate_daily_brief(matches):
    if not matches: return "Aucun match."
    return await call_persona_with_retry("Refais un briefing Directeur ultra-court.", build_match_context(matches[:5]))

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
    return await run_bookmaker(matches)
async def run_bookmaker(matches):
    return await run_full_analysis(matches)
