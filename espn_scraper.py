import sys
import subprocess
import json

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    import requests
except ImportError:
    install('requests')
    import requests

def get_real_soccer_matches():
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        matches = []
        for event in data.get("events", []):
            try:
                competitors = event["competitions"][0]["competitors"]
                home_team = None
                away_team = None
                for team in competitors:
                    if team["homeAway"] == "home":
                        home_team = team["team"]["name"]
                    else:
                        away_team = team["team"]["name"]
                
                # ESPN API doesn't provide accurate betting odds for free easily
                # We will simulate the odds purely for the demonstration of the AI Council
                # based on team ranks (we use a simple hash to make it consistent)
                odds_1 = round(1.1 + (hash(home_team) % 200) / 100.0, 2)
                odds_2 = round(1.1 + (hash(away_team) % 200) / 100.0, 2)
                odds_N = round((odds_1 + odds_2) / 2 + 1.5, 2)
                
                if home_team and away_team:
                    matches.append({
                         "id": event["id"],
                         "sport": "Football",
                         "competition": "Premier League (via ESPN)",
                         "homeTeam": home_team,
                         "awayTeam": away_team,
                         "date": event["date"][:16].replace("T", " "),
                         "odds": {
                             "1": odds_1,
                             "N": odds_N,
                             "2": odds_2
                         }
                    })
            except Exception as e:
                continue
        return matches
    except Exception as e:
        print(f"Failed to fetch live matches: {e}")
        return []

if __name__ == "__main__":
    print(json.dumps(get_real_soccer_matches(), indent=2))
