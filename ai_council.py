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
STABLE_NAMES = ["gemini-1.5-flash", "models/gemini-1.5-flash", "gemini-1.5-pro"]

async def get_model_name():
    """Simple model selector with fallback."""
    global _WORKING_MODEL
    if _WORKING_MODEL: return _WORKING_MODEL
    
    key = os.getenv("GEMINI_API_KEY")
    if not key: return None
    genai.configure(api_key=key.strip('"').strip("'"))
    
    # Quick test the most likely one
    for name in STABLE_NAMES:
        try:
            model = genai.GenerativeModel(name)
            await asyncio.to_thread(model.generate_content, "hi", generation_config={"max_output_tokens": 5})
            _WORKING_MODEL = name
            return name
        except: continue
    return "gemini-1.5-flash"

async def call_gemini_safe(prompt, data_context, timeout=25):
    """Call Gemini with a strict timeout and error handling."""
    model_name = await get_model_name()
    try:
        model = genai.GenerativeModel(model_name)
        full_prompt = f"{prompt}\n\nDONNÉES :\n{data_context}"
        
        # Wrapped in a timeout to prevent infinite hangs
        response = await asyncio.wait_for(
            asyncio.to_thread(model.generate_content, full_prompt),
            timeout=timeout
        )
        return response.text if response else ""
    except asyncio.TimeoutError:
        print(f"Gemini Timeout for model {model_name}")
        return "TIMEOUT"
    except Exception as e:
        print(f"Gemini Error ({model_name}): {e}")
        return ""

def extract_json(text):
    if not text: return None
    try:
        # Clean markdown
        text = re.sub(r'```(?:json)?', '', text)
        text = re.sub(r'```', '', text)
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
    except: pass
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
    """SEQUENTIAL STRATEGY: One by one to avoid overloading Render CPU/Network."""
    if not matches: return {"error": "Pas de matchs."}
    
    m_hash = str(len(matches))
    cache_key = f"analysis_seq_v89_{m_hash}"
    cached = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)

    # 1. Council Call
    council_prompt = """Retourne UNIQUEMENT un JSON : { "statistician": "...", "expert": "...", "pessimist": "...", "trend": "..." }
    Fais une analyse brève du Conseil."""
    res_council = await call_gemini_safe(council_prompt, context)
    if res_council == "TIMEOUT": return {"error": "L'IA est trop lente sur ce serveur. Réessayez."}
    
    # 2. Predictions Call
    pred_prompt = f"""Analyse CHAQUE match et retourne UNIQUEMENT un JSON :
    {{ 
      "predictions": {{ "ID": {{"bet": "...", "confidence": 85, "reason": "..."}} }},
      "tickets": {{ "safe": {{...}}, "balanced": {{...}}, "risky": {{...}} }}
    }}"""
    res_pred = await call_gemini_safe(pred_prompt, context, timeout=40)
    if res_pred == "TIMEOUT": return {"error": "Le calcul des pronostics a expiré. Relancez."}

    data_council = extract_json(res_council) or {}
    data_pred = extract_json(res_pred) or {}

    final_data = {**data_council, **data_pred}
    if "predictions" in final_data:
        set_cache(cache_key, final_data)
        return final_data
    
    return {"error": "IA a renvoyé une réponse incomplète."}

async def generate_daily_brief(matches):
    if not matches: return "Aucun match."
    res = await call_gemini_safe("Fais un briefing Directeur de 2 phrases.", build_match_context(matches[:5]))
    return res if res not in ["TIMEOUT", ""] else "Briefing indisponible."

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
