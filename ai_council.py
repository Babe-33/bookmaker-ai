import os
import json
import asyncio
import time
from datetime import datetime, timezone, timedelta
from persistence import get_cache, set_cache, load_db
from real_matches_scraper import scrape_real_matches
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# Global Concurrency Semaphore
GEMINI_SEMAPHORE = asyncio.Semaphore(1)

async def call_persona_with_retry(client, system_prompt, match_data, use_search=False):
    """Simplified Bimodal Fallback: tries 2.0-flash, then 1.5-flash on failure."""
    if not client: return "Clé API absente."
    
    async with GEMINI_SEMAPHORE:
        # First attempt: 2.0-flash
        try:
            config = {"temperature": 0.1}
            if use_search: config["tools"] = [{"google_search": {}}]
            
            response = await asyncio.to_thread(
                client.models.generate_content,
                model="gemini-2.0-flash",
                contents=match_data,
                config=types.GenerateContentConfig(system_instruction=system_prompt, **config)
            )
            if response.text: return response.text
        except Exception as e:
            # Second attempt: 1.5-flash
            try:
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-1.5-flash",
                    contents=match_data,
                    config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=0.1)
                )
                if response.text: return response.text
            except: pass
            
            err_msg = str(e).lower()
            if "quota" in err_msg or "429" in err_msg: return "ERROR:QUOTA"
            return f"Erreur IA: {str(e)[:50]}"
            
    return "Aucune réponse de l'IA."

def get_base_extractor_prompt():
    today = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    return f"""
Tu es un extracteur de données sportives en temps réel EXTRÊMEMENT RIGOUREUX. Navigue sur internet pour trouver les VRAIS événements sportifs prévus EXACTEMENT pour aujourd'hui ({today}) ou ce week-end.
Cherche AU MOINS 15 à 20 événements réels. Renvoie UNIQUEMENT un JSON valide.
"""

def get_niche_sports_extractor_prompt():
    return """Tu es un expert en sports de niche français. Trouve les matchs Pro D2, LNH, Magnus pour aujourd'hui. Renvoie un JSON."""

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
    """Hybrid Scraper: ESPN API + niche fallback."""
    cached = get_cache("match_cache_v10", ttl=21600)
    if not force_refresh and cached: return cached

    matches = []
    try:
        matches.extend(scrape_real_matches(force_refresh=force_refresh))
    except: pass

    key = os.getenv("GEMINI_API_KEY")
    if key:
        try:
            client = genai.Client(api_key=key)
            res = await call_persona_with_retry(client, "Trouve les matchs sportifs du jour en France (Pro D2, LNH, Magnus).", "Scraping", use_search=True)
            n_data = extract_json(res)
            if n_data and "matches" in n_data: matches.extend(n_data["matches"])
        except: pass
        
    if matches: set_cache("match_cache_v10", matches)
    return matches

async def call_persona(*args, **kwargs):
    return await call_persona_with_retry(*args, **kwargs)

def build_prompt_data(matches):
    prompt_data = "Matchs du jour :\n"
    for m in matches:
        odds = m.get('odds', {})
        prompt_data += f"- ID {m['id']} | {m['sport']} : {m['homeTeam']} vs {m['awayTeam']} | Cotes 1N2: {odds.get('1','-')}/{odds.get('N','-')}/{odds.get('2','-')}\n"
    return prompt_data

SYSTEM_MASTER_COUNCIL = """Tu es une API de pronostics sportifs. Retourne UN SEUL OBJET JSON pur.
Structure : {
  "statistician": "...", "expert": "...", "pessimist": "...", "trend": "...",
  "predictions": { "ID": {"bet": "...", "confidence": 80, "reason": "..."} },
  "tickets": { "safe": {...}, "balanced": {...}, "risky": {...} }
}"""

async def run_full_analysis(matches, force_refresh=False):
    key = os.getenv("GEMINI_API_KEY")
    if not key: return {"error": "API Key missing"}
    
    m_hash = get_matches_hash(matches)
    cache_key = f"full_analysis_emergency_v10_{m_hash}"
    cached_data = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached_data: return cached_data

    client = genai.Client(api_key=key)
    # LIMIT TO 6 MATCHES FOR SPEED
    prompt_data = build_prompt_data(matches[:6]) 
    raw_res = await call_persona_with_retry(client, SYSTEM_MASTER_COUNCIL, prompt_data)
    
    if "ERROR:QUOTA" in str(raw_res): return {"error": "QUOTA_EXHAUSTED"}
    
    data = extract_json(raw_res)
    if data:
        set_cache(cache_key, data)
        return data
    return {"error": "Erreur de formatage IA."}

async def run_bookmaker(matches):
    return await run_full_analysis(matches)

async def generate_daily_brief(matches):
    key = os.getenv("GEMINI_API_KEY")
    if not key: return "Clé absente."
    client = genai.Client(api_key=key)
    res = await call_persona_with_retry(client, "Fais un court résumé des opportunités du jour.", build_prompt_data(matches[:10]))
    return res

async def run_ai_council(matches):
    return await run_bookmaker(matches)
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
