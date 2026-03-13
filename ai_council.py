import os
import json
import asyncio
import time
from datetime import datetime, timezone
import google.generativeai as genai
from persistence import get_cache, set_cache, load_db
from real_matches_scraper import scrape_real_matches
from dotenv import load_dotenv

load_dotenv()

# Global WORKING_MODEL to avoid repeated 404s
_WORKING_MODEL = None
STABLE_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-1.5-pro", "gemini-pro"]

async def call_persona_with_retry(prompt, data_context):
    """Legacy SDK version with robust multi-model fallback."""
    global _WORKING_MODEL
    key = os.getenv("GEMINI_API_KEY")
    if not key: return "Erreur: Clé API manquante."
    
    # Strip quotes if they were mistakenly kept in .env
    key = key.strip('"').strip("'")
    genai.configure(api_key=key)
    
    models_to_try = [_WORKING_MODEL] if _WORKING_MODEL else STABLE_MODELS
    
    last_error = "Aucun modèle n'a répondu."
    for model_name in models_to_try:
        if not model_name: continue
        try:
            model = genai.GenerativeModel(model_name)
            full_prompt = f"{prompt}\n\nDONNÉES MATCHS :\n{data_context}"
            
            # Use to_thread to keep FastAPI async loop non-blocking
            response = await asyncio.to_thread(model.generate_content, full_prompt)
            if response.text:
                _WORKING_MODEL = model_name
                return response.text
        except Exception as e:
            err = str(e).lower()
            last_error = str(e)
            if "404" in err or "not found" in err:
                continue # Try next model
            if "429" in err or "quota" in err:
                return "ERROR:QUOTA"
            # If 400 or other, keep trying next models just in case
            continue
            
    return f"Erreur IA : {last_error[:100]}"

def get_matches_hash(matches):
    try:
        m_ids = sorted([str(m.get('id', '')) for m in matches])
        return "|".join(m_ids)
    except:
        return "fallback"

def extract_json(text):
    import re
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
    except Exception as e:
        print(f"Scraper error: {e}")
        matches = []
        
    if matches: set_cache("match_cache_v20", matches)
    return matches

def build_match_context(matches):
    ctx = "Voici les matchs réels du jour :\n"
    for m in matches[:15]: # Limit to top 15 for a good balance of speed/quality
        odds = m.get('odds', {})
        ctx += f"- {m.get('homeTeam')} vs {m.get('awayTeam')} | Sport: {m.get('sport')} | Comp: {m.get('competition')} | ID: {m.get('id')} | Cotes: {odds.get('1')}/{odds.get('N')}/{odds.get('2')}\n"
    return ctx

SYSTEM_MASTER_COUNCIL = """Tu es une IA de pronostics sportifs de précision. Analyse les matchs fournis et retourne UN SEUL OBJET JSON pur.
Structure attendue :
{
  "statistician": "Analyse chiffrée courte...",
  "expert": "Analyse tactique courte...",
  "pessimist": "Mise en garde sur les pièges...",
  "trend": "Analyse des cotes et du marché...",
  "predictions": {
    "ID_DU_MATCH": {"bet": "Pari suggéré (ex: 1, N, 2, Buteur X)", "confidence": 85, "reason": "Pourquoi ?"}
  },
  "tickets": {
    "safe": {"total_odds": 2.10, "suggested_stake": 5, "selections": [{"match": "Nom", "bet": "X", "odds": 1.45}]},
    "balanced": {"total_odds": 5.50, "suggested_stake": 2, "selections": [...]},
    "risky": {"total_odds": 15.0, "suggested_stake": 1, "selections": [...]}
  }
}
RÈGLE D'OR : Ne propose QUE des matchs présents dans la liste avec leur ID correct."""

async def run_full_analysis(matches, force_refresh=False):
    if not matches: return {"error": "Aucun match à analyser."}
    
    m_hash = get_matches_hash(matches)
    cache_key = f"analysis_phase67_stable_v1_{m_hash}"
    cached = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)
    res = await call_persona_with_retry(SYSTEM_MASTER_COUNCIL, context)
    
    if "ERROR:QUOTA" in res: return {"error": "Quota Gemini épuisé. Réessayez demain."}
    if res.startswith("Erreur IA"): return {"error": res}
    
    data = extract_json(res)
    if data:
        # Data validation to prevent frontend crashes
        if "tickets" not in data: data["tickets"] = {}
        for cat in ["safe", "balanced", "risky"]:
            if cat not in data["tickets"]: data["tickets"][cat] = {"total_odds": 0, "suggested_stake": 0, "selections": []}
            
        set_cache(cache_key, data)
        return data
        
    return {"error": "Formatage IA corrompu. Relancez l'analyse."}

async def run_bookmaker(matches):
    return await run_full_analysis(matches)

async def generate_daily_brief(matches):
    if not matches: return "Pas de matchs aujourd'hui."
    prompt = "Tu es le Directeur. Fais un briefing très court (3 phrases) sur les opportunités du jour."
    res = await call_persona_with_retry(prompt, build_match_context(matches[:6]))
    return res

# Legacy wrappers for main.py compatibility
async def run_statistician(matches):
    res = await run_full_analysis(matches)
    return res.get("statistician", "Analyse indisponible.")
async def run_expert(matches):
    res = await run_full_analysis(matches)
    return res.get("expert", "Analyse indisponible.")
async def run_pessimist(matches):
    res = await run_full_analysis(matches)
    return res.get("pessimist", "Analyse indisponible.")
async def run_trend(matches):
    res = await run_full_analysis(matches)
    return res.get("trend", "Analyse indisponible.")
async def run_ai_council(matches):
    return await run_bookmaker(matches)
