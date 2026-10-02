# modules/analyzer.py
from datetime import datetime, timedelta


def calculate_zero_isotherm(temp_2300: float, altitude: int = 2300) -> int:
    """Высота нулевой изотермы по градиенту 0.6°C/100м."""
    if temp_2300 >= 0:
        return int(altitude + (temp_2300 / 0.6) * 100)
    return int(altitude - (abs(temp_2300) / 0.6) * 100)


def _parse_time(t: str):
    """Парсит время из yr.no ('...Z'), meteoblue и Open-Meteo ('YYYY-MM-DD HH:MM')."""
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.strptime(t, "%Y-%m-%d %H:%M")
        except Exception:
            return None


def _collect_window(records: list, start_hours: int, end_hours: int, keys: dict):
    """Собирает значения из записей в окне [now + start_hours; now + end_hours]."""
    now = datetime.now()
    t_start = now + timedelta(hours=start_hours)
    t_end = now + timedelta(hours=end_hours)

    result = {k: [] for k in keys}
    result["__times__"] = []

    for r in records:
        t = _parse_time(r.get("time", ""))
        if t is None:
            continue
        t_naive = t.replace(tzinfo=None)
        if t_start <= t_naive <= t_end:
            for out_key, field in keys.items():
                val = r.get(field)
                if val is not None:
                    result[out_key].append(val)
            result["__times__"].append(t_naive)

    return result


def _time_of_extreme(records: list, start_hours: int, end_hours: int,
                     field: str, mode: str = "min"):
    """Возвращает время экстремума (min или max) поля в окне."""
    now = datetime.now()
    t_start = now + timedelta(hours=start_hours)
    t_end = now + timedelta(hours=end_hours)

    best_val = None
    best_time = None
    for r in records:
        t = _parse_time(r.get("time", ""))
        if t is None:
            continue
        t_naive = t.replace(tzinfo=None)
        if not (t_start <= t_naive <= t_end):
            continue
        val = r.get(field)
        if val is None:
            continue
        if best_val is None:
            best_val, best_time = val, t_naive
        elif mode == "min" and val < best_val:
            best_val, best_time = val, t_naive
        elif mode == "max" and val > best_val:
            best_val, best_time = val, t_naive

    return best_val, best_time


def _weighted_avg_multi(sources: list, weights: list):
    """
    Взвешенное среднее для нескольких источников.
    sources = [[v1, v2, ...], [v1, v2, ...], ...]
    weights = [0.6, 0.25, 0.15]
    Пропускает пустые источники и автоматически нормализует веса.
    """
    valid = [(vals, w) for vals, w in zip(sources, weights) if vals]
    if not valid:
        return None

    total_w = sum(w * len(vals) for vals, w in valid)
    if total_w == 0:
        return None

    weighted_sum = sum(sum(vals) * w for vals, w in valid)
    return weighted_sum / total_w


def _check_agreement_multi(sources_temps: dict, temp_threshold: float = 3.0):
    """
    Проверяет согласованность нескольких источников по температуре.
    sources_temps = {"yr.no": [...], "meteoblue": [...], "Open-Meteo": [...]}
    """
    avgs = {}
    for name, vals in sources_temps.items():
        if vals:
            avgs[name] = sum(vals) / len(vals)

    if len(avgs) < 2:
        return "ok", None

    names = list(avgs.keys())
    max_diff = 0
    pair = None
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            diff = abs(avgs[names[i]] - avgs[names[j]])
            if diff > max_diff:
                max_diff = diff
                pair = (names[i], names[j])

    if max_diff > temp_threshold and pair:
        return "warn", (
            f"{pair[0]} и {pair[1]} расходятся по температуре на "
            f"{max_diff:.1f}°C "
            f"({pair[0]} {avgs[pair[0]]:+.1f}, {pair[1]} {avgs[pair[1]]:+.1f})"
        )

    return "ok", None


