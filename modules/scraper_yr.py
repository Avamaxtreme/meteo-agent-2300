# modules/scraper_yr.py
import requests
from datetime import datetime

HEADERS = {
    "User-Agent": "MeteoAgent/1.0 github.com/yourname/meteo-agent your-maxtreme@bk.ru"
}

def get_yr_api(lat: float, lon: float, altitude: int = 2300):
    """
    Получает прогноз через API MET Norway (yr.no).
    Возвращает список почасовых записей.
    """
    url = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
    params = {
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "altitude": altitude
    }
    
    response = requests.get(url, params=params, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    
    timeseries = data.get("properties", {}).get("timeseries", [])
    
    records = []
    for entry in timeseries:
        time = entry["time"]
        details = entry["data"]["instant"]["details"]
        
        # Осадки за следующий час
        next_1h = entry["data"].get("next_1_hours", {})
        precip = next_1h.get("details", {}).get("precipitation_amount", 0)
        symbol = next_1h.get("summary", {}).get("symbol_code", "unknown")
        
        records.append({
            "time": time,
            "temp": details.get("air_temperature"),
            "wind_speed": details.get("wind_speed"),
            "humidity": details.get("relative_humidity"),
            "precip_mm": precip,
            "symbol": symbol
        })
    
    return records