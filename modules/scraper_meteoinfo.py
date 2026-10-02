# modules/scraper_meteoinfo.py
"""
Скачивание прогностических карт с meteoinfo.ru через прямые URL.
Без Selenium — только requests. Быстро и надёжно.
"""
import os
import requests


BASE_URL = "https://meteoinfo.ru/hmc-input/mapsynop"

# Прогнозы приземного анализа на 24 / 36 / 60 часов
MAPS = {
    24: f"{BASE_URL}/Prognoz24h.png",
    36: f"{BASE_URL}/Prognoz36h.png",
    60: f"{BASE_URL}/Prognoz60h.png",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://meteoinfo.ru/prognosticheskie-karty",
}


def download_maps(download_dir: str = "downloads") -> list:
    """
    Скачивает три прогностические карты (24/36/60ч).
    Возвращает список словарей: [{"path": ..., "horizon": 24}, ...]
    """
    os.makedirs(download_dir, exist_ok=True)
    results = []

    for horizon, url in MAPS.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()

            path = os.path.join(download_dir, f"prognoz_{horizon}h.png")
            with open(path, "wb") as f:
                f.write(r.content)

            size_kb = len(r.content) // 1024
            print(f"[OK] {horizon}ч: {path} ({size_kb} KB)")
            results.append({"path": path, "horizon": horizon})

        except Exception as e:
            print(f"[FAIL] {horizon}ч: {e}")

    return results


if __name__ == "__main__":
    files = download_maps()
    print(f"\nСкачано карт: {len(files)}")
    for f in files:
        print(f"  +{f['horizon']}ч — {f['path']}")