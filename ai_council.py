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
    """TICKETS + EXPERTISE STRATEGY: Two ultra-fast sequential calls to bypass Render's 30s limit."""
    if not matches: return {"error": "Pas de matchs."}
    
    m_hash = str(len(matches))
    cache_key = f"analysis_sequential_v109_{m_hash}"
    cached = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)

    # --- CALL 1 : THE EXPERTS (Generates text only) ---
    prompt_experts = """Tu es le Cerveau Analytique. Donne-moi ton avis d'expert sur ces matchs.
    RÉPOND STRICTEMENT EN JSON SELON CETTE STRUCTURE :
    {
      "statistician": "2 phrases : Analyse mathématique globale des matchs (les value bets).",
      "expert": "2 phrases : Analyse terrain (dynamiques d'équipe, contexte).",
      "pessimist": "2 phrases : Les pièges à éviter aujourd'hui.",
      "trend": "2 phrases : La tendance générale des parieurs.",
      "predictions": {
          "id_match_1": {"bet": "1", "confidence": 80, "reason": "Motif court"}
      }
    }"""
    
    # --- CALL 2 : THE TICKETS (Generates betting lines only) ---
    prompt_tickets = """Tu es le Cerveau Financier. Crée 3 Tickets parfaits avec ces matchs.
    RÉPOND STRICTEMENT EN JSON SELON CETTE STRUCTURE :
    {
      "tickets": { 
          "safe": {
              "total_odds": 1.5, 
              "suggested_stake": 5.0,
              "selections": [{"match": "Equipe A vs B", "bet": "1", "odds": 1.5, "reason": "Sûr"}]
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

    # Executive Summary: We execute sequentially to stay under the 30s Render Limit per request.
    print("AI COUNCIL: Starting Phase 1/2 (Experts)...")
    res_expert = await call_gemini_safe(prompt_experts, context, timeout=20)
    print("AI COUNCIL: Starting Phase 2/2 (Tickets)...")
    res_tickets = await call_gemini_safe(prompt_tickets, context, timeout=20)
    
    if res_expert == "TIMEOUT" or res_tickets == "TIMEOUT": 
        return {"error": "L'IA a mis trop de temps (>30s) sur l'une des phases. L'analyse est interrompue."}
    if res_expert == "ERROR:QUOTA": return {"error": "Google API: Quota épuisé."}
    if res_expert == "ERROR:404": return {"error": "Google API: Erreur 404 (Modèle)."}
    if not res_expert or not res_tickets: return {"error": "IA inactive. Vérifiez vos clés."}

    data_expert = extract_json(res_expert) or {}
    data_tickets = extract_json(res_tickets) or {}
    
    # Merge both JSONs
    final_data = {
        "statistician": data_expert.get("statistician", "Analyse experte non disponible."),
        "expert": data_expert.get("expert", "Analyse terrain non disponible."),
        "pessimist": data_expert.get("pessimist", "Analyse risques non disponible."),
        "trend": data_expert.get("trend", "Tendance non disponible."),
        "predictions": data_expert.get("predictions", {}),
        "tickets": data_tickets.get("tickets", {
            "safe": {"total_odds": 0, "suggested_stake": 0, "selections": []},
            "balanced": {"total_odds": 0, "suggested_stake": 0, "selections": []},
            "risky": {"total_odds": 0, "suggested_stake": 0, "selections": []}
        })
    }
    
    set_cache(cache_key, final_data)
    return final_data


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
