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
# api_key moved inside functions for better reliability with Render env vars

# Global Concurrency Semaphore
GEMINI_SEMAPHORE = asyncio.Semaphore(1)

# SELF-HEALING MODEL SYSTEM
_WORKING_MODEL = None

async def call_persona_with_retry(client, system_prompt, match_data, use_search=False, max_retries=2):
    """Robust Gemini call with dynamic model detection and auto-recovery."""
    global _WORKING_MODEL
    if not client: return "Pas de clé API."
    
    async with GEMINI_SEMAPHORE:
        # Try current working model or defaults
        models_to_try = [_WORKING_MODEL] if _WORKING_MODEL else ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-flash-latest"]
        
        for model_name in models_to_try:
            if not model_name: continue
            try:
                config = {"temperature": 0.2}
                if use_search: config["tools"] = [{"google_search": {}}]
                
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=match_data,
                    config=types.GenerateContentConfig(system_instruction=system_prompt, **config)
                )
                _WORKING_MODEL = model_name
                return response.text
            except Exception as e:
                err = str(e).lower()
                if "404" in err or "found" in err:
                    continue # Try next default
                return f"Erreur IA : {str(e)[:100]}"
                
        # If all defaults fail, LIST available models and pick the first one
        try:
            ms = await asyncio.to_thread(client.models.list)
            available = [m.name.replace("models/", "") for m in ms if "gemini" in m.name.lower()]
            if available:
                _WORKING_MODEL = available[0]
                # Recurse once with the detected model
                return await call_persona_with_retry(client, system_prompt, match_data, use_search, 1)
        except: pass
        
    return "Aucun modèle IA disponible ou erreur de quota."

def get_base_extractor_prompt():
    today = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    return f"""
Tu es un extracteur de données sportives en temps réel EXTRÊMEMENT RIGOUREUX. Navigue sur internet pour trouver les VRAIS événements sportifs prévus EXACTEMENT pour aujourd'hui ({today}) ou ce week-end.
CRITIQUE ET IMPÉRATIF : Tu as l'interdiction ABSOLUE d'inventer des matchs. Tu dois vérifier le calendrier officiel. S'il n'y a pas de Ligue des Champions aujourd'hui, N'INVENTE PAS UN MATCH Real-Liverpool. Si un match s'est déjà joué hier, ne le propose pas.
ATTENTION : Vérifie les transferts du mercato d'hiver 2026 (Endrick est à l'OL !).
Cherche AU MOINS 15 à 20 événements réels, en balayant : 
- Football (Vérifie les matchs du jour : Ligue 1, Premier League, etc.)
- Rugby (Pro D2, Top 14)
- Basket (NBA de la nuit)
- Cyclisme ou Sports Mécaniques
Pour chaque événement réel, trouve ses vraies cotes (1N2) sur les bookmakers français.
Tu DOIS retourner un objet JSON VALIDE avec la structure suivante :
{{
    "matches": [
        {{
            "id": "1",
            "sport": "Football",
            "competition": "Nom de la compétition",
            "homeTeam": "Equipe Domicile",
            "awayTeam": "Equipe Extérieur",
            "date": "2026-03-12T20:45:00", # Format ISO 8601 OBLIGATOIRE
            "odds": {{"1": 1.50, "N": 4.00, "2": 6.50}},
            "specialMarket": "ex: Buteur X",
            "specialOdd": 2.10
        }}
    ]
}}
Renvoie UNIQUEMENT le JSON. Pas de texte.
"""