def analyze_forecast(yr_data: list, meteoblue_data: list, config: dict,
                     om_data: list = None, weights: tuple = None) -> dict:
    """
    Анализ с весовым усреднением температур.
    weights = (yr.no, meteoblue, Open-Meteo); если None — дефолт (0.60, 0.25, 0.15).
    Осадки — консервативная оценка (максимум по источникам).
    Прогноз на 24 / 36 / 60 часов.
    """
    if weights is None:
        weights = (0.60, 0.25, 0.15)
    w_yr, w_mb, w_om = weights

    horizons = [24, 36, 60]
    result = {"forecast": {}, "warnings": []}

    yr_fields = {"temp": "temp", "precip": "precip_mm"}
    mb_fields = {"temp": "temp", "precip": "precip"}
    om_fields = {"temp": "temp", "precip": "precip_mm"}

    prev_h = 0
    prev_precip_sum = 0.0

    for h in horizons:
        yr_win = _collect_window(yr_data, 0, h, yr_fields)
        mb_win = _collect_window(meteoblue_data, 0, h, mb_fields)
        om_win = {"temp": [], "precip": []}
        if om_data:
            om_win = _collect_window(om_data, 0, h, om_fields)

        # --- Температура: min/max по объединению, avg — взвешенный ---
        all_temps = yr_win["temp"] + mb_win["temp"] + om_win["temp"]
        t_min = min(all_temps) if all_temps else None
        t_max = max(all_temps) if all_temps else None

        t_avg = _weighted_avg_multi(
            [yr_win["temp"], mb_win["temp"], om_win["temp"]],
            [w_yr, w_mb, w_om]
        )

        _, t_min_time = _time_of_extreme(yr_data, 0, h, "temp", "min")
        _, t_max_time = _time_of_extreme(yr_data, 0, h, "temp", "max")

        # --- Осадки: суммируем по каждому источнику отдельно ---
        yr_precip_sum = sum(yr_win["precip"]) if yr_win["precip"] else 0.0
        mb_precip_sum = sum(mb_win["precip"]) if mb_win["precip"] else 0.0
        om_precip_sum = sum(om_win["precip"]) if om_win["precip"] else 0.0

        # Консервативная оценка: максимум из трёх источников
        precip_sum = max(yr_precip_sum, mb_precip_sum, om_precip_sum)

        precip_delta = precip_sum - prev_precip_sum
        interval_hours = h - prev_h
        interval_intensity = precip_delta / interval_hours if interval_hours else 0.0
        precip_avg_per_h = precip_sum / h if h else 0.0

        # --- Тип осадков ---
        if t_avg is None:
            precip_type = "нет данных"
        elif precip_sum < 0.1:
            precip_type = "нет"
        elif t_avg < -1:
            precip_type = "снег"
        elif t_avg > 2:
            precip_type = "дождь"
        else:
            precip_type = "смешанные"

        # --- Нулевая изотерма ---
        zero_iso_min = calculate_zero_isotherm(t_min or 0, config["altitude"])
        zero_iso_max = calculate_zero_isotherm(t_max or 0, config["altitude"])
        zero_iso_avg = calculate_zero_isotherm(t_avg or 0, config["altitude"])

        # --- Проверка согласованности ---
        agreement_status, agreement_msg = _check_agreement_multi({
            "yr.no": yr_win["temp"],
            "meteoblue": mb_win["temp"],
            "Open-Meteo": om_win["temp"],
        })

        # --- Формируем текст ---
        lines = [f"### Прогноз +{h} часов", ""]

        if agreement_status == "warn":
            lines.append(f"⚠️ *{agreement_msg}*")
            result["warnings"].append(f"⚠️ +{h}ч: {agreement_msg}")

        if t_min is not None:
            lines.append("**🌡️ Температура на 2300 м:**")
            lines.append(f"- Средняя (взвеш.): **{t_avg:+.1f}°C**")
            min_str = f"- Минимум: **{t_min:+.1f}°C**"
            if t_min_time:
                min_str += f" (в {t_min_time.strftime('%H:%M')})"
            lines.append(min_str)
            max_str = f"- Максимум: **{t_max:+.1f}°C**"
            if t_max_time:
                max_str += f" (в {t_max_time.strftime('%H:%M')})"
            lines.append(max_str)
            lines.append("")

        # --- Осадки с раскладкой по источникам ---
        lines.append(f"**🌧️ Осадки:**")
        lines.append(f"- Всего за 0–{h}ч (консерв.): **{precip_sum:.1f} мм**")

        precip_sources = (
            f"  yr.no: {yr_precip_sum:.1f} мм · "
            f"meteoblue: {mb_precip_sum:.1f} мм"
        )
        if om_data:
            precip_sources += f" · Open-Meteo: {om_precip_sum:.1f} мм"
        lines.append(precip_sources)

        lines.append(f"  (средняя интенсивность {precip_avg_per_h:.2f} мм/ч)")

        if prev_h > 0:
            lines.append(
                f"- **В интервале {prev_h}–{h}ч: {precip_delta:+.1f} мм** "
                f"(интенсивность {interval_intensity:.2f} мм/ч)"
            )
        else:
            lines.append(f"- **В интервале 0–{h}ч: {precip_delta:+.1f} мм**")

        lines.append(f"- Тип: **{precip_type}**")
        lines.append("")

        lines.append("**🧮 Высота нулевой изотермы:**")
        lines.append(f"- При средней T: ~{zero_iso_avg} м")
        lines.append(f"- При минимуме: ~{zero_iso_min} м")
        lines.append(f"- При максимуме: ~{zero_iso_max} м")

        # --- Предупреждения ---
        if t_min is not None and t_min < -10:
            result["warnings"].append(f"🥶 +{h}ч: мороз до {t_min:.1f}°C")
        if t_max is not None and t_max > 5 and precip_type == "снег":
            result["warnings"].append(
                f"🌡️ +{h}ч: днём плюс при снегопаде — риск мокрых лавин"
            )
        if precip_sum > 20:
            result["warnings"].append(
                f"🌧️ +{h}ч: суммарные осадки {precip_sum:.1f} мм — риск лавин"
            )
        if interval_intensity > 1.5 and precip_delta > 5:
            result["warnings"].append(
                f"⛈️ +{h}ч: интенсивный ливень в интервале "
                f"{prev_h}–{h}ч ({precip_delta:.1f} мм)"
            )

        result["forecast"][f"{h}h"] = "\n".join(lines)

        prev_h = h
        prev_precip_sum = precip_sum

    return result