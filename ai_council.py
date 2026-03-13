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

# We completely remove dynamic discovery. The legacy SDK fails to alias models correctly,
# resulting in 404 Not Found on Render. We use the absolute, explicit latest model.
EXPLICIT_MODEL = "models/gemini-1.5-flash-latest"

async def call_gemini_safe(prompt, data_context, timeout=40):
    """Call Gemini explicitly with strict timeout."""
    key = os.getenv("GEMINI_API_KEY")
    if not key: return "Erreur: Clé API manquante dans l'environnement."
    
    clean_key = str(key).strip().strip("'").strip('"').strip()
    genai.configure(api_key=clean_key)
    
    try:
        model = genai.GenerativeModel(EXPLICIT_MODEL)
        full_prompt = f"{prompt}\n\nDONNÉES MATCHS :\n{data_context}"
        
        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, full_prompt),
            timeout=timeout
        )
        return response.text if response else ""
    except asyncio.TimeoutError:
        print(f"Gemini Timeout sur {EXPLICIT_MODEL}")
        return "TIMEOUT"
    except Exception as e:
        err_str = str(e).lower()
        print(f"Gemini Error ({EXPLICIT_MODEL}): {e}")
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
    for m in matches[:10]: # Limit for speed
        ctx += f"- {m.get('homeTeam')} vs {m.get('awayTeam')} | ID: {m.get('id')} | Cotes: {m.get('odds')}\n"
    return ctx

async def run_full_analysis(matches, force_refresh=False):
    """TICKETS ONLY STRATEGY: Maximum quality, minimum payload weight."""
    if not matches: return {"error": "Pas de matchs."}
    
    m_hash = str(len(matches))
    cache_key = f"analysis_tickets_only_v96_{m_hash}"
    cached = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)

    prompt = """Tu es une machine API HAUT NIVEAU. Renvoye un JSON valide et complet. 
    MISSION : Oublie les pronostics individuels de tous les matchs. Concentre-toi UNIQUEMENT sur la création de 3 TÉCKETS EXCEPTIONNELS (Safe, Équilibré, Audacieux) avec les meilleurs matchs de la liste.
    
    1. "statistician" : Analyse proba détaillée sur la stratégie des 3 tickets.
    2. "expert" : Analyse terrain de tes choix.
    3. "pessimist" : Les points faibles de tes tickets.
    4. "trend" : La tendance globale.
    5. "predictions" : DOIT RESTER VIDE {}. Ne liste PAS les autres matchs.
    
    STRUCTURE EXACTE À RENVOYER :
    {
      "statistician": "analyse pro poussée",
      "expert": "analyse pro poussée",
      "pessimist": "analyse pro poussée",
      "trend": "analyse pro poussée",
      "predictions": {},
      "tickets": { 
          "safe": {"total_odds": 2.5, "selections": [{"match_id": "123", "bet": "1", "odds": 1.5, "reason": "mot"}]}, 
          "balanced": {"total_odds": 5.0, "selections": []}, 
          "risky": {"total_odds": 12.0, "selections": []} 
      }
    }"""

    res = await call_gemini_safe(prompt, context, timeout=40)
    if res == "TIMEOUT": return {"error": "L'IA a mis trop de temps à répondre (Timeout)."}
    if res == "ERROR:QUOTA": return {"error": "Google API: Quota dépassé (Trop de requêtes aujourd'hui)."}
    if res == "ERROR:404": return {"error": "Google API: Erreur 404 (Modèle refusé ou Clé API restreinte)."}
    if not res: return {"error": "Veuillez vérifier votre clé API dans Render."}

    data = extract_json(res)
    
    if data and "tickets" in data:
        # Guarantee predictions is an empty dict so UI doesn't crash
        if "predictions" not in data: data["predictions"] = {}
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