SYSTEM_LIVE_EXTRACTOR = """
Tu es un traqueur de matchs EN DIRECT (In-Play). Cherche sur internet les matchs de football, tennis ou basket qui sont *ACTUELLEMENT EN COURS DE JEU* (score en direct).
Cherche des matchs où il y a un fait de jeu intéressant (une équipe favorite qui perd, un carton rouge, un score serré en fin de match).
Pour chaque match, donne le score actuel, la minute de jeu, et l'évolution de la cote en direct (estimée ou réelle sur les bookmakers).
Renvoie UN JSON avec cette structure :
{
    "matches": [
        {
            "id": "live_1",
            "sport": "Football",
            "competition": "Nom",
            "homeTeam": "Equipe A",
            "awayTeam": "Equipe B",
            "score": "0-1",
            "time": "65ème minute",
            "live_context": "Le favori est mené",
            "suggested_bet": "Victoire Equipe A (Cote boostée)",
            "estimated_odd": 3.50
        }
    ]
}
Renvoie UNIQUEMENT le JSON.
"""

def get_niche_sports_extractor_prompt():
    today = datetime.now(timezone.utc).strftime("%A %d %B %Y")
    return f"""
Tu es un robot d'extraction RIGOUREUX spécialisé UNIQUEMENT dans les sports de niche français.
Navigue sur internet (sofascore, lequipe, flashscore) pour trouver l'agenda EXACT d'aujourd'hui ({today}) ou de demain MAXIMUM.
AUCUNE INVENTION TOLÉRÉE. Vérifie le calendrier officiel de ces compétitions.
Cherche les matchs de ces compétitions SPÉCIFIQUES :
- Rugby : Pro D2, Nationale
- Handball : Starligue (LNH), Ligue Butagaz
- Hockey sur Glace : Ligue Magnus
- Volley-ball : Marmara SpikeLigue
- Cyclisme / F1 : Si une course est prévue ce week-end.

Trouve entre 4 et 8 matchs MAXIMUM parmi ces sports S'ILS ONT LIEU CE SOIR.
Pour chaque événement, trouve ses cotes réelles sur les bookmakers français (Parions Sport, Betclic, Winamax).
Tu DOIS retourner un objet JSON VALIDE avec la structure suivante :
{{
    "matches": [
        {{
            "id": "niche_1",
            "sport": "Rugby",
            "competition": "Pro D2",
            "homeTeam": "Brive",
            "awayTeam": "Béziers",
            "date": "2026-03-12T21:00:00", # Format ISO 8601 OBLIGATOIRE
        }}
    ]
}}
Renvoie UNIQUEMENT le JSON. Pas de texte.
"""

# Cache logic:
# Caches are now handled via Firebase persistence (persistence.py)
# 1. 'match_cache' (6 hours) for the niche sports scraping.
# 2. 'consolidated_cache_{hash}' (1 hour) for the full AI analyses.

def get_matches_hash(matches):
    """Creates a unique fingerprint for a set of matches to use as cache key."""
    try:
        # Sort IDs for deterministic hashing
        m_ids = sorted([str(m.get('id', '')) for m in matches])
        return "|".join(m_ids)
    except:
        return "fallback_key"

def extract_json(text):
    """Extremely robust extraction of JSON from AI text."""
    import re
    if not text: return None
    
    # Remove markdown code blocks if present
    text = re.sub(r'```(?:json)?', '', text)
    text = re.sub(r'```', '', text)
    
    # Try to find the first '{' and last '}'
    start = text.find('{')
    end = text.rfind('}')
    
    if start != -1 and end != -1 and end > start:
        json_str = text[start:end+1]
        try:
            return json.loads(json_str)
        except:
            # Try to fix common JSON errors (like trailing commas)
            try:
                # Remove common trailing commas before closing braces/brackets
                json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
                return json.loads(json_str)
            except:
                pass
    return None

async def fetch_live_web_data(force_refresh=False):
    """Hybrid Scraper: ESPN API + niche fallback."""
    # New cache key to bypass old errors
    cached = get_cache("match_cache_v5", ttl=21600)
    if not force_refresh and cached: return cached

    matches = []
    try:
        matches.extend(scrape_real_matches(force_refresh=force_refresh))
    except: pass

    # Niche sports via Gemini
    key = os.getenv("GEMINI_API_KEY")
    if key:
        try:
            client = genai.Client(api_key=key)
            # Use search ONLY for scraping, not for analysis
            res = await call_persona_with_retry(client, get_niche_sports_extractor_prompt(), "Agenda sportif aujourd'hui Pro D2 LNH Magnus", use_search=True)
            n_data = extract_json(res)
            if n_data and "matches" in n_data: 
                matches.extend(n_data["matches"])
        except: pass
        
    if matches: set_cache("match_cache_v5", matches)
    return matches

