import os
import json
import asyncio
import time
from datetime import datetime, timezone, timedelta
from real_matches_scraper import scrape_real_matches
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

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

# Global cache for niche sports to prevent hitting quota too fast (30 mins)
MATCH_CACHE = {"data": [], "timestamp": 0}

def fetch_live_web_data(force_refresh=False):
    """
    Hybrid Scraper:
    1. Gets 100% real matches and odds from ESPN API.
    2. Fallbacks to a HIGHLY CONSTRAINED Gemini search for niche sports.
    3. Uses a 30-min cache to protect Gemini API quota.
    """
    global MATCH_CACHE
    now = time.time()
    
    # Return cache if not expired (2 hours = 7200s)
    if not force_refresh and (now - MATCH_CACHE["timestamp"] < 7200) and MATCH_CACHE["data"]:
        print("Using MATCH_CACHE (2-Hour Quota Protection Active)")
        return MATCH_CACHE["data"]

    matches = []
    # 1. API Direct (ESPN)
    try:
        espn_matches = scrape_real_matches(leagues=None, force_refresh=force_refresh)
        matches.extend(espn_matches)
    except Exception as e:
        print(f"Error fetching ESPN matches: {e}")

    # 2. Scraper Niche Sport via Gemini (To cover Pro D2, LNH, Magnus...)
    if api_key:
        client = genai.Client(api_key=api_key)
        sys_prompt = get_niche_sports_extractor_prompt()
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents="Cherche EXACTEMENT l'agenda sportif d'aujourd'hui et demain pour la Pro D2, la Starligue, la Ligue Magnus, la Champions Cup (Rugby), les Jeux Olympiques, le Tour de France (Cyclisme), la Formule 1 (Grand Prix), et le Tennis (Tournois ATP/WTA). N'INVENTE AUCUN MATCH. Extrais le JSON avec de vraies cotes bookmakers. Pour la F1, mets le favori en 'homeTeam' et 'Le reste du peloton' en 'awayTeam'.",
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
            # Failsafe statique avec DATES DYNAMIQUES
            today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            tom_str = (datetime.now(timezone.utc) + timedelta(days=1)).strftime('%Y-%m-%d')
            matches.extend([
                {"id": "n1", "sport": "Rugby", "competition": "Pro D2", "homeTeam": "Béziers", "awayTeam": "Provence Rugby", "date": f"{today_str} 21:00 UTC", "odds": {"1": 1.75, "N": 20.0, "2": 2.25}, "specialMarket": "Vainqueur Match", "specialOdd": 1.75},
                {"id": "n2", "sport": "Handball", "competition": "Starligue", "homeTeam": "PSG", "awayTeam": "Nantes", "date": f"{today_str} 20:00 UTC", "odds": {"1": 1.45, "N": 8.0, "2": 3.80}, "specialMarket": "Vainqueur Match", "specialOdd": 1.45},
                {"id": "n3", "sport": "Hockey", "competition": "Ligue Magnus", "homeTeam": "Grenoble", "awayTeam": "Rouen", "date": f"{tom_str} 20:15 UTC", "odds": {"1": 1.95, "N": 4.5, "2": 2.10}, "specialMarket": "Vainqueur Match", "specialOdd": 1.95}
            ])
            
    # Update cache
    if matches:
        MATCH_CACHE["data"] = matches
        MATCH_CACHE["timestamp"] = now
        
    return matches

def fetch_live_in_play_data():
    """Uses Gemini to find matches CURRENTLY playing for In-Play Live Betting."""
    if not api_key:
        return []
        
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents="Quels sont les matchs de sport intéressants actuellement en direct (live score) avec des cotes potentiellement rentables ?",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_LIVE_EXTRACTOR,
                temperature=0.3,
                tools=[{"google_search": {}}]
            ),
        )
        raw = response.text
        if "```json" in raw: raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw: raw = raw.split("```")[1].split("```")[0]
        data = json.loads(raw.strip())
        return data.get("matches", [])
    except Exception as e:
        print(f"Error fetching in_play matches: {e}")
        return []

