# modules/map_analyzer.py
"""
Анализ синоптических карт Гидрометцентра через Gemini API.
Обрезает карту под Кавказ, отправляет в Gemini, получает описание.

Работает через SOCKS5-прокси (v2rayN) — обход геоблокировки Google
для российских IP.

ВАЖНО: карты российские (meteoinfo.ru), поэтому используются
российские обозначения барических образований:
  В — антициклон (высокое давление)
  Н — циклон (низкое давление)

Кэш: результат для каждой карты сохраняется в
`history/map_analysis_cache.json` и переиспользуется, пока не изменится
сам файл карты (по хешу). Это экономит ~80% запросов к Gemini.
"""
import base64
import hashlib
import json
import os
import time
import random
from PIL import Image
import httpx


# ============================================================
# Прокси (SOCKS5 из v2rayN)
# ============================================================
# Если v2rayN слушает на другом порту — поменяй здесь.
# Значение "socks5h://" — DNS через прокси, важно для обхода геоблокировки.
PROXY_URL = "socks5h://127.0.0.1:10808"


# ============================================================
# Модель Gemini
# ============================================================
#  Модель из доступных в твоём аккаунте (см. /v1beta/models).
#  Варианты (vision + generateContent):
#    - gemini-3.5-flash-lite  ← используется (500 RPD, 15 RPM)
#    - gemini-3.5-flash
#    - gemini-flash-latest
#    - gemini-2.5-flash
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-3.5-flash-lite:generateContent"
)


# === Параметры обрезки карты под Кавказ ===
CROP_BOX = (280, 480, 720, 963)   # (left, top, right, bottom)


# === Путь к кэшу ===
CACHE_FILE = os.path.join("history", "map_analysis_cache.json")


PROMPT_TEMPLATE = """Ты — профессиональный синоптик Гидрометцентра России.
Перед тобой ФРАГМЕНТ прогностической приземной карты погоды:
юг Европейской России, Чёрное море, Крым, Кавказ.

ТОЧКА ИНТЕРЕСА: широта {lat}, долгота {lon}, высота {altitude} м
(Западный Кавказ, район Красной Поляны, Снеголавинный пост «Горная Карусель»).
На карте эта точка — в районе Сочи, на восточном побережье Чёрного моря.

===========================================================
СПРАВОЧНИК СИМВОЛОВ (российский стандарт):
===========================================================
- В — антициклон (высокое давление), Н — циклон (низкое давление)
- Замкнутые изобары (концентрические линии) — центры циклонов/антициклонов
- Сгущение изобар — сильный ветер
- Линия с КРАСНЫМИ ПОЛУКРУГАМИ — тёплый фронт
- Линия с СИНИМИ ТРЕУГОЛЬНИКАМИ — холодный фронт
- Линия с полукругами и треугольниками попеременно — фронт окклюзии
- Зелёные зоны — осадки (дождь/снег)
- Точки — дождь, звёздочки — снег, пустые/тёмные треугольники — ливни
- Значок с молнией — гроза

===========================================================
ЗАДАЧА:
===========================================================
Опиши синоптическую ситуацию ДЛЯ ТОЧКИ (Сочи / Красная Поляна),
обязательно упомяни:

1. Где расположены циклоны и антициклоны относительно Чёрного моря
   и Кавказа, куда смещаются.
   ВАЖНО: буква «В» на этой карте — это АНТИЦИКЛОН,
   буква «Н» — это ЦИКЛОН. Не путай их.

2. Какие фронты видны на фрагменте, где проходят относительно Сочи
   (в каком направлении от точки), и приближаются или удаляются.

3. Есть ли зелёные зоны осадков над Чёрным морем, над Сочи,
   над Кавказом. Если есть — в какую сторону смещаются.

4. Что ожидать в точке в ближайшие часы: ухудшение или стабилизацию.

ВАЖНО:
- Если зелёной зоны осадков над точкой нет — так и скажи.
- Не выдумывай фронтов, которых не видишь.
- Отвечай конкретно: «северо-западнее Сочи проходит холодный фронт»,
  а не «в регионе имеются фронтальные разделы».

Ответ — 3–5 предложений по-русски, по делу.
"""