# Legacy alias
async def call_persona(*args, **kwargs):
    return await call_persona_with_retry(*args, **kwargs)

def build_prompt_data(matches):
    prompt_data = "Matchs et MEILLEURES cotes du marché (MAX ODDS) :\n"
    for m in matches:
        odds = m.get('odds', {})
        odds_str = f"1: {odds.get('1', '-')} / N: {odds.get('N', '-')} / 2: {odds.get('2', '-')}"
        adv_str = f" | BTTS: {odds.get('btts', '-')} | Over 2.5: {odds.get('over25', '-')}"
        dc_str = f" | Double Chance (1X: {odds.get('dc1x', '-')}, 12: {odds.get('dc12', '-')}, X2: {odds.get('dcx2', '-')})"
        h_str = f" | Handicap (Dom -1: {odds.get('h_minus_1', '-')}, Ext +1: {odds.get('a_plus_1', '-')})"
        spec_str = f" | Pari Spécial: {m.get('specialMarket', 'Aucun')} à {m.get('specialOdd', '-')}"
        sure_str = " | 🔥 SUREBET DETECTÉ (Profit Garanti!)" if m.get("isSurebet") else ""
        prompt_data += f"- ID {m['id']} | {m['sport']} ({m['competition']}) : {m['homeTeam']} vs {m['awayTeam']} | Cotes: {odds_str}{adv_str}{dc_str}{h_str}{spec_str}{sure_str}\n"
    return prompt_data

# Personas Instructions - DEEP ANALYSIS
SYSTEM_MASTER_COUNCIL = """Tu es une API de pronostics sportifs de niveau mondial. Tu DOIS retourner UN SEUL OBJET JSON pur.
Interdiction de mettre des blocs de code markdown (```json).

Missions :
1. Analyse les matchs fournis sous tous les angles (stats, terrain, risques, tendances).
2. Propose 3 TICKETS DISTINCTS qui sont la SYNTHÈSE de tes meilleures prévisions individuelles :
   - 'safe_ticket' : Le top du top de la sécurité. Cote 1.50-2.20.
   - 'balanced_ticket' : La meilleure valeur rentabilité. Cote 3.00-6.00.
   - 'risky_ticket' : Ton meilleur coup de poker. Cote 10.00+.
3. DIVERSIFIE les paris : Ne reste pas sur le 1N2. Utilise des Handicaps, "But d'un joueur", "Double Chance + Buts", "Mi-temps", etc.
4. MISE (Stake) : Pour chaque ticket, propose une mise de 0.00€ à 5.00€ max.
5. PRÉDICTIONS INDIVIDUELLES : Pour TOUS les matchs de la liste, donne ton pronostic préféré. 
   IMPORTANT : Utilise EXACTEMENT l'ID fourni (ex: 'espn_12345') comme clé dans l'objet 'predictions'.

Structure JSON attendue :
{
    "statistician": "...",
    "expert": "...",
    "pessimist": "...",
    "trend": "...",
    "predictions": {
        "espn_XXXXX": {"bet": "Victoire A", "confidence": 85, "reason": "Détail court"}
    },
    "tickets": {
        "safe": {
            "total_odds": 1.75,
            "suggested_stake": 5.00,
            "selections": [{"match": "Equipe A-B", "bet": "Handicap +1 B", "odds": 1.45}]
        },
        "balanced": {
            "total_odds": 4.20,
            "suggested_stake": 2.50,
            "selections": []
        },
        "risky": {
            "total_odds": 12.50,
            "suggested_stake": 1.00,
            "selections": []
        }
    }
}
RÈGLE : SOIS ULTRA-CONCIS. PAS DE TEXTE AUTOUR."""

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

