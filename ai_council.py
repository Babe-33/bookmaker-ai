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

# Robust list of models to try. Some regions/keys require prefixes, others don't.
MODEL_CANDIDATES = [
    "models/gemini-1.5-flash-latest",
    "gemini-1.5-flash",
    "models/gemini-1.5-flash",
    "gemini-1.5-pro",
    "models/gemini-pro"
]
_WORKING_MODEL_CACHE = None

async def call_gemini_safe(prompt, data_context, timeout=40):
    """Call Gemini with multi-model fallback to solve 404 errors."""
    global _WORKING_MODEL_CACHE
    key = os.getenv("GEMINI_API_KEY")
    if not key: return "Erreur: Clé API manquante dans l'environnement."
    
    clean_key = str(key).strip().strip("'").strip('"').strip()
    genai.configure(api_key=clean_key)
    
    # Try the cached working model first
    models_to_test = ([_WORKING_MODEL_CACHE] if _WORKING_MODEL_CACHE else []) + MODEL_CANDIDATES
    
    last_error = ""
    for model_name in models_to_test:
        if not model_name: continue
        try:
            model = genai.GenerativeModel(model_name)
            full_prompt = f"{prompt}\n\nDONNÉES MATCHS :\n{data_context}"
            
            response = await asyncio.wait_for(
                asyncio.to_thread(model.generate_content, full_prompt),
                timeout=timeout
            )
            if response:
                _WORKING_MODEL_CACHE = model_name # Save for next time
                return response.text
        except asyncio.TimeoutError:
            return "TIMEOUT"
        except Exception as e:
            last_error = str(e).lower()
            print(f"Gemini Attempt ({model_name}) failed: {e}")
            if "quota" in last_error or "429" in last_error: return "ERROR:QUOTA"
            # If 404, we continue to the next candidate
            if "404" in last_error: continue
            return f"ERROR:UNEXPECTED ({model_name})"
            
    return "ERROR:404" # None of the candidates worked

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
    for m in matches[:10]: # Limit for speed
        ctx += f"- {m.get('homeTeam')} vs {m.get('awayTeam')} | ID: {m.get('id')} | Cotes: {m.get('odds')}\n"
    return ctx

async def run_full_analysis(matches, force_refresh=False):
    """TICKETS ONLY STRATEGY: High-Level Excellence & Direct ROI focus."""
    if not matches: return {"error": "Pas de matchs."}
    
    m_hash = str(len(matches))
    cache_key = f"analysis_tickets_high_level_v102_{m_hash}"
    cached = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)

    prompt = """Tu es le SYSTÈME ANALYTIQUE SUPRÊME. Ta mission est de générer du PROFIT NET. 
    Oublie les futilités. Scanne les données pour identifier les 3 meilleures opportunités du jour.
    
    1. "statistician" : Analyse mathématique froide (variance, value-bet, probabilités intrinsèques vs cotes).
    2. "expert" : Analyse tactique et psychologique (dynamique d'équipe, motivation, enjeux cruciaux).
    3. "pessimist" : Analyse des risques et pièges (over-confidence, blessures cachées, historique piège).
    4. "trend" : Analyse des flux du marché et consensus des parieurs pro.
    
    RECOIS CETTE STRUCTURE JSON STRICTE ET REMPLIS-LA AVEC DU TEXTE DE HAUT NIVEAU :
    {
      "statistician": "analyse quantitative experte",
      "expert": "analyse qualitative terrain",
      "pessimist": "critique acerbe des points de rupture",
      "trend": "mouvements de foule et smart money",
      "predictions": {},
      "tickets": { 
          "safe": {
              "total_odds": 1.5, 
              "suggested_stake": 5.0,
              "selections": [{"match": "Nom Match", "bet": "1", "odds": 1.5, "reason": "Argument Flash"}]
          }, 
          "balanced": {
              "total_odds": 4.5, 
              "suggested_stake": 3.0,
              "selections": []
          }, 
          "risky": {
              "total_odds": 15.0, 
              "suggested_stake": 1.0,
              "selections": []
          } 
      }
    }"""

    res = await call_gemini_safe(prompt, context, timeout=40)
    if res == "TIMEOUT": return {"error": "L'IA a mis trop de temps à répondre (Timeout)."}
    if res == "ERROR:QUOTA": return {"error": "Google API: Quota dépassé (Trop de requêtes aujourd'hui)."}
    if res == "ERROR:404": return {"error": "Google API: Erreur 404 (Modèle refusé ou Clé API restreinte)."}
    if not res: return {"error": "Veuillez vérifier votre clé API dans Render."}

    data = extract_json(res)
    
    if data and "tickets" in data:
        # Guarantee data integrity for frontend
        if "predictions" not in data: data["predictions"] = {}
        for strategy in ["safe", "balanced", "risky"]:
            if strategy not in data["tickets"]: 
                data["tickets"][strategy] = {"total_odds": 0, "suggested_stake": 0, "selections": []}
            else:
                ticket = data["tickets"][strategy]
                if "suggested_stake" not in ticket: ticket["suggested_stake"] = 0
                if "total_odds" not in ticket: ticket["total_odds"] = 0
                if "selections" not in ticket: ticket["selections"] = []
                
        set_cache(cache_key, data)
        return data
        
    print(f"JSON FAULT. Raw output was: {res[:200]}...")
    return {"error": "L'IA a généré un format invalide. Réessayez."}

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
