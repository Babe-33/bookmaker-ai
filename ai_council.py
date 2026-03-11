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

# Global Concurrency Semaphore: Only 1 Gemini call at a time to stay under RPS limits
GEMINI_SEMAPHORE = asyncio.Semaphore(1)

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
            "date": "Date réelle du match",
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
            "date": "Date réelle du match",
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
    """Robustly extracts JSON from potentially messy AI text."""
    import re
    # 1. Try markdown blocks
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        try: return json.loads(content)
        except: pass
    
    # 2. Try simple brace matching
    match = re.search(r'(\{.*\})', text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        try: return json.loads(content)
        except: pass
        
    # 3. Last resort: dirty cleaning
    cleaned = text.strip().replace('```json', '').replace('```', '').strip()
    try: return json.loads(cleaned)
    except: return None

async def fetch_live_web_data(force_refresh=False):
    """
    Hybrid Scraper:
    1. Gets 100% real matches and odds from ESPN API.
    2. Fallbacks to a HIGHLY CONSTRAINED Gemini search for niche sports.
    3. Uses a 6-hour CLOUD cache to protect Gemini API quota.
    """
    # Return cache if not expired (6 hours = 21600s)
    cached_matches = get_cache("match_cache", ttl=21600)
    if not force_refresh and cached_matches:
        print("Using Cloud MATCH_CACHE (6-Hour Quota Protection Active)")
        return cached_matches

    matches = []
    # 1. API Direct (ESPN + Merge the-odds-api)
    try:
        espn_matches = scrape_real_matches(leagues=None, force_refresh=force_refresh)
        matches.extend(espn_matches)
    except Exception as e:
        print(f"Error fetching ESPN matches: {e}")

    # 2. Scraper Niche Sport via Gemini (To cover Pro D2, LNH, Magnus...)
    key = os.getenv("GEMINI_API_KEY")
    if key:
        client = genai.Client(api_key=key)
        sys_prompt = get_niche_sports_extractor_prompt()
        try:
            # Use Semaphore to avoid RPS saturation
            async with GEMINI_SEMAPHORE:
                # Log available models once to help debug 404
                try:
                    models = client.models.list()
                    print("LOG: Available models for this key:")
                    for m in models: print(f" - {m.name}")
                except: pass

                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-1.5-flash",
                    contents="Cherche EXACTEMENT l'agenda sportif d'aujourd'hui et demain pour la Pro D2, la Starligue, la Ligue Magnus, la Champions Cup (Rugby), les Jeux Olympiques, le Tour de France (Cyclisme), the Formule 1 (Grand Prix), et le Tennis (Tournois ATP/WTA). N'INVENTE AUCUN MATCH. Extrais le JSON avec de vraies cotes bookmakers. Pour la F1, mets le favori en 'homeTeam' et 'Le reste du peloton' en 'awayTeam'.",
                    config=types.GenerateContentConfig(
                        system_instruction=sys_prompt,
                        temperature=0.0,
                        tools=[{"google_search": {}}]
                    ),
                )
            
            raw = response.text
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
                
            niche_data = json.loads(raw.strip())
            niche_matches = niche_data.get("matches", [])
            
            # Ensure odds object has 1, N, 2 keys explicitly
            for nm in niche_matches:
                if "odds" not in nm or not isinstance(nm["odds"], dict):
                    nm["odds"] = {"1": "-", "N": "-", "2": "-"}
                else:
                    nm["odds"]["1"] = nm["odds"].get("1", nm["odds"].get("home", "-"))
                    nm["odds"]["N"] = nm["odds"].get("N", nm["odds"].get("draw", "-"))
                    nm["odds"]["2"] = nm["odds"].get("2", nm["odds"].get("away", "-"))

            matches.extend(niche_matches)
            
        except Exception as e:
            print(f"Error fetching niche sports via Gemini: {e}")
            pass # No static fallback to avoid presenting fake data to the final user
            
    # Update Cloud Cache
    if matches:
        set_cache("match_cache", matches)
        
    return matches

def fetch_live_in_play_data():
    """Uses Gemini to find matches CURRENTLY playing for In-Play Live Betting."""
    return [] # Disabled for quota safety

