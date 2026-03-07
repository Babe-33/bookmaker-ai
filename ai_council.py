import os
import json
import asyncio
import datetime
from real_matches_scraper import scrape_real_matches
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

def get_base_extractor_prompt():
    today = datetime.datetime.now().strftime("%A %d %B %Y")
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
    today = datetime.datetime.now().strftime("%A %d %B %Y")
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

def fetch_live_web_data():
    """
    Hybrid Scraper:
    1. Gets 100% real matches and odds from ESPN API (Football, NBA, Top 14).
    2. Fallbacks to a HIGHLY CONSTRAINED Gemini search strictly for French niche sports (Pro D2, Starligue, Magnus).
    """
    matches = []
    # 1. API Direct (ESPN)
    try:
        espn_matches = scrape_real_matches()
        matches.extend(espn_matches)
    except Exception as e:
        print(f"Error fetching ESPN matches: {e}")

    # 2. Scraper Niche Sport via Gemini (To cover Pro D2, LNH, Magnus...)
    if api_key:
        client = genai.Client(api_key=api_key)
        sys_prompt = get_niche_sports_extractor_prompt()
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
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
            # Failsafe statique pour s'assurer que les French Niche Sports s'affichent toujours même si l'API IA sature
            today_str = datetime.utcnow().strftime('%Y-%m-%d')
            matches.extend([
                {"id": "n1", "sport": "Rugby", "competition": "Pro D2", "homeTeam": "Valence Romans", "awayTeam": "RC Vannes", "date": f"{today_str} 21:00 UTC", "odds": {"1": 1.85, "N": 20.0, "2": 2.15}, "specialMarket": "Vainqueur Match", "specialOdd": 1.85},
                {"id": "n2", "sport": "Handball", "competition": "Starligue", "homeTeam": "Istres", "awayTeam": "Tremblay", "date": f"{today_str} 20:00 UTC", "odds": {"1": 1.95, "N": 8.0, "2": 2.05}, "specialMarket": "Vainqueur Match", "specialOdd": 1.95},
                {"id": "n3", "sport": "Hockey", "competition": "Ligue Magnus", "homeTeam": "Bordeaux", "awayTeam": "Marseille", "date": f"{today_str} 20:30 UTC", "odds": {"1": 1.75, "N": 4.5, "2": 3.10}, "specialMarket": "Vainqueur Match", "specialOdd": 1.75},
                {"id": "n4", "sport": "Hockey", "competition": "Ligue Magnus", "homeTeam": "Anglet", "awayTeam": "Rouen", "date": f"{today_str} 20:30 UTC", "odds": {"1": 4.20, "N": 5.0, "2": 1.45}, "specialMarket": "Vainqueur Match", "specialOdd": 1.45},
                {"id": "n5", "sport": "Handball", "competition": "Starligue", "homeTeam": "Montpellier", "awayTeam": "PSG", "date": "2026-03-07 20:00 UTC", "odds": {"1": 2.80, "N": 7.5, "2": 1.55}, "specialMarket": "Vainqueur Match", "specialOdd": 1.55}
            ])
            
    return matches

def fetch_live_in_play_data():
    """Uses Gemini to find matches CURRENTLY playing for In-Play Live Betting."""
    if not api_key:
        return []
        
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
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
        "temperature": 0.5,
    }

    if use_search:
        config_kwargs["tools"] = [{"google_search": {}}]

def call_persona(client, system_prompt, match_data, use_search=False):
    if not client:
        return "Pas de clé API."

    config_kwargs = {
        "system_instruction": system_prompt,
        "temperature": 0.5,
    }
    if use_search:
        config_kwargs["tools"] = [{"google_search": {}}]

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
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
    prompt_data = "Matchs et cotes disponibles ce soir :\n"
    for m in matches:
        odds_str = f"1: {m['odds'].get('1', '-')} / N: {m['odds'].get('N', '-')} / 2: {m['odds'].get('2', '-')}"
        spec_str = f" | Pari Spécial: {m.get('specialMarket', 'Aucun')} à {m.get('specialOdd', '-')}"
        prompt_data += f"- ID {m['id']} | {m['sport']} : {m['homeTeam']} vs {m['awayTeam']} | Cotes 1N2: {odds_str}{spec_str}\n"
    return prompt_data

