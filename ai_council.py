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
    global _WORKING_MODEL, _DISCOVERY_DONE
    if _DISCOVERY_DONE: return _WORKING_MODEL
    async with _LOCK:
        if _DISCOVERY_DONE: return _WORKING_MODEL
        key = os.getenv("GEMINI_API_KEY")
        if not key: return None
        key = key.strip('"').strip("'")
        genai.configure(api_key=key)
        
        # Test basic Flash first
        for name in ["gemini-1.5-flash", "models/gemini-1.5-flash", "gemini-1.5-pro"]:
            try:
                model = genai.GenerativeModel(name)
                await asyncio.to_thread(model.generate_content, "hi", generation_config={"max_output_tokens": 5})
                _WORKING_MODEL = name
                _DISCOVERY_DONE = True
                return name
            except: continue
        return "gemini-1.5-flash" # Fallback

async def call_gemini(prompt, data_context):
    model_name = await discover_best_model()
    try:
        model = genai.GenerativeModel(model_name)
        full_prompt = f"{prompt}\n\nDONNÉES :\n{data_context}"
        response = await asyncio.to_thread(model.generate_content, full_prompt)
        return response.text if response else ""
    except Exception as e:
        print(f"Gemini Error: {e}")
        return ""

def extract_json(text):
    if not text: return None
    try:
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
    for m in matches[:10]:
        ctx += f"- {m.get('homeTeam')} vs {m.get('awayTeam')} | ID: {m.get('id')} | Cotes: {m.get('odds')}\n"
    return ctx

async def run_full_analysis(matches, force_refresh=False):
    """SPLIT STRATEGY: 2 separate calls for maximum speed and detail."""
    if not matches: return {"error": "Pas de matchs."}
    
    m_hash = str(len(matches))
    cache_key = f"analysis_split_v88_{m_hash}"
    cached = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached: return cached

    context = build_match_context(matches)

    # CALL 1: The Council (Personalities)
    council_prompt = """Tu es le Conseil des Intelligences. Retourne un JSON pur :
    { "statistician": "...", "expert": "...", "pessimist": "...", "trend": "..." }
    Sois bref et pro."""
    
    # CALL 2: The Predictions & Tickets (Detailed)
    pred_prompt = """Tu es l'Analyste de Précision. Analyse CHAQUE match de la liste et retourne un JSON pur :
    { 
      "predictions": { "ID": {"bet": "Pari suggéré", "confidence": 85, "reason": "..."} },
      "tickets": { "safe": {...}, "balanced": {...}, "risky": {...} }
    }"""

    # Run calls in parallel for speed
    results = await asyncio.gather(
        call_gemini(council_prompt, context),
        call_gemini(pred_prompt, context)
    )

    council_data = extract_json(results[0]) or {}
    pred_data = extract_json(results[1]) or {}

    # Merge results
    final_data = {**council_data, **pred_data}
    
    if final_data:
        set_cache(cache_key, final_data)
        return final_data
    
    return {"error": "Format IA invalide."}

async def generate_daily_brief(matches):
    if not matches: return "Aucun match."
    return await call_gemini("Fais un briefing Directeur de 3 phrases.", build_match_context(matches[:5]))

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