async def call_persona_with_retry(client, system_prompt, match_data, use_search=False, max_retries=3):
    """
    Wraps Gemini calls with a global semaphore (RPS protection) and an auto-retry loop.
    """
    if not client:
        return "Pas de clé API."

    # Use Semaphore to avoid RPS saturation
    async with GEMINI_SEMAPHORE:
        for attempt in range(max_retries):
            config_kwargs = {
                "system_instruction": system_prompt,
                "temperature": 0.2,
            }
            if use_search:
                config_kwargs["tools"] = [{"google_search": {}}]

            try:
                # Use standard gemini-1.5-flash (no latest)
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-1.5-flash",
                    contents=match_data,
                    config=types.GenerateContentConfig(**config_kwargs)
                )
                return response.text
            except Exception as e:
                err_msg = str(e)
                print(f"Exception from Gemini: {e}") # DEBUG
                if "429" in err_msg or "quota" in err_msg.lower():
                    if attempt < max_retries - 1:
                        # Exponential backoff: 3s, 6s...
                        wait_time = (attempt + 1) * 3
                        print(f"Quota Gemini dépassé. Retentative en {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        return "EXHAUSTED"
                # Return the FULL error message to help user debug the 404
                return f"Erreur IA : {err_msg}"

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
# MASTER SYSTEM PROMPT - Consolidates all experts into one call
SYSTEM_MASTER_COUNCIL = """Tu es le 'Conseil des Experts AI'. Ta mission est de réaliser une analyse COMPLÈTE de 360° sur les matchs fournis et de générer un ticket de pari optimal.

Tu dois impérativement répondre avec un objet JSON qui contient les analyses de tes 4 experts internes :

1. 'L'Analyste Opta' (Statisticien) : Utilise la logique Opta (xG, PPDA, transitions).
2. 'L'Expert Terrain' : Forme, blessés, enjeux psychologiques.
3. 'L'Avocat du Diable' : Détecte le biais public et les pièges des favoris trop populaires.
4. 'Le Réseauteur' : Tendances mondiales et flux de paris.

Enfin, tu agis comme le 'Bookmaker' pour créer le meilleur ticket (Main Ticket + Safe Ticket) en utilisant toutes ces expertises.

STRUCTURE DU JSON ATTENDU :
{
    "statistician": "Texte court de l'analyse Opta...",
    "expert": "Texte court de l'expert terrain...",
    "pessimist": "Analyse des pièges...",
    "trend": "Tendances mondiales...",
    "ticket": {
        "debate": "Résumé tactique global.",
        "main_ticket": {
            "total_odds": 5.42,
            "selections": [{"match_name": "...", "prediction": "...", "odds": 2.10}]
        },
        "safe_ticket": {
            "total_odds": 1.75,
            "selections": []
        }
    }
}
RÈGLE D'OR : UN SEUL JSON, PAS DE TEXTE AUTOUR. SOIS ULTRA-CONCIS DANS LES ANALYSES (1-2 phrases par match).
"""

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
    cache_key = f"full_analysis_{m_hash}"
    
    cached_data = get_cache(cache_key, ttl=3600) # 1 hour TTL for analysis
    if not force_refresh and cached_data:
        print(f"Using Cloud ANALYSIS_CACHE for {m_hash} (100% Quota Saving!)")
        return cached_data

    client = genai.Client(api_key=key)
    prompt_data = build_prompt_data(matches[:12]) 
    
    print(f"DEBUG: Using API Key starting with {key[:8]}...")    
    raw_res = await call_persona_with_retry(client, SYSTEM_MASTER_COUNCIL, prompt_data, use_search=True)
    
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
            "ticket": {"debate": "Analyse échouée (Format JSON invalide).", "main_ticket": {"total_odds": 0, "selections": []}}
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
        "ticket": data.get("ticket")
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
    
    res = await asyncio.to_thread(call_persona, client, sys_journal, f"Briefing du jour :\n{prompt_data}", False)
    
    if res and res != "EXHAUSTED" and "Erreur" not in res:
        set_cache(cache_key, res)
        
    return res

async def run_ai_council(matches):
    """Legacy wrapper for backwards compat."""
    return await run_bookmaker(matches)

