# modules/history.py
"""
Модуль истории прогнозов и фактов.
- Парсит CSV со станции 2070 м.
- Сохраняет прогнозы и факты в JSON (прогнозы — список версий за день).
- Считает точность каждого источника.
- Пересчитывает веса для analyzer.py.

Ключевые принципы:
1) PR10 на станции 2070м = сумма осадков за 10 минут (мм).
   Сумма PR10 за час = часовые осадки в мм. Делить НЕ надо.
2) Прогноз покрывает окно [saved_at, saved_at + horizon_h], а факт — календарный день.
   Сравнение осадков идёт ТОЛЬКО по пересечению окон.
3) Часовые осадки факта хранятся в fact["precip_hourly"] как {"0": 2.1, ..., "23": 0.0}.
4) accuracy_report(days=None) — накопительный режим: считает ВСЕ доступные дни.
   accuracy_report(days=N)    — скользящее окно N дней.
"""
import os
import json
import glob
from datetime import datetime, timedelta
import pandas as pd


HISTORY_DIR = "history"
FACTS_DIR = "facts"
FORECASTS_FILE = os.path.join(HISTORY_DIR, "forecasts.json")
FACTS_FILE = os.path.join(HISTORY_DIR, "facts.json")
WEIGHTS_FILE = os.path.join(HISTORY_DIR, "weights.json")

# Приведение температуры к высоте 2300 м (станция на 2070 м)
TEMP_ADJUST_2300 = 1.38

# Порог "есть осадки" — ниже считаем шумом
PRECIP_EPS = 0.05


# ============================================================
# УТИЛИТЫ
# ============================================================

def _ensure_dirs():
    os.makedirs(HISTORY_DIR, exist_ok=True)
    os.makedirs(FACTS_DIR, exist_ok=True)


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[history] Ошибка чтения {path}: {e}")
        return default


def _save_json(path, data):
    _ensure_dirs()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_iso_dt(raw):
    """
    Безопасный парсинг ISO-времени из прогнозов разных источников.
    Поддерживает:
      "2026-09-22T07:00:00Z"
      "2026-09-22T07:00"
      "2026-09-22 07:00"
    Возвращает naive datetime или None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    s = s.replace("Z", "").replace("+00:00", "")
    s = s.replace(" ", "T")
    if "." in s:
        s = s.split(".")[0]
    try:
        return datetime.fromisoformat(s)
    except Exception:
        try:
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        except Exception:
            try:
                return datetime.strptime(s, "%Y-%m-%dT%H:%M")
            except Exception:
                return None


# ============================================================
# СОХРАНЕНИЕ ПРОГНОЗА — НАКАПЛИВАЕТ ВСЕ ВЕРСИИ ЗА ДЕНЬ
# ============================================================

def save_forecast(date_str, horizons_data, sources_raw):
    """
    Сохраняет прогноз на дату.
    Каждый вызов ДОБАВЛЯЕТ новую версию в список predictions.
    Старые версии НЕ перезаписываются.
    """
    _ensure_dirs()
    forecasts = _load_json(FORECASTS_FILE, {})

    if date_str not in forecasts:
        forecasts[date_str] = {"predictions": []}
    elif "predictions" not in forecasts[date_str]:
        old = forecasts[date_str]
        forecasts[date_str] = {"predictions": [old]}

    forecasts[date_str]["predictions"].append({
        "saved_at": datetime.now().isoformat(),
        "horizons": horizons_data,
        "sources_raw": sources_raw,
    })

    _save_json(FORECASTS_FILE, forecasts)


def get_saved_versions(date_str=None):
    """Возвращает список сохранённых версий прогноза."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    forecasts = _load_json(FORECASTS_FILE, {})
    day = forecasts.get(date_str, {})

    if isinstance(day, dict) and "predictions" in day:
        return day["predictions"]
    elif day:
        return [day]
    return []


# ============================================================
# ПАРСИНГ CSV СО СТАНЦИИ 2070 М
# ============================================================