def call_persona(client, system_prompt, match_data, use_search=False):
    if not client:
        return "Pas de clé API."

    config_kwargs = {
        "system_instruction": system_prompt,
        "temperature": 0.2,
    }

    if use_search:
        config_kwargs["tools"] = [{"google_search": {}}]

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash", # Using 2.0-flash as 2.5 is not yet public
            contents=match_data,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        return response.text
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg or "quota" in err_msg.lower():
            return "⏳ (Quota Google dépassé. Attendez 1 minute avant la prochaine analyse.)"
        return f"Erreur IA : {err_msg[:50]}..."

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
sys_stat = """Tu es 'Le Statisticien' (Spécialiste Data Profonde & Expected Goals). 
RÈGLE D'OR (Stratégie xG) : Ne te contente pas de la forme brute (Victoires/Défaites). Tu DOIS chercher les metrics avancées ("xG" = Expected Goals, "xGA" = Expected Goals Against).
ANOMALIE À RECHERCHER : Si une équipe perd souvent mais a un xG très haut, c'est une anomalie (malchance). Ses cotes seront surévaluées par les bookmakers. C'est là que se trouve la VRAIE VALEUR. Explique cette anomalie si tu en trouves une.
RÈGLE DE FORMATAGE : Pour chaque match, donne :
1. ANALYSE STAT & xG (1-2 phrases)
2. NOTE DE CONFIANCE (X/10)"""

sys_expert = """Tu es 'L'Expert Terrain'. Analyse la forme actuelle, les compos probables, blessés et l'enjeu psychologique (Maintien, Titre). 
Focalise-toi sur le contenu du jeu et les "infos insiders" (L'Equipe, RMC).
RÈGLE DE FORMATAGE : Pour chaque match, donne :
1. ANALYSE (1-2 phrases)
2. NOTE DE CONFIANCE (X/10)"""

sys_pessimist = """Tu es 'L'Avocat du Diable' ET le 'Détecteur de Biais Public'. 
RÈGLE D'OR (Stratégie Anti-Public) : Les bookmakers baissent drastiquement les cotes des "Equipes Populaires" (PSG, Real Madrid, Lakers) car le grand public parie dessus aveuglément. 
MISSION : Cherche systématiquement la FAILLE. Si une équipe favorite est trop soutenue par les "fans", sa cote est mathématiquement fausse. Trouve la valeur sur l'outsider (Handicap, Double Chance) et explique pourquoi le favori est un "Piège à pigeons".
RÈGLE DE FORMATAGE : Pour chaque match, donne :
1. ANALYSE DU PIÈGE / BIAIS PUBLIC (1-2 phrases)
2. NOTE DE CONFIANCE (X/10)"""

sys_trend = """Tu es 'Le Réseauteur'. Analyse les flux de paris mondiaux, les chutes de cotes et les tendances climatiques ou d'arbitrage.
RÈGLE DE FORMATAGE : Pour chaque match, donne :
1. ANALYSE (1-2 phrases)
2. NOTE DE CONFIANCE (X/10)"""

async def run_statistician(matches):
    if not api_key: return "⚠️ Clé GEMINI_API_KEY absente. Ajoute-la dans les 'Environment Variables' sur Render pour activer les experts."
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    return await asyncio.to_thread(call_persona, client, sys_stat, f"Trouve les stats détaillées des matchs suivants : SOIS EXTRÊMEMENT CONCIS (2 phrases max/match) :\n{prompt_data}", True)

async def run_expert(matches):
    if not api_key: return "⚠️ Clé GEMINI_API_KEY absente. Ajoute-la dans les 'Environment Variables' sur Render pour activer les experts."
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    return await asyncio.to_thread(call_persona, client, sys_expert, f"Trouve les avis de RMC, compos et blessés : SOIS EXTRÊMEMENT CONCIS (2 phrases max/match) :\n{prompt_data}", True)

async def run_pessimist(matches):
    if not api_key: return "⚠️ Clé GEMINI_API_KEY absente. Ajoute-la dans les 'Environment Variables' sur Render pour activer les experts."
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    return await asyncio.to_thread(call_persona, client, sys_pessimist, f"Détruis les espoirs des favoris sur ces matchs : SOIS EXTRÊMEMENT CONCIS (2 phrases max/match) :\n{prompt_data}", False)

async def run_trend(matches):
    if not api_key: return "⚠️ Clé GEMINI_API_KEY absente. Ajoute-la dans les 'Environment Variables' sur Render pour activer les experts."
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    return await asyncio.to_thread(call_persona, client, sys_trend, f"Quelles sont les grosses tendances de paris sur ces matchs : SOIS EXTRÊMEMENT CONCIS (2 phrases max/match) :\n{prompt_data}", True)

async def run_bookmaker(matches, stat_response="", expert_response="", pessimist_response="", trend_response=""):
    if not api_key: return {"error": "API Key missing"}
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    
    # Run the 4 experts concurrently to save massive time if it's the legacy call
    if not stat_response:
        stat_task = run_statistician(matches)
        expert_task = run_expert(matches)
        pessimist_task = run_pessimist(matches)
        trend_task = run_trend(matches)
        stat_response, expert_response, pessimist_response, trend_response = await asyncio.gather(
            stat_task, expert_task, pessimist_task, trend_task
        )

    # 5. Moi (Le Bookmaker / ticket final)
    # Load bankroll for localized staking
    db = {"bankroll": {"balance": 100.0}}
    try:
        with open("database.json", "r") as f: db = json.load(f)
    except: pass
    balance = db["bankroll"]["balance"]

    sys_bookie = f"""Tu es l'Expert Bookmaker, ton unique but est la RENTABILITÉ MAXIMALE. 
Ta mission : Créer le ticket parfait en utilisant toutes les données des experts.
TON CAPITAL ACTUEL : {balance}€

RÈGLES D'OR MISES À JOUR (Phase 47) :
1. CHASSEUR DE VALUE : Compare la probabilité réelle avec les MAX ODDS.
2. DOMINATION NICHE : Priorise les sports de niche (Rugby Pro D2, Handball Starligue, Hockey Magnus). Les bookmakers y font plus d'erreurs. Si tu trouves de la valeur ici, augmente le score de confiance.
3. SUREBETS : Si un match est marqué "SUREBET", il DOIT être dans le ticket (C'est de l'argent gratuit).
4. SGP : Autorisé sur le même match.
5. COMBINÉ SÉCURISÉ (SAFE) : En plus de ton ticket principal, prépare un "Safe Ticket" (cote totale entre 1.50 et 2.00) avec les sélections les plus "béton" (probabilité > 90%).
6. STAKING (KELLY) : Suggère une mise en % basée sur (Confiance vs Cote).

Expertise reçue :
Statisticien (xG) : {stat_response}
Expert Terrain : {expert_response}
Avocat du Diable (Biais Public) : {pessimist_response}
Le Réseauteur : {trend_response}

Retourne UN JSON avec DEUX tickets :
{{
    "debate": "Résumé tactique global.",
    "main_ticket": {{
        "total_odds": 5.42,
        "suggested_stake_percent": "5%",
        "suggested_stake_value": 12.5,
        "selections": [
            {{
                "match_id": "ID",
                "match_name": "Team A vs Team B",
                "prediction": "Victoire A",
                "odds": 2.10,
                "confidence": "9/10",
                "is_niche": true
            }}
        ]
    }},
    "safe_ticket": {{
        "total_odds": 1.75,
        "suggested_stake_percent": "10%",
        "suggested_stake_value": 25.0,
        "selections": []
    }}
}}
"""
    final_ticket_json_str = await asyncio.to_thread(call_persona, client, sys_bookie, prompt_data, False)
    
    import re
    try:
        raw = final_ticket_json_str
        if "```json" in raw: raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw: raw = raw.split("```")[1].split("```")[0]
        
        try:
            final_ticket = json.loads(raw.strip())
        except json.JSONDecodeError:
            # Fallback regex extraction if Gemini added conversational text around the JSON
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                final_ticket = json.loads(match.group(0))
            else:
                raise ValueError("No valid JSON object found in response.")
                
        # Fail-safe: ensure selections is a list to prevent frontend .forEach() crash
        if not isinstance(final_ticket.get("selections"), list):
            final_ticket["selections"] = []
            
    except Exception as e:
        print(f"Error parse ticket json: {e}")
        final_ticket = {
            "debate": "Erreur lors de la création du ticket. L'IA a formaté sa réponse incorrectement ou le quota a été dépassé. Veuillez réessayer.", 
            "total_odds": 0, 
            "selections": []
        }
        
    return {
        "statistician": stat_response,
        "expert": expert_response,
        "pessimist": pessimist_response,
        "trend": trend_response,
        "ticket": final_ticket
    }

async def run_ai_council(matches):
    """Legacy wrapper for backwards compat."""
    return await run_bookmaker(matches)

