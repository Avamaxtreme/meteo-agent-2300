# modules/scraper_meteoblue.py
import requests


def get_meteoblue_forecast(lat: float, lon: float, api_key: str, altitude: int = 2300):
    """
    Получает прогноз meteoblue через Free Weather API (пакет basic-1h).
    Возвращает список словарей с почасовыми данными.
    """
    url = "https://my.meteoblue.com/packages/basic-1h"
    params = {
        "lat": lat,
        "lon": lon,
        "asl": altitude,
        "apikey": api_key,
        "format": "json"
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    # Структура данных meteoblue
    data_1h = data.get("data_1h", {})
    if not data_1h:
        raise ValueError("meteoblue вернул пустой ответ. Проверьте API-ключ.")

    times = data_1h.get("time", [])
    temps = data_1h.get("temperature", [])
    precips = data_1h.get("precipitation", [])
    winds = data_1h.get("windspeed", [])
    gusts = data_1h.get("windgust", [])
    clouds = data_1h.get("cloudcover", data_1h.get("totalcloudcover", []))

    if not times:
        raise ValueError("meteoblue: в ответе нет массива 'time'.")

    # Безопасный доступ к элементу списка
    def safe_get(lst, idx, default=None):
        if isinstance(lst, list) and 0 <= idx < len(lst):
            return lst[idx]
        return default

    records = []
    for i, t in enumerate(times):
        records.append({
            "time": t,
            "temp": safe_get(temps, i, 0.0),
            "precip": safe_get(precips, i, 0.0),
            "wind_speed": safe_get(winds, i, 0.0),
            "wind_gust": safe_get(gusts, i, 0.0),
            "clouds": safe_get(clouds, i, 0.0),
        })

    return records


if __name__ == "__main__":
    # Быстрый тест при запуске файла напрямую:
    #   python modules/scraper_meteoblue.py
    import json
    with open("config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    data = get_meteoblue_forecast(
        cfg["lat"], cfg["lon"], cfg["meteoblue_api_key"], cfg["altitude"]
    )
    print(f"OK, записей: {len(data)}")
    print(data[0])