def parse_station_csv(csv_path):
    """
    Читает CSV станции 2070 м (CP1251, sep=';', decimal=',').
    Первая колонка содержит имя файла (s37106_2026-09-19) —
    переименовываем её в 'time'.
    """
    df = pd.read_csv(
        csv_path,
        sep=";",
        encoding="cp1251",
        decimal=",",
        na_values=["", "-"],
    )

    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
    df.columns = [c.strip() for c in df.columns]

    if len(df.columns) > 0 and df.columns[0] != "time":
        df = df.rename(columns={df.columns[0]: "time"})

    needed = [
        "time", "T", "Td", "R", "WD", "WS", "Wmax",
        "PR10", "I", "Imax", "WW", "P",
    ]
    existing = [c for c in needed if c in df.columns]
    df = df[existing]

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], format="%H:%M", errors="coerce")

    for col in ("T", "Td", "R", "WD", "WS", "Wmax", "PR10", "I", "Imax", "WW", "P"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def summarize_station_day(df):
    """
    Суточные итоги по станции.
    Осадки — по PR10 (мм за 10 мин → сумма за сутки).
    Добавляет precip_hourly — словарь {"0".."23": мм}.
    """
    result = {}

    # --- Температура ---
    if "T" in df.columns and df["T"].notna().any():
        t_avg = float(df["T"].mean())
        t_min = float(df["T"].min())
        t_max = float(df["T"].max())

        result["t_avg_2070"] = round(t_avg, 1)
        result["t_min_2070"] = round(t_min, 1)
        result["t_max_2070"] = round(t_max, 1)

        result["t_avg_2300"] = round(t_avg - TEMP_ADJUST_2300, 1)
        result["t_min_2300"] = round(t_min - TEMP_ADJUST_2300, 1)
        result["t_max_2300"] = round(t_max - TEMP_ADJUST_2300, 1)

        if "time" in df.columns:
            try:
                idx_min = df["T"].idxmin()
                idx_max = df["T"].idxmax()
                result["t_min_time"] = df.loc[idx_min, "time"].strftime("%H:%M")
                result["t_max_time"] = df.loc[idx_max, "time"].strftime("%H:%M")
            except Exception:
                pass

    # --- Осадки: PR10 ---
    if "PR10" in df.columns and df["PR10"].notna().any():
        total_mm = float(df["PR10"].sum())
        result["precip_total"] = round(total_mm, 2)

        n_records = int(df["PR10"].notna().sum())
        if n_records > 0:
            hours = n_records * 10.0 / 60.0
            result["precip_intensity_avg"] = (
                round(total_mm / hours, 2) if hours > 0 else 0.0
            )

        if "Imax" in df.columns and df["Imax"].notna().any():
            result["precip_intensity_max"] = round(float(df["Imax"].max()), 1)
        elif "I" in df.columns and df["I"].notna().any():
            result["precip_intensity_max"] = round(float(df["I"].max()), 1)

        if "T" in df.columns and df["T"].notna().any():
            t_avg = float(df["T"].mean())
            if total_mm < 0.1:
                result["precip_type"] = "нет"
            elif t_avg < -1:
                result["precip_type"] = "снег"
            elif t_avg > 2:
                result["precip_type"] = "дождь"
            else:
                result["precip_type"] = "смешанные"

        # Часовой профиль осадков
        if "time" in df.columns:
            hourly = {}
            for hour in range(24):
                hour_data = df[df["time"].dt.hour == hour]
                hourly[str(hour)] = round(float(hour_data["PR10"].sum()), 2)
            result["precip_hourly"] = hourly

        # Времена и интервалы осадков
        if "time" in df.columns:
            precip_df = df[df["PR10"] > PRECIP_EPS].copy()
            if not precip_df.empty:
                precip_df["hour"] = precip_df["time"].dt.hour
                result["precip_hours"] = sorted(precip_df["hour"].unique().tolist())
                result["precip_first_time"] = precip_df["time"].min().strftime("%H:%M")
                result["precip_last_time"] = precip_df["time"].max().strftime("%H:%M")

                intervals = []
                current = None
                for _, row in precip_df.iterrows():
                    t = row["time"]
                    mm = float(row["PR10"])
                    if current is None:
                        current = {"start": t, "end": t, "mm": mm}
                    else:
                        if (t - current["end"]).total_seconds() <= 600:
                            current["end"] = t
                            current["mm"] += mm
                        else:
                            intervals.append({
                                "start": current["start"].strftime("%H:%M"),
                                "end": current["end"].strftime("%H:%M"),
                                "mm": round(current["mm"], 2),
                            })
                            current = {"start": t, "end": t, "mm": mm}

                if current is not None:
                    intervals.append({
                        "start": current["start"].strftime("%H:%M"),
                        "end": current["end"].strftime("%H:%M"),
                        "mm": round(current["mm"], 2),
                    })

                result["precip_intervals"] = intervals
            else:
                result["precip_hours"] = []
                result["precip_intervals"] = []

    # --- Ветер ---
    if "WS" in df.columns and df["WS"].notna().any():
        result["wind_avg"] = round(float(df["WS"].mean()), 1)
    if "Wmax" in df.columns and df["Wmax"].notna().any():
        result["wind_max"] = round(float(df["Wmax"].max()), 1)

    return result


def load_facts_from_folder(force_reload=False):
    """
    Обрабатывает все CSV из facts/, дописывает новые в facts.json.
    Если force_reload=True — перечитывает ВСЕ файлы заново
    (полезно после добавления новых полей, например precip_hourly).
    """
    _ensure_dirs()
    facts = _load_json(FACTS_FILE, {})
    processed = 0

    for csv_path in sorted(glob.glob(os.path.join(FACTS_DIR, "*.csv"))):
        filename = os.path.basename(csv_path)
        try:
            date_str = filename.replace("s37106_", "").replace(".csv", "")
        except Exception:
            continue

        if not force_reload and date_str in facts:
            continue

        try:
            df = parse_station_csv(csv_path)
            summary = summarize_station_day(df)
            summary["source"] = "станция 2070м"
            summary["raw_file"] = filename
            facts[date_str] = summary
            processed += 1
        except Exception as e:
            print(f"[history] Ошибка при чтении {filename}: {e}")

    if processed > 0:
        _save_json(FACTS_FILE, facts)

    return processed


# ============================================================
# СРАВНЕНИЕ ПРОГНОЗА С ФАКТОМ
# ============================================================

def _pick_best_prediction(predictions, fact_start, fact_end, horizon_h):
    """
    Среди версий прогноза выбирает ту, у которой максимальное
    пересечение окна [saved_at, saved_at + horizon_h] с [fact_start, fact_end].
    Возвращает (best_pred, saved_at, end_dt, overlap_h) или (None, ...).
    """
    best = None
    best_overlap_h = 0.0
    best_saved = None
    best_end = None

    for pred in predictions:
        saved_at = _parse_iso_dt(pred.get("saved_at"))
        if saved_at is None:
            continue

        pred_end = saved_at + timedelta(hours=horizon_h)
        overlap_start = max(saved_at, fact_start)
        overlap_end = min(pred_end, fact_end)
        overlap_h = (overlap_end - overlap_start).total_seconds() / 3600.0

        if overlap_h > best_overlap_h:
            best_overlap_h = overlap_h
            best = pred
            best_saved = saved_at
            best_end = pred_end

    return best, best_saved, best_end, best_overlap_h


def _extract_source_totals(forecasts, fact_date, source_name, horizon_h, fact=None):
    """
    Достаёт данные прогноза для источника и горизонта.
    Если за дату сохранено НЕСКОЛЬКО прогнозов — берётся тот,
    у которого максимальное пересечение с окном факта.

    Возвращает dict:
      t_avg, t_min, t_max       — прогноз в окне
      precip_total              — прогноз осадков в окне
      precip_fact_window        — факт осадков в ТОМ ЖЕ окне (если fact передан)
      saved_at, overlap_hours
    """
    if fact_date not in forecasts:
        return None

    forecast_day = forecasts[fact_date]
    if isinstance(forecast_day, dict) and "predictions" in forecast_day:
        predictions = forecast_day["predictions"]
    else:
        predictions = [forecast_day]

    if not predictions:
        return None

    try:
        fact_start = datetime.strptime(fact_date, "%Y-%m-%d")
    except Exception:
        return None
    fact_end = fact_start + timedelta(hours=23, minutes=59, seconds=59)

    best, saved_at, end, overlap_h = _pick_best_prediction(
        predictions, fact_start, fact_end, horizon_h
    )
    if best is None or overlap_h < 1:
        return None

    sources_raw = best.get("sources_raw", {})
    records = sources_raw.get(source_name, [])
    if not records:
        return None

    t_start_actual = max(saved_at, fact_start)
    t_end_actual = min(end, fact_end)

    temps = []
    precips = []

    for r in records:
        t = _parse_iso_dt(r.get("time"))
        if t is None:
            continue
        if t_start_actual <= t <= t_end_actual:
            if r.get("temp") is not None:
                temps.append(r["temp"])
            for key in ("precip_mm", "precip"):
                if r.get(key) is not None:
                    precips.append(r[key])
                    break

    if not temps:
        return None

    precip_pred = sum(precips) if precips else 0.0

    # Факт осадков — за то же окно, если есть часовые данные
    precip_fact = None
    if fact and "precip_hourly" in fact:
        precip_fact = 0.0
        for hour_str, mm in fact["precip_hourly"].items():
            try:
                hour_int = int(hour_str)
            except (TypeError, ValueError):
                continue
            h_start = fact_start + timedelta(hours=hour_int)
            h_end = h_start + timedelta(hours=1)
            if h_end > t_start_actual and h_start < t_end_actual:
                precip_fact += float(mm)
        precip_fact = round(precip_fact, 2)

    return {
        "t_avg": sum(temps) / len(temps),
        "t_min": min(temps),
        "t_max": max(temps),
        "precip_total": round(precip_pred, 2),
        "precip_fact_window": precip_fact,
        "saved_at": best["saved_at"],
        "overlap_hours": overlap_h,
    }


def accuracy_report(days=None, horizons=(24,)):
    """
    Отчёт точности каждого источника.

    Параметр days:
      None — НАКОПИТЕЛЬНЫЙ режим: все дни с самого раннего факта.
      N    — скользящее окно N последних календарных дней.

    Осадки сравниваются В ОДНОМ ОКНЕ (прогноз vs факт за то же время).
    """
    forecasts = _load_json(FORECASTS_FILE, {})
    facts = _load_json(FACTS_FILE, {})

    sources = ["yr.no", "meteoblue", "Open-Meteo"]

    stats = {src: {"temp_errors": [], "precip_errors": []} for src in sources}

    # --- Определяем cutoff ---
    if days is None:
        # Накопительный режим: от самого раннего дня в фактах
        if facts:
            try:
                earliest = min(facts.keys())
                cutoff = datetime.strptime(earliest, "%Y-%m-%d")
            except Exception:
                cutoff = datetime(1970, 1, 1)
        else:
            cutoff = datetime(1970, 1, 1)
    else:
        # Скользящее окно: начало календарного дня, N дней назад
        cutoff = (datetime.now() - timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    for date_str, fact in facts.items():
        try:
            fact_dt = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue
        if fact_dt < cutoff:
            continue

        actual_t_avg = fact.get("t_avg_2300")
        actual_precip_full = fact.get("precip_total")
        if actual_t_avg is None:
            continue

        for src in sources:
            for h in horizons:
                pred = _extract_source_totals(
                    forecasts, date_str, src, h, fact=fact
                )
                if pred is None:
                    continue
                if pred.get("overlap_hours", 0) < 6:
                    continue

                temp_err = abs(pred["t_avg"] - actual_t_avg)
                stats[src]["temp_errors"].append(temp_err)

                precip_fact_window = pred.get("precip_fact_window")
                if precip_fact_window is not None:
                    actual_precip = precip_fact_window
                else:
                    actual_precip = actual_precip_full

                if actual_precip is not None and pred["precip_total"] is not None:
                    precip_err = abs(pred["precip_total"] - actual_precip)
                    stats[src]["precip_errors"].append(precip_err)

    report = {}
    for src in sources:
        te = stats[src]["temp_errors"]
        pe = stats[src]["precip_errors"]
        report[src] = {
            "temp_mae": round(sum(te) / len(te), 2) if te else None,
            "precip_mae": round(sum(pe) / len(pe), 2) if pe else None,
            "n": len(te),
            "n_temp": len(te),
            "n_precip": len(pe),
        }
    return report


# ============================================================
# КАЛИБРОВКА ВЕСОВ
# ============================================================

def recalibrate_weights(days=None, temp_weight=0.7, precip_weight=0.3):
    """
    Пересчитывает веса источников по точности.

    Параметр days:
      None — использовать ВСЕ доступные дни фактов (накопительно).
      N    — использовать последние N календарных дней.

    Итоговая ошибка = temp_weight * temp_mae + precip_weight * precip_mae
    (если precip_mae нет — используется только temp_mae).
    """
    report = accuracy_report(days=days)

    inverse_errors = {}
    for src, data in report.items():
        t_mae = data.get("temp_mae")
        p_mae = data.get("precip_mae")
        n_temp = data.get("n_temp", 0)

        if t_mae is None or n_temp < 3:
            continue

        if p_mae is not None:
            combined = temp_weight * t_mae + precip_weight * p_mae
        else:
            combined = t_mae

        inverse_errors[src] = 1.0 / (combined + 0.1)

    if not inverse_errors:
        return None

    total = sum(inverse_errors.values())
    weights = {src: round(w / total, 2) for src, w in inverse_errors.items()}

    s = sum(weights.values())
    if s > 0:
        weights = {k: round(v / s, 2) for k, v in weights.items()}

    # Считаем, сколько реально дней попало в выборку (для UI)
    facts = _load_json(FACTS_FILE, {})
    n_days = len(facts)

    _ensure_dirs()
    _save_json(WEIGHTS_FILE, {
        "updated_at": datetime.now().isoformat(),
        "weights": weights,
        "based_on_days": days,
        "facts_in_base": n_days,
        "temp_weight": temp_weight,
        "precip_weight": precip_weight,
        "report": report,
    })
    return weights


def load_weights(default=(0.60, 0.25, 0.15)):
    """Возвращает кортеж весов (yr.no, meteoblue, Open-Meteo)."""
    if not os.path.exists(WEIGHTS_FILE):
        return default

    data = _load_json(WEIGHTS_FILE, {})
    weights = data.get("weights", {})
    if not weights:
        return default

    return (
        weights.get("yr.no", default[0]),
        weights.get("meteoblue", default[1]),
        weights.get("Open-Meteo", default[2]),
    )