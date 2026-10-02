# modules/scraper_openmeteo.py
import requests
from datetime import datetime, timedelta


OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"

# Параметры запроса для нашей точки
HOURLY_VARS = [
    "temperature_2m",
    "precipitation",
    "freezinglevel_height",
]


def get_openmeteo_forecast(lat: float, lon: float, altitude: int = 2300) -> list:
    """
    Получает почасовой прогноз с Open-Meteo.
    Возвращает список словарей в формате, совместимом с yr.no:
      [{"time": "...", "temp": ..., "precip_mm": ..., "freezing_level": ...}]
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "elevation": altitude,
        "hourly": ",".join(HOURLY_VARS),
        "timezone": "Europe/Moscow",
        "forecast_days": 3,
    }

    response = requests.get(OPENMETEO_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precips = hourly.get("precipitation", [])
    freezing = hourly.get("freezinglevel_height", [])

    if not times:
        raise ValueError("Open-Meteo вернул пустой ответ.")

    records = []
    for i, t in enumerate(times):
        records.append({
            "time": t,
            "temp": temps[i] if i < len(temps) else None,
            "precip_mm": precips[i] if i < len(precips) else 0.0,
            "freezing_level": freezing[i] if i < len(freezing) else None,
        })

    return records


if __name__ == "__main__":
    # Тестовый запуск
    import json
    with open("config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    data = get_openmeteo_forecast(cfg["lat"], cfg["lon"], cfg["altitude"])
    print(f"OK, записей: {len(data)}")
    print(data[0])