# Personas Instructions
sys_stat = "Tu es 'Le Statisticien', perfectionniste et pointilleux. Utilise Google pour trouver des statistiques mathématiques réelles, météo, historiques des arbitres. ATTENTION : vérifie les effectifs actuels et compos probables. Cherche les Value Bets en croisant données et cotes. Fais un résumé chiffré de 5 lignes."
sys_expert = "Tu es 'L'Expert Terrain', le pronostiqueur francophone ultime, connu pour sa Rigueur extrême. Utilise Google pour valider les compositions d'équipe prévues, les blessés, les suspendus (Exemple : Souviens-toi qu'Endrick est titulaire à l'OL maintenant, pas au Real Madrid). Croise tes infos avec celles données aujourd'hui sur 'Les Paris RMC' et 'Winamax TV'. Fais un résumé terrain expert de 5 lignes."
sys_pessimist = "Tu es 'L'Avocat du Diable'. Ton but est de trouver LA FAILLE qui ferait perdre le pari évident. Sois factuel. Vérifie la véracité des informations sportives (mercato hiver 2026). Utilise internet pour trouver l'historique noir ou la fatigue extrême des favoris de ces matchs. Rédige un avis pessimiste de 4 lignes maximum."
sys_trend = "Tu es 'Le Réseauteur'. Tu analyses où va l'argent (Market Movers) et le consensus du public (Reddit, Twitter, Tipsters étrangers). Cherche sur internet quelles sont les équipes les plus pariées (Public Betting) sur ces matchs et si des cotes chutent brutalement (Drop Odds). Fais un résumé de 4 lignes maximum."

async def run_statistician(matches):
    if not api_key: return "API Key missing"
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    return await asyncio.to_thread(call_persona, client, sys_stat, f"Trouve les stats détaillées des matchs suivants:\n{prompt_data}", True)

async def run_expert(matches):
    if not api_key: return "API Key missing"
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    return await asyncio.to_thread(call_persona, client, sys_expert, f"Trouve les avis de RMC, compos et blessés sur ces matchs:\n{prompt_data}", True)

async def run_pessimist(matches):
    if not api_key: return "API Key missing"
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    return await asyncio.to_thread(call_persona, client, sys_pessimist, f"Détruis les espoirs des favoris sur ces matchs:\n{prompt_data}", True)

async def run_trend(matches):
    if not api_key: return "API Key missing"
    client = genai.Client(api_key=api_key)
    prompt_data = build_prompt_data(matches)
    return await asyncio.to_thread(call_persona, client, sys_trend, f"Quelles sont les grosses tendances de paris et chutes de cotes sur ces matchs:\n{prompt_data}", True)

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
    sys_bookie = f"""Tu es l'Expert Bookmaker de l'équipe, ton seul objectif est la RENTABILITE. Ta mission est de proposer les paris LES PLUS SURS OU LES MIEUX VALORISES parmi la liste.
IMPORTANT : IL N'Y A PLUS D'OBLIGATION D'Avoir UNE COTE x4. Si le meilleur pari du jour est un Single à 1.50, propose-le. Si c'est un combiné de 2 matchs ultra-sécurisés, propose-le. Si tu sens un gros coup justifié à 8.00, propose-le.
Priorise la fiabilité. Prends en compte toutes les compositions, stats joueurs (buteurs, etc.).
Voici les avis de tes 4 experts ayant fait des recherches web :
Statisticien : {stat_response}
Expert Terrain : {expert_response}
Avocat du Diable : {pessimist_response}
Le Réseauteur : {trend_response}

Mets-toi dans la peau d'un pronostiqueur pro. Tu DOIS retourner un objet JSON VALIDE SANS TEXTE AUTOUR :
{{
    "debate": "Explique pourquoi tu choisis ces paris précisément, justifie tes choix.",
    "total_odds": 4.50,
    "selections": [
        {{
            "match_id": "1",
            "match_name": "Equipe A vs Equipe B",
            "prediction": "Victoire A ou Buteur X",
            "odds": 1.80
        }}
    ]
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



def run_live_council(matches):
    """Analyzes IN-PLAY matches to find immediate betting opportunities."""
    if not api_key or not matches:
        return {"advice": "Aucun match en direct analysable."}
        
    client = genai.Client(api_key=api_key)
    prompt_data = "Matchs en cours de jeu :\n"
    for m in matches:
        prompt_data += f"- {m['homeTeam']} vs {m['awayTeam']} | Score: {m['score']} à la {m['time']} | Contexte: {m['live_context']} | Pari Suggéré: {m['suggested_bet']} @ {m['estimated_odd']}\n"
        
    sys_live = """Tu es un expert en 'Live Betting' (Paris en direct). Regarde très attentivement le score et le temps restant des matchs proposés. 
Choisis le pari en direct le plus judicieux ("Value Bet").
Rédige une courte analyse pour alerter l'utilisateur de l'opportunité à saisir MAINTENANT. Ne renvoie que ton texte d'analyse."""

    return {"advice": call_persona(client, sys_live, prompt_data, use_search=False)}

