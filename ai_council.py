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

# Global WORKING_MODEL to avoid repeated 404s
_WORKING_MODEL = None
# Prioritize the most common names that work across regions
STABLE_MODELS = ["gemini-1.5-flash", "models/gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]

async def call_persona_with_retry(prompt, data_context):
    """Legacy SDK version with extreme resilience."""
    global _WORKING_MODEL
    key = os.getenv("GEMINI_API_KEY")
    if not key: return "Erreur: Clé API manquante dans .env"
    
    key = key.strip('"').strip("'")
    genai.configure(api_key=key)
    
    # Always try the last working model first
    models_to_try = [_WORKING_MODEL] if _WORKING_MODEL else STABLE_MODELS
    # If the working model fails, try them all
    if _WORKING_MODEL and _WORKING_MODEL in STABLE_MODELS:
        full_list = [_WORKING_MODEL] + [m for m in STABLE_MODELS if m != _WORKING_MODEL]
    else:
        full_list = STABLE_MODELS

    last_error = "Aucun modèle Gemini n'est accessible avec votre clé."
    
    for model_name in full_list:
        if not model_name: continue
        try:
            print(f"DEBUG: Tentative avec {model_name}...")
            model = genai.GenerativeModel(model_name)
            full_prompt = f"{prompt}\n\nDONNÉES MATCHS :\n{data_context}"
            
            # Non-blocking call
            response = await asyncio.to_thread(model.generate_content, full_prompt)
            if response and response.text:
                _WORKING_MODEL = model_name
                print(f"DEBUG: Succès avec {model_name}")
                return response.text
            else:
                print(f"DEBUG: Réponse vide de {model_name}")
        except Exception as e:
            err_msg = str(e).lower()
            print(f"DEBUG: Erreur avec {model_name} : {err_msg}")
            last_error = f"Erreur avec {model_name} : {str(e)}"
            if "quota" in err_msg or "429" in err_msg:
                return "ERROR:QUOTA"
            # 404 or 400 means model not found/unsupported, continue to next
            continue
            
    return f"Erreur IA : {last_error[:120]}"

def extract_json(text):
    if not text: return None
    # Remove markdown blocks
    text = re.sub(r'```(?:json)?', '', text)
    text = re.sub(r'```', '', text)
    # Find JSON boundaries
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            pass
    return None

async def fetch_live_web_data(force_refresh=False):
    cached = get_cache("match_cache_v20", ttl=21600)
    if not force_refresh and cached: return cached
    try:
        matches = scrape_real_matches(force_refresh=force_refresh)
    except Exception as e:
        print(f"Scraper error: {e}")
        matches = []
    if matches: set_cache("match_cache_v20", matches)
    return matches

def build_match_context(matches):
    ctx = "Matchs réels :\n"
    for m in matches[:12]: # Optimal count for quality/speed
        odds = m.get('odds', {})
        ctx += f"- {m.get('homeTeam')} vs {m.get('awayTeam')} | ID: {m.get('id')} | Cotes: {odds.get('1')}/{odds.get('N')}/{odds.get('2')}\n"
    return ctx

SYSTEM_MASTER_COUNCIL = """Tu es une IA de pronostics. Retourne UN SEUL OBJET JSON pur.
Structure :
{
  "statistician": "...", "expert": "...", "pessimist": "...", "trend": "...",
  "predictions": { "ID": {"bet": "...", "confidence": 85, "reason": "..."} },
  "tickets": { "safe": {...}, "balanced": {...}, "risky": {...} }
}"""

async def run_full_analysis(matches, force_refresh=False):
    if not matches: return {"error": "Aucun match trouvé pour analyse."}
    
    m_hash = "m" + str(len(matches)) # Simple hash for cache
    cache_key = f"analysis_v85_{m_hash}"
    cached = get_cache(cache_key, ttl=1800)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)
    res = await call_persona_with_retry(SYSTEM_MASTER_COUNCIL, context)
    
    if "ERROR:QUOTA" in res: return {"error": "QUOTA_EPUISE"}
    if res.startswith("Erreur IA"): return {"error": res}
    
    data = extract_json(res)
    if data:
        # Default structures to prevent frontend crashes
        if "tickets" not in data: data["tickets"] = {}
        for k in ["safe", "balanced", "risky"]:
            if k not in data["tickets"]: data["tickets"][k] = {"total_odds": 0, "selections": []}
        set_cache(cache_key, data)
        return data
        
    return {"error": "L'IA a retourné un format invalide. Réessayez."}

async def generate_daily_brief(matches):
    if not matches: return "Aucun match pour le briefing."
    prompt = "Fais un briefing Directeur très court (3 phrases) des meilleures opportunités."
    res = await call_persona_with_retry(prompt, build_match_context(matches[:5]))
    return res

# Compatibility wrappers
async def run_statistician(matches):
    data = await run_full_analysis(matches)
    return data.get("statistician", "Erreur d'analyse.") if isinstance(data, dict) else str(data)
async def run_expert(matches):
    data = await run_full_analysis(matches)
    return data.get("expert", "Erreur d'analyse.") if isinstance(data, dict) else str(data)
async def run_pessimist(matches):
    data = await run_full_analysis(matches)
    return data.get("pessimist", "Erreur d'analyse.") if isinstance(data, dict) else str(data)
async def run_trend(matches):
    data = await run_full_analysis(matches)
    return data.get("trend", "Erreur d'analyse.") if isinstance(data, dict) else str(data)
async def run_ai_council(matches):
    return await run_full_analysis(matches)
async def run_bookmaker(matches):
    return await run_full_analysis(matches)