# ============================================================
# Кэш
# ============================================================
def _file_hash(path: str) -> str:
    """SHA1 файла — используется как ключ кэша."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[map_analyzer] Не удалось сохранить кэш: {e}")


# ============================================================
# Обрезка карты под Кавказ
# ============================================================
def _crop_map_to_caucasus(image_path: str) -> str:
    """Обрезает карту Гидрометцентра под Кавказ."""
    img = Image.open(image_path).convert("RGB")

    if img.width < 800 or img.height < 600:
        return image_path

    w, h = img.size
    left = int(CROP_BOX[0] / 1465 * w)
    top = int(CROP_BOX[1] / 963 * h)
    right = int(CROP_BOX[2] / 1465 * w)
    bottom = int(CROP_BOX[3] / 963 * h)

    cropped = img.crop((left, top, right, bottom))

    new_w = int(cropped.width * 2)
    new_h = int(cropped.height * 2)
    cropped = cropped.resize((new_w, new_h), Image.LANCZOS)

    out_path = image_path.rsplit(".", 1)[0] + "_cropped.jpg"
    cropped.save(out_path, "JPEG", quality=90)
    return out_path


# ============================================================
# POST через SOCKS5-прокси (httpx)
# ============================================================
def _post_with_retry(url, headers, data, timeout=180, max_attempts=4):
    """
    POST через SOCKS5-прокси с retry.
    429 → 10/20/40 сек, 503 → 5/10/20/40 сек + джиттер.
    """
    last_error = None

    # Транспорт httpx с SOCKS5-прокси.
    # socks5h:// — DNS тоже через прокси (важно для обхода блокировки).
    transport = httpx.HTTPTransport(proxy=PROXY_URL, retries=0)

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(transport=transport, timeout=timeout) as client:
                response = client.post(url, headers=headers, content=data)

            if response.status_code == 429:
                raise httpx.HTTPError(
                    "429 Too Many Requests (исчерпана квота Gemini)"
                )
            if response.status_code == 503:
                raise httpx.HTTPError(
                    "503 Service Unavailable (перегрузка сервера Gemini)"
                )
            response.raise_for_status()
            return response

        except (httpx.TimeoutException, httpx.ConnectError,
                httpx.HTTPError, httpx.RemoteProtocolError) as e:
            last_error = e
            err_text = str(e)
            print(f"[map_analyzer retry {attempt}/{max_attempts}] {err_text}")

            if attempt < max_attempts:
                if "429" in err_text:
                    delay = 10 * (2 ** (attempt - 1))       # 10, 20, 40
                else:
                    delay = 5 * (2 ** (attempt - 1)) + random.uniform(0, 1)
                print(f"  → пауза {delay:.1f} сек...")
                time.sleep(delay)
            else:
                if "429" in err_text:
                    print(
                        "  ⚠️  Исчерпана квота Gemini. "
                        "Проверь: https://aistudio.google.com/rate-limit"
                    )

    raise last_error


# ============================================================
# Основная функция — анализ одной карты (с кэшем)
# ============================================================
def analyze_map_with_gemini(image_path: str, api_key: str, lat: float,
                            lon: float, altitude: int,
                            use_cache: bool = True) -> str:
    """
    Обрезает карту под Кавказ и отправляет в Gemini (через прокси).
    Если файл уже анализировался (тот же хеш) и use_cache=True —
    возвращает сохранённый текст без обращения к API.
    """
    # 1. Обрезаем карту
    cropped_path = _crop_map_to_caucasus(image_path)

    # 2. Проверяем кэш по хешу обрезанной карты
    file_hash = _file_hash(cropped_path)

    cache = _load_cache()
    if use_cache and file_hash in cache:
        cached = cache[file_hash]
        age_hours = (time.time() - cached.get("saved_at_ts", 0)) / 3600
        print(f"[map_analyzer] CACHE HIT — {os.path.basename(image_path)} "
              f"(сохранено {age_hours:.1f} ч назад, запрос к Gemini не нужен)")
        return cached.get("text", "")

    print(f"[map_analyzer] CACHE MISS — {os.path.basename(image_path)}, "
          f"запрос к Gemini через прокси...")

    # 3. Читаем и кодируем в base64
    with open(cropped_path, "rb") as f:
        image_bytes = f.read()

    mime = (
        "image/jpeg"
        if cropped_path.lower().endswith((".jpg", ".jpeg"))
        else "image/png"
    )
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = PROMPT_TEMPLATE.format(lat=lat, lon=lon, altitude=altitude)

    # 4. Формируем payload
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": mime,
                        "data": image_b64
                    }
                }
            ]
        }],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1500
        }
    }

    # 5. Отправляем с retry — ключ в заголовке x-goog-api-key
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    response = _post_with_retry(
        GEMINI_URL,
        headers=headers,
        data=json.dumps(payload),
        timeout=180,
        max_attempts=4
    )
    data = response.json()

    # 6. Парсим ответ
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip()
    except (KeyError, IndexError) as e:
        raise ValueError(
            f"Не удалось разобрать ответ Gemini: {e}\n"
            f"Полный ответ: {json.dumps(data, ensure_ascii=False)[:500]}"
        )

    # 7. Сохраняем в кэш
    cache[file_hash] = {
        "text": text,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "saved_at_ts": time.time(),
        "source_file": os.path.basename(image_path),
        "model": GEMINI_URL.rsplit("/", 2)[-2],
    }
    _save_cache(cache)

    return text


# ============================================================
# Совместимость со старым API — несколько карт сразу
# ============================================================
def analyze_all_maps(image_paths: list, api_key: str, lat: float,
                     lon: float, altitude: int) -> str:
    """
    Анализирует несколько карт и объединяет описания.
    Между запросами к API — пауза 15 сек (чтобы не упереться в 5 RPM).
    Если карта есть в кэше — пауза не нужна.
    """
    descriptions = []
    for i, path in enumerate(image_paths, 1):
        try:
            text = analyze_map_with_gemini(path, api_key, lat, lon, altitude)
            descriptions.append(f"**Карта {i}:** {text}")
        except Exception as e:
            descriptions.append(f"**Карта {i}:** не удалось проанализировать ({e})")

        if i < len(image_paths):
            print("  ⏸  пауза 15 сек между картами...")
            time.sleep(15)

    return "\n\n".join(descriptions)


# ============================================================
# Утилита: очистить кэш
# ============================================================
def clear_cache():
    """Удаляет весь кэш — например, если хочешь переанализировать."""
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
        print("[map_analyzer] Кэш очищен")


# ============================================================
# CLI для тестирования
# ============================================================
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python modules/map_analyzer.py <путь_к_картинке>")
        print("  python modules/map_analyzer.py --clear-cache")
        sys.exit(1)

    if sys.argv[1] == "--clear-cache":
        clear_cache()
        sys.exit(0)

    with open("config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)

    result = analyze_map_with_gemini(
        sys.argv[1], cfg["gemini_api_key"],
        cfg["lat"], cfg["lon"], cfg["altitude"]
    )
    print("=" * 60)
    print(result)
    print("=" * 60)
