import requests
from typing import Optional, Dict

def enrich_nonprofit(name: str, state: Optional[str] = None) -> Dict:
    """Enrich nonprofit data using ProPublica API"""
    try:
        # ProPublica endpoint
        url = "https://projects.propublica.org/nonprofits/api/v2/search.json"
        params = {"q": name}
        if state:
            params["state[id]"] = state
            
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get("organizations"):
                org = data["organizations"][0]  # Take first match
                return {
                    "ein": org.get("ein"),
                    "name": org.get("name"),
                    "city": org.get("city"),
                    "state": org.get("state"),
                    "source": "ProPublica Nonprofit API",
                    "status": "success"
                }
        
        return {"status": "not_found", "source": "ProPublica Nonprofit API"}
        
    except requests.Timeout:
        return {"status": "error", "reason": "API timeout", "source": "ProPublica"}
    except Exception as e:
        return {"status": "error", "reason": str(e), "source": "ProPublica"}