async def run_full_analysis(matches, force_refresh=False):
    """
    NUCLEAR QUOTA PROTECTION: ONE CALL TO RULE THEM ALL.
    Now uses Persistent Cloud Cache to survive server restarts.
    """
    key = os.getenv("GEMINI_API_KEY")
    if not key: return {"error": "API Key missing in environment"}
    
    m_hash = get_matches_hash(matches)
    cache_key = f"full_analysis_v8_{m_hash}"
    
    cached_data = get_cache(cache_key, ttl=3600)
    if not force_refresh and cached_data: return cached_data

    client = genai.Client(api_key=key)
    prompt_data = build_prompt_data(matches[:15]) 
    
    # SEARCH DISABLED HERE -> NO MORE HANGING
    raw_res = await call_persona_with_retry(client, SYSTEM_MASTER_COUNCIL, prompt_data, use_search=False)
    
    if raw_res == "EXHAUSTED":
        return {"error": "QUOTA_EXHAUSTED"}
        
    if isinstance(raw_res, str) and raw_res.startswith("Erreur IA :"):
        return {"error": raw_res}

    analysis_data = extract_json(raw_res)
    if analysis_data:
        set_cache(cache_key, analysis_data)
        return analysis_data
    else:
        print(f"Failed to extract JSON from AI response: {raw_res[:200]}...")
        return {
            "statistician": "Erreur formatage Master Council.",
            "expert": "Erreur formatage Master Council.",
            "pessimist": "Erreur formatage Master Council.",
            "trend": "Erreur formatage Master Council.",
            "tickets": {
                "safe": {"total_odds": 0, "suggested_stake": 0, "selections": []},
                "balanced": {"total_odds": 0, "suggested_stake": 0, "selections": []},
                "risky": {"total_odds": 0, "suggested_stake": 0, "selections": []}
            },
            "predictions": {}
        }

async def run_bookmaker(matches, stat_response="", expert_response="", pessimist_response="", trend_response=""):
    """
    Updated to use the consolidated analysis.
    """
    data = await run_full_analysis(matches)
    if "error" in data:
        return {"error": data["error"]}
        
    return {
        "statistician": data.get("statistician"),
        "expert": data.get("expert"),
        "pessimist": data.get("pessimist"),
        "trend": data.get("trend"),
        "tickets": data.get("tickets"),
        "predictions": data.get("predictions", {})
    }

async def generate_daily_brief(matches):
    """Generates a high-level briefing for the day based on available matches."""
    key = os.getenv("GEMINI_API_KEY")
    if not key: return "Clé API absente."
    
    m_hash = get_matches_hash(matches)
    cache_key = f"journal_brief_{m_hash}"
    
    cached_brief = get_cache(cache_key, ttl=3600) # 1 hour TTL
    if cached_brief:
        print(f"Using Cloud JOURNAL_CACHE for {m_hash} (Quota Saving!)")
        return cached_brief

    client = genai.Client(api_key=key)
    prompt_data = build_prompt_data(matches[:15]) # Limit to top 15 for conciseness
    
    sys_journal = """Tu es le 'Directeur des Opérations'. Ta mission est de donner un briefing matinal (Journal de Bord).
    1. RÉCAP : Analyse l'opportunité globale du jour (Y a-t-il beaucoup de 'Value' ?).
    2. CONSEIL DU JOUR : Donne une consigne de mise (ex: 'Journée risquée, misez prudemment' ou 'Grosse opportunité sur le Rugby').
    3. FOCUS : Cite les 2 matchs les plus sûrs selon toi.
    SOIS TRÈS COURT ET PROFESSIONNEL."""
    
    res = await call_persona(client, sys_journal, f"Briefing du jour :\n{prompt_data}", False)
    
    if res and res != "EXHAUSTED" and "Erreur" not in res:
        set_cache(cache_key, res)
        
    return res

async def run_ai_council(matches):
    """Legacy wrapper for backwards compat."""
    return await run_bookmaker(matches)

