# app.py
import streamlit as st
import json
import os
import re
from datetime import datetime, timedelta
import pandas as pd
from modules.scraper_yr import get_yr_api
from modules.scraper_meteoblue import get_meteoblue_forecast
from modules.scraper_openmeteo import get_openmeteo_forecast
from modules.analyzer import analyze_forecast
from modules.scraper_meteoinfo import download_maps
from modules.map_analyzer import analyze_map_with_gemini
from modules.history import (
    save_forecast, load_facts_from_folder,
    accuracy_report, recalibrate_weights, load_weights,
    get_saved_versions,
)

# ============================================================
# Конфиг
# ============================================================
with open("config.json", "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

st.set_page_config(
    page_title="Метео-агент 2300м",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# ТЕМА: светлая / тёмная
# ============================================================
if "ui_theme" not in st.session_state:
    st.session_state["ui_theme"] = "light"


def _inject_css(theme: str):
    """Инжектит CSS в зависимости от выбранной темы."""
    if theme == "dark":
        css = """
        <style>
            .stApp { background-color: #0e1117; color: #e8eaed; }
            section[data-testid="stSidebar"] {
                background-color: #1a1d24;
            }
            section[data-testid="stSidebar"] * { color: #e8eaed; }
            .stButton > button {
                background-color: #1c2733;
                color: #e8eaed;
                border: 1px solid #4fa3f0;
            }
            .stButton > button:hover {
                background-color: #2a3a4a;
                border-color: #6ec1ff;
            }
            .stExpander {
                background-color: #1a1d24 !important;
                border: 1px solid #2a2e36 !important;
            }
            .stMetric { color: #e8eaed; }
            h1, h2, h3, h4, h5 { color: #e8eaed !important; }
            p, span, label, div { color: #e8eaed; }

            .main-title {
                background: linear-gradient(90deg, #4fa3f0 0%, #4caf50 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                font-size: 2.4rem;
                font-weight: 800;
                margin-bottom: 0;
                padding-bottom: 0;
            }
            .subtitle {
                color: #4fa3f0;
                font-size: 1.7rem;
                font-weight: 700;
                margin-top: 0.3rem;
                margin-bottom: 1.6rem;
                padding-left: 0.8rem;
                border-left: 5px solid #4caf50;
                letter-spacing: 0.2px;
            }
            .source-badge {
                display: inline-block;
                padding: 0.4rem 0.8rem;
                border-radius: 0.5rem;
                font-size: 0.85rem;
                font-weight: 600;
                margin-right: 0.5rem;
            }
            .badge-ok   { background: #1e3a24; color: #6ee787; }
            .badge-err  { background: #3a1e1e; color: #ff7b72; }
            .badge-warn { background: #3a331e; color: #ffd866; }
            .horizon-card {
                background: #1a1d24;
                border-radius: 0.7rem;
                padding: 1rem;
                margin-bottom: 0.8rem;
                border-left: 4px solid #4fa3f0;
                color: #e8eaed;
            }
            .synoptic-box {
                background: #1c2733;
                border-left: 4px solid #4fa3f0;
                padding: 0.9rem 1.1rem;
                border-radius: 0.5rem;
                font-size: 0.95rem;
                line-height: 1.55;
                color: #dbe4ee;
            }
            .chart-title {
                font-size: 1.2rem;
                font-weight: 700;
                color: #4fa3f0;
                margin-top: 1rem;
                margin-bottom: 0.5rem;
            }
            .temp-warm { color: #ff6b6b; font-weight: 700; }
            .temp-cold { color: #4fa3f0; font-weight: 700; }
            .temp-zero { color: #9aa0a6; font-weight: 700; }

            .temp-card {
                border-radius: 0.6rem;
                padding: 0.7rem 0.4rem;
                text-align: center;
                margin-bottom: 0.6rem;
            }
            .temp-card .label {
                font-size: 0.75rem;
                color: #9aa0a6;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .temp-card .value {
                font-size: 1.5rem;
                font-weight: 800;
                margin-top: 0.2rem;
            }
            .temp-card.warm { background: #3a1f1f; border-left: 3px solid #ff6b6b; }
            .temp-card.cold { background: #1c2733; border-left: 3px solid #4fa3f0; }
            .temp-card.zero { background: #262a30; border-left: 3px solid #9aa0a6; }
            .temp-card.warm .value { color: #ff6b6b; }
            .temp-card.cold .value { color: #4fa3f0; }
            .temp-card.zero .value { color: #9aa0a6; }
        </style>
        """
    else:
        css = """
        <style>
            .main-title {
                background: linear-gradient(90deg, #1e88e5 0%, #43a047 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                font-size: 2.4rem;
                font-weight: 800;
                margin-bottom: 0;
                padding-bottom: 0;
            }
            .subtitle {
                color: #1e88e5;
                font-size: 1.7rem;
                font-weight: 700;
                margin-top: 0.3rem;
                margin-bottom: 1.6rem;
                padding-left: 0.8rem;
                border-left: 5px solid #43a047;
                letter-spacing: 0.2px;
            }
            .source-badge {
                display: inline-block;
                padding: 0.4rem 0.8rem;
                border-radius: 0.5rem;
                font-size: 0.85rem;
                font-weight: 600;
                margin-right: 0.5rem;
            }
            .badge-ok   { background: #d4edda; color: #155724; }
            .badge-err  { background: #f8d7da; color: #721c24; }
            .badge-warn { background: #fff3cd; color: #856404; }
            .horizon-card {
                background: #f8f9fa;
                border-radius: 0.7rem;
                padding: 1rem;
                margin-bottom: 0.8rem;
                border-left: 4px solid #1e88e5;
            }
            .synoptic-box {
                background: #e3f2fd;
                border-left: 4px solid #1e88e5;
                padding: 0.9rem 1.1rem;
                border-radius: 0.5rem;
                font-size: 0.95rem;
                line-height: 1.55;
            }
            .chart-title {
                font-size: 1.2rem;
                font-weight: 700;
                color: #1e88e5;
                margin-top: 1rem;
                margin-bottom: 0.5rem;
            }
            .temp-warm { color: #e53935; font-weight: 700; }
            .temp-cold { color: #1e88e5; font-weight: 700; }
            .temp-zero { color: #757575; font-weight: 700; }

            .temp-card {
                border-radius: 0.6rem;
                padding: 0.7rem 0.4rem;
                text-align: center;
                margin-bottom: 0.6rem;
            }
            .temp-card .label {
                font-size: 0.75rem;
                color: #666;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            .temp-card .value {
                font-size: 1.5rem;
                font-weight: 800;
                margin-top: 0.2rem;
            }
            .temp-card.warm { background: #ffebee; border-left: 3px solid #e53935; }
            .temp-card.cold { background: #e3f2fd; border-left: 3px solid #1e88e5; }
            .temp-card.zero { background: #f5f5f5; border-left: 3px solid #757575; }
            .temp-card.warm .value { color: #e53935; }
            .temp-card.cold .value { color: #1e88e5; }
            .temp-card.zero .value { color: #757575; }
        </style>
        """
    st.markdown(css, unsafe_allow_html=True)


_inject_css(st.session_state["ui_theme"])

# Палитра для графиков Altair — зависит от темы
if st.session_state["ui_theme"] == "dark":
    _chart_bg = "#0e1117"
    _chart_text = "#e8eaed"
    _chart_grid = "#2a2e36"
else:
    _chart_bg = "#ffffff"
    _chart_text = "#222222"
    _chart_grid = "#e0e0e0"


# ============================================================
# Заголовок
# ============================================================
st.markdown(
    '<h1 class="main-title">🏔️ Автономный ИИ Метео-агент</h1>',
    unsafe_allow_html=True
)
st.markdown(
    f'<p class="subtitle">{CONFIG["location_name"]} · '
    f'{CONFIG["lat"]}°N, {CONFIG["lon"]}°E · '
    f'высота {CONFIG["altitude"]} м</p>',
    unsafe_allow_html=True
)


# ============================================================
# Хелперы
# ============================================================
def check_synoptic_vs_numeric(synoptic_text, precip_mm, precip_threshold=5.0):
    if not synoptic_text or precip_mm < precip_threshold:
        return None
    text_lower = synoptic_text.lower()
    negative_markers = [
        "без осадков", "осадков не наблюдается", "осадков нет",
        "осадки не ожидаются", "осадки не приближаются",
        "преимущественно сухая", "без существенных осадков",
        "не ожидается", "стабильная малооблачная",
    ]
    if not any(m in text_lower for m in negative_markers):
        return None
    return (
        f"**⚠️ Расхождение между синоптической картой и численными моделями**\n\n"
        f"Обзорная карта meteoinfo не показывает осадков над точкой, "
        f"но локальные модели дают **{precip_mm:.1f} мм** за период.\n\n"
        f"**Причины:** локальные ливни в горах, невидимые на карте "
        f"масштаба ~25 км; либо карта — снимок момента, а не сумма.\n\n"
        f"**Рекомендация:** ориентируйтесь на локальные модели."
    )


def extract_number(text, pattern, default=0.0):
    m = re.search(pattern, text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return default
    return default


def precip_icon(precip_type):
    return {
        "снег": "❄️",
        "дождь": "🌧️",
        "смешанные": "🌨️",
        "нет": "☀️",
        "нет данных": "❔",
    }.get(precip_type, "🌦️")


def colorize_temps(text: str) -> str:
    def repl(match):
        try:
            num = float(match.group(1).replace(",", "."))
        except ValueError:
            return match.group(0)
        if num > 0:
            cls = "temp-warm"
        elif num < 0:
            cls = "temp-cold"
        else:
            cls = "temp-zero"
        display = f"{num:+.1f}°C" if num != 0 else "0.0°C"
        return f'<span class="{cls}">{display}</span>'

    pattern = r"\*{0,2}([+\-]?\d+(?:[.,]\d+)?)\s*°C\*{0,2}"
    return re.sub(pattern, repl, text)


def temp_card(label: str, value: float) -> str:
    if value > 0:
        cls = "warm"
    elif value < 0:
        cls = "cold"
    else:
        cls = "zero"
    display = f"{value:+.1f}°C" if value != 0 else "0.0°C"
    return (
        f'<div class="temp-card {cls}">'
        f'<div class="label">{label}</div>'
        f'<div class="value">{display}</div>'
        f'</div>'
    )


def _parse_time(t):
    """Безопасный парсинг времени из любого источника."""
    if t is None:
        return None
    s = str(t).strip()
    s = s.replace("Z", "").replace("+00:00", "").replace(" ", "T")
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


def build_multi_source_dataframe(yr_data, mb_data, om_data, hours_ahead=60):
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now + timedelta(hours=hours_ahead)

    source_offsets = {
        "yr.no":      timedelta(minutes=-15),
        "meteoblue":  timedelta(minutes=0),
        "Open-Meteo": timedelta(minutes=+15),
    }

    sources = [
        ("yr.no",      yr_data, "precip_mm"),
        ("meteoblue",  mb_data, "precip"),
        ("Open-Meteo", om_data, "precip_mm"),
    ]

    rows = []
    for src_name, data, precip_key in sources:
        if not data:
            continue
        offset = source_offsets[src_name]
        for r in data:
            t = _parse_time(r.get("time", ""))
            if t is None or not (start <= t <= end):
                continue
            precip = r.get(precip_key, 0) or 0
            temp = r.get("temp", 0) or 0

            if precip < 0.05:
                ptype = "нет"
            elif temp < -1:
                ptype = "снег"
            elif temp > 1:
                ptype = "дождь"
            else:
                ptype = "смешанные"

            rows.append({
                "time": t + offset,
                "time_real": t,
                "precip": float(precip),
                "temp": float(temp),
                "source": src_name,
                "ptype": ptype,
            })

    if not rows:
        return pd.DataFrame(
            columns=["time", "time_real", "precip", "temp", "source", "ptype"]
        )

    return pd.DataFrame(rows).sort_values(["time", "source"]).reset_index(drop=True)


# ============================================================
# ФЛАЖОК ТЕСТОВОГО РЕЖИМА
# ============================================================
TEST_MODE = False


def _slr(temp_c):
    """Snow-to-Liquid Ratio: см снега на 1 мм осадков (по T)."""
    if temp_c is None:
        return 1.0
    if temp_c < -10:
        return 1.3
    elif temp_c < -5:
        return 1.1
    elif temp_c < -2:
        return 0.9
    elif temp_c < 0:
        return 0.7
    elif temp_c <= 1:
        return 0.5
    else:
        return 0.4


def snow_warning_line(df_src, threshold_cm=25.0):
    """Возвращает строку-предупреждение о накоплении снега выше порога."""
    if df_src.empty:
        return None

    if TEST_MODE:
        snow = df_src[df_src["ptype"].isin(["снег", "дождь"])].sort_values("time_real")
    else:
        snow = df_src[df_src["ptype"] == "снег"].sort_values("time_real")

    THRESHOLD_CM = float(threshold_cm)
    if snow.empty:
        return None

    snow = snow.copy()
    snow["cm"] = snow.apply(lambda r: r["precip"] * _slr(r.get("temp")), axis=1)
    total_cm = float(snow["cm"].sum())
    if total_cm < THRESHOLD_CM:
        return None

    t_start = snow["time_real"].min()
    cumulative = 0.0
    t_threshold = None
    for _, row in snow.iterrows():
        cumulative += row["cm"]
        if cumulative >= THRESHOLD_CM:
            t_threshold = row["time_real"]
            break

    if t_threshold is None:
        return (
            f"⚠️ ❄️ Ожидается **{total_cm:.0f} см** снега (по SLR) · "
            f"старт {t_start.strftime('%d.%m %H:%M')} · "
            f"порог {THRESHOLD_CM:.0f} см не достигается в пределах прогноза"
        )

    hours_to = (t_threshold - t_start).total_seconds() / 3600
    return (
        f"⚠️ ❄️ Ожидается **{total_cm:.0f} см** снега (по SLR) · "
        f"старт {t_start.strftime('%d.%m %H:%M')} · "
        f"порог {THRESHOLD_CM:.0f} см → "
        f"{t_threshold.strftime('%d.%m %H:%M')} · "
        f"через **{hours_to:.0f} ч**"
    )


def render_multi_source_charts(df):
    if df.empty:
        st.info("ℹ️ Нет данных для графиков.")
        return

    import altair as alt

    source_colors = {
        "yr.no":      "#1e88e5",
        "meteoblue":  "#fb8c00",
        "Open-Meteo": "#43a047",
    }
    source_labels = {
        "yr.no":      "yr.no · MET Norway (1 км)",
        "meteoblue":  "meteoblue · базовая модель",
        "Open-Meteo": "Open-Meteo · интерполяция",
    }
    source_domain = list(source_colors.keys())

    precip_type_colors_by_source = {
        "yr.no": {"дождь": "#bbdefb", "снег": "#0d47a1", "смешанные": "#5c6bc0", "нет": "#f5f5f5"},
        "meteoblue": {"дождь": "#ffe0b2", "снег": "#e65100", "смешанные": "#a1887f", "нет": "#f5f5f5"},
        "Open-Meteo": {"дождь": "#c8e6c9", "снег": "#1b5e20", "смешанные": "#9e9d24", "нет": "#f5f5f5"},
    }

    t_start_axis = df["time_real"].min().replace(hour=0, minute=0, second=0, microsecond=0)
    t_end_axis = df["time_real"].max()

    x_scale = alt.Scale(domain=[t_start_axis, t_end_axis])
    x_axis = alt.Axis(
        format="%H:%M", labelAngle=-90, labelFontSize=9,
        tickMinStep=3600000, grid=True, gridDash=[2, 2],
        gridColor=_chart_grid, tickSize=5,
        labelColor=_chart_text, titleColor=_chart_text,
    )

    day_boundaries = []
    cur = t_start_axis
    while cur <= t_end_axis:
        day_boundaries.append(cur)
        cur += timedelta(days=1)
    days_df = pd.DataFrame({"day": day_boundaries})

    threshold = st.session_state.get("snow_threshold_cm", 25.0)

    st.markdown("### 🌧️ Осадки по источникам")

    for src in source_domain:
        sub = df[df["source"] == src]
        if sub.empty:
            continue

        color = source_colors[src]
        label = source_labels[src]
        src_colors = precip_type_colors_by_source[src]

        st.markdown(
            f'<p class="chart-title" style="color:{color};">🌧️ {label}</p>',
            unsafe_allow_html=True
        )

        legend_html = f"""
        <div style="display: flex; gap: 1.2rem; flex-wrap: wrap;
            margin: 0 0 0.4rem 0; font-size: 0.85rem;">
            <span style="display:inline-flex; align-items:center; gap:0.35rem;">
                <span style="display:inline-block; width:12px; height:12px;
                    background:{src_colors['дождь']}; border:1px solid #aaa;
                    border-radius:3px;"></span>дождь</span>
            <span style="display:inline-flex; align-items:center; gap:0.35rem;">
                <span style="display:inline-block; width:12px; height:12px;
                    background:{src_colors['снег']}; border:1px solid #aaa;
                    border-radius:3px;"></span>снег</span>
            <span style="display:inline-flex; align-items:center; gap:0.35rem;">
                <span style="display:inline-block; width:12px; height:12px;
                    background:{src_colors['смешанные']}; border:1px solid #aaa;
                    border-radius:3px;"></span>смешанные</span>
        </div>
        """
        st.markdown(legend_html, unsafe_allow_html=True)

        bars = alt.Chart(sub).mark_bar(size=6, opacity=0.95).encode(
            x=alt.X("time:T", title="Время", axis=x_axis, scale=x_scale),
            y=alt.Y("precip:Q", title="мм/ч",
                    axis=alt.Axis(labelColor=_chart_text, titleColor=_chart_text)),
            color=alt.Color(
                "ptype:N",
                scale=alt.Scale(
                    domain=list(src_colors.keys()),
                    range=list(src_colors.values())
                ),
                legend=None
            ),
            tooltip=[
                alt.Tooltip("time_real:T", title="Время", format="%d.%m %H:%M"),
                alt.Tooltip("precip:Q", title="Осадки, мм/ч", format=".2f"),
                alt.Tooltip("temp:Q", title="Температура, °C", format=".1f"),
                alt.Tooltip("ptype:N", title="Тип"),
            ]
        )

        day_lines = alt.Chart(days_df).mark_rule(
            color=("#9e9e9e" if _chart_bg == "#ffffff" else "#5a5f66"),
            strokeDash=[3, 3], size=1
        ).encode(x="day:T")

        day_labels = alt.Chart(days_df).mark_text(
            align="left", dx=4, dy=-4, fontSize=11, fontWeight="bold",
            color=_chart_text
        ).encode(x="day:T", text=alt.Text("day:T", format="%d.%m"))

        st.altair_chart(
            (bars + day_lines + day_labels).properties(height=180, background=_chart_bg),
            use_container_width=True
        )

        warning_line = snow_warning_line(sub, threshold_cm=threshold)
        if warning_line:
            st.error(warning_line)

    st.markdown("### 🌡️ Температура — сравнение трёх источников")

    temp_lines = alt.Chart(df).mark_line(strokeWidth=2.5, opacity=0.9).encode(
        x=alt.X("time:T", title="Время", axis=x_axis, scale=x_scale),
        y=alt.Y("temp:Q", title="°C",
                axis=alt.Axis(labelColor=_chart_text, titleColor=_chart_text)),
        color=alt.Color(
            "source:N",
            scale=alt.Scale(
                domain=source_domain,
                range=[source_colors[s] for s in source_domain]
            ),
            legend=alt.Legend(title="Источник", orient="top",
                              labelColor=_chart_text, titleColor=_chart_text)
        ),
        tooltip=[
            alt.Tooltip("time_real:T", title="Время", format="%d.%m %H:%M"),
            alt.Tooltip("source:N", title="Источник"),
            alt.Tooltip("temp:Q", title="Температура, °C", format=".1f"),
        ]
    )

    zero_rule = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color=("#757575" if _chart_bg == "#ffffff" else "#9aa0a6"),
        strokeDash=[4, 4], size=1.2
    ).encode(y="y:Q")

    day_lines_temp = alt.Chart(days_df).mark_rule(
        color=("#9e9e9e" if _chart_bg == "#ffffff" else "#5a5f66"),
        strokeDash=[3, 3], size=1
    ).encode(x="day:T")

    day_labels_temp = alt.Chart(days_df).mark_text(
        align="left", dx=4, dy=-4, fontSize=11, fontWeight="bold",
        color=_chart_text
    ).encode(x="day:T", text=alt.Text("day:T", format="%d.%m"))

    st.altair_chart(
        (temp_lines + zero_rule + day_lines_temp + day_labels_temp)
        .properties(height=220, background=_chart_bg),
        use_container_width=True
    )

    with st.expander("📊 Итоги по горизонтам (24 / 36 / 60 ч)", expanded=False):
        sources_present = df["source"].unique().tolist()
        now = datetime.now()
        for horizon_h in [24, 36, 60]:
            cutoff = now + timedelta(hours=horizon_h)
            df_h = df[df["time_real"] <= cutoff]
            st.markdown(f"#### ⏱️ За {horizon_h} часов")
            for src in sources_present:
                sub = df_h[df_h["source"] == src]
                c1, c2, c3, c4, c5 = st.columns(5)
                if sub.empty:
                    total_p = max_p = snow_p = rain_p = mix_p = 0.0
                else:
                    total_p = sub["precip"].sum()
                    max_p = sub["precip"].max()
                    snow_p = sub[sub["ptype"] == "снег"]["precip"].sum()
                    rain_p = sub[sub["ptype"] == "дождь"]["precip"].sum()
                    mix_p = sub[sub["ptype"] == "смешанные"]["precip"].sum()
                c1.metric(f"{src} · всего", f"{total_p:.1f} мм")
                c2.metric("🌧️ дождь", f"{rain_p:.1f} мм")
                c3.metric("❄️ снег", f"{snow_p:.1f} мм")
                c4.metric("🌨️ смеш.", f"{mix_p:.1f} мм")
                c5.metric("макс/ч", f"{max_p:.2f} мм/ч")


# ============================================================
# Читаем настройки UI из weights.json
# ============================================================
_w_path = os.path.join("history", "weights.json")
_default_t = 70
_default_p = 30
_default_snow_cm = 25

if os.path.exists(_w_path):
    try:
        with open(_w_path, "r", encoding="utf-8") as _f:
            _wdata = json.load(_f)
        _tw = _wdata.get("temp_weight")
        _pw = _wdata.get("precip_weight")
        _sc = _wdata.get("snow_threshold_cm")
        if _tw is not None and _pw is not None:
            _default_t = int(round(_tw * 100))
            _default_p = int(round(_pw * 100))
        if _sc is not None:
            _default_snow_cm = int(_sc)
    except Exception:
        pass


# ============================================================
# Боковая панель (сокращённая)
# ============================================================
with st.sidebar:
    # --- Заглушки, чтобы код ниже в app.py не сломался ---
    save_btn = False
    load_facts_btn = False
    calibrate_btn = False
    temp_w = _default_t
    precip_w = _default_p
    norm_t, norm_p = _default_t / 100.0, _default_p / 100.0
    total_w = _default_t + _default_p
    st.session_state["snow_threshold_cm"] = _default_snow_cm

    # --- Переключатель темы ---
    st.markdown("### 🎨 Тема")
    _theme_options = ["Светлая", "Тёмная"]
    _theme_idx = 0 if st.session_state["ui_theme"] == "light" else 1
    _theme_choice = st.radio(
        "Оформление",
        options=_theme_options,
        index=_theme_idx,
        key="theme_radio_widget",
        label_visibility="collapsed",
        horizontal=True,
    )
    _new_theme = "light" if _theme_choice == "Светлая" else "dark"
    if _new_theme != st.session_state["ui_theme"]:
        st.session_state["ui_theme"] = _new_theme
        st.rerun()

    st.markdown("---")

    # --- Кнопка «Собрать и проанализировать» ---
    st.markdown("### ⚙️ Управление")
    run_btn = st.button(
        "🔄 Собрать и проанализировать",
        type="primary",
        use_container_width=True
    )

    st.markdown("---")

    # --- Строка с весами ---
    w_yr, w_mb, w_om = load_weights()
    st.caption(
        f"Веса: yr.no {w_yr:.2f} · meteoblue {w_mb:.2f} · Open-Meteo {w_om:.2f}"
    )

    st.markdown("---")

    # --- Точка прогноза ---
    st.markdown("### 📍 Точка прогноза")
    st.markdown(f"**{CONFIG['location_name']}**")
    st.caption(
        f"Широта: {CONFIG['lat']}°\n\n"
        f"Долгота: {CONFIG['lon']}°\n\n"
        f"Высота: {CONFIG['altitude']} м"
    )

    st.markdown("---")

    # --- Источники ---
    st.markdown("### 📡 Источники")
    st.markdown(
        "- **yr.no** — MET Norway, 1 км\n"
        "- **meteoblue** — базовая модель\n"
        "- **Open-Meteo** — интерполяция\n"
        "- **meteoinfo** — карты Гидрометцентра\n"
        "- **Gemini** — синоптический анализ"
    )


# ============================================================
# Основная кнопка
# ============================================================
if run_btn:
    st.session_state["run"] = True

if st.session_state.get("run"):
    with st.spinner("Собираю данные с yr.no..."):
        try:
            yr_data = get_yr_api(CONFIG["lat"], CONFIG["lon"], CONFIG["altitude"])
            yr_status = ("ok", f"yr.no · {len(yr_data)} записей")
        except Exception as e:
            st.error(f"❌ yr.no: {e}")
            yr_data = []
            yr_status = ("err", "yr.no · ошибка")

    with st.spinner("Собираю данные с meteoblue..."):
        try:
            mb_data = get_meteoblue_forecast(
                CONFIG["lat"], CONFIG["lon"],
                CONFIG["meteoblue_api_key"],
                CONFIG["altitude"]
            )
            mb_status = ("ok", f"meteoblue · {len(mb_data)} записей")
        except Exception as e:
            st.error(f"❌ meteoblue: {e}")
            mb_data = []
            mb_status = ("err", "meteoblue · ошибка")

    with st.spinner("Собираю данные с Open-Meteo..."):
        try:
            om_data = get_openmeteo_forecast(
                CONFIG["lat"], CONFIG["lon"], CONFIG["altitude"]
            )
            om_status = ("ok", f"Open-Meteo · {len(om_data)} записей")
        except Exception as e:
            st.error(f"❌ Open-Meteo: {e}")
            om_data = []
            om_status = ("err", "Open-Meteo · ошибка")

    synoptic_by_horizon = {}
    try:
        with st.spinner("Скачиваю синоптические карты meteoinfo.ru..."):
            maps = download_maps(download_dir="downloads")
            mo_status = ("ok", f"meteoinfo · {len(maps)} карт")
    except Exception as e:
        st.error(f"❌ meteoinfo: {e}")
        maps = []
        mo_status = ("err", "meteoinfo · ошибка")

    gem_status = ("warn", "Gemini · нет ключа")
    if maps and CONFIG.get("gemini_api_key"):
        progress = st.progress(0, text="Анализирую карты через Gemini...")
        ok_count = 0
        for i, m in enumerate(maps, 1):
            try:
                text = analyze_map_with_gemini(
                    m["path"], CONFIG["gemini_api_key"],
                    CONFIG["lat"], CONFIG["lon"], CONFIG["altitude"]
                )
                synoptic_by_horizon[m["horizon"]] = text
                ok_count += 1
                progress.progress(i / len(maps),
                                  text=f"Проанализировано карт: {i}/{len(maps)}")
            except Exception as e:
                err_msg = str(e)[:80]
                synoptic_by_horizon[m["horizon"]] = f"⚠️ Gemini: {err_msg}"
                progress.progress(i / len(maps),
                                  text=f"Ошибка на карте {i}: {err_msg}")
        progress.empty()
        if ok_count > 0:
            gem_status = ("ok", f"Gemini · {ok_count}/{len(maps)} карт")
        else:
            gem_status = ("err", "Gemini · все ошибки")

    st.markdown("### 📡 Статус источников")
    b1, b2, b3, b4, b5 = st.columns(5)

    def render_badge(col, status_tuple):
        kind, label = status_tuple
        cls = {"ok": "badge-ok", "err": "badge-err", "warn": "badge-warn"}[kind]
        icon = {"ok": "✅", "err": "❌", "warn": "⚠️"}[kind]
        col.markdown(
            f'<span class="source-badge {cls}">{icon} {label}</span>',
            unsafe_allow_html=True
        )

    render_badge(b1, yr_status)
    render_badge(b2, mb_status)
    render_badge(b3, om_status)
    render_badge(b4, mo_status)
    render_badge(b5, gem_status)

    if yr_data or mb_data or om_data:
        weights = load_weights()
        result = analyze_forecast(
            yr_data, mb_data, CONFIG,
            om_data=om_data,
            weights=weights,
        )

        st.session_state["last_forecast"] = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "saved_at": datetime.now().isoformat(),
            "yr_data": yr_data,
            "mb_data": mb_data,
            "om_data": om_data,
            "horizons_text": {
                str(h): result["forecast"][f"{h}h"] for h in [24, 36, 60]
            },
        }
        st.caption(
            "💡 Прогноз готов."
        )

        st.markdown("---")
        st.markdown("## 📊 Прогноз на 24 / 36 / 60 часов")

        cols = st.columns(3)
        for col, h in zip(cols, [24, 36, 60]):
            forecast_text = result["forecast"][f"{h}h"]

            t_avg = extract_number(forecast_text, r"Средняя(?:\s*\(взвеш\.\))?:\s*\*{0,2}([+\-]?[\d.,]+)°C")
            t_min = extract_number(forecast_text, r"Минимум:\s*\*{0,2}([+\-]?[\d.,]+)°C")
            t_max = extract_number(forecast_text, r"Максимум:\s*\*{0,2}([+\-]?[\d.,]+)°C")
            precip_total = extract_number(forecast_text, r"Всего за [\d–]+ч(?:\s*\(консерв\.\))?:\s*\*{0,2}([\d.,]+)\s*мм")
            precip_interval = extract_number(forecast_text, r"В интервале [\d–]+ч:\s*([+\-]?[\d.,]+)\s*мм")
            zero_avg = extract_number(forecast_text, r"При средней T:\s*~(\d+)\s*м")

            if "снег" in forecast_text.lower():
                ptype = "снег"
            elif "смешанные" in forecast_text.lower():
                ptype = "смешанные"
            elif "дождь" in forecast_text.lower():
                ptype = "дождь"
            elif "нет данных" in forecast_text.lower():
                ptype = "нет данных"
            else:
                ptype = "нет"

            icon = precip_icon(ptype)

            with col:
                st.markdown(
                    f'<div class="horizon-card">'
                    f'<h3 style="margin:0;">⏱️ +{h} часов</h3>'
                    f'<p style="margin:0.3rem 0 0 0; opacity:0.7;">'
                    f'{icon} Осадки: {precip_total:.1f} мм'
                    f'</p></div>',
                    unsafe_allow_html=True
                )

                m1, m2, m3 = st.columns(3)
                m1.markdown(temp_card("Средняя", t_avg), unsafe_allow_html=True)
                m2.markdown(temp_card("Мин", t_min), unsafe_allow_html=True)
                m3.markdown(temp_card("Макс", t_max), unsafe_allow_html=True)

                st.markdown(
                    f"**{icon} Осадки**  \n"
                    f"Всего: **{precip_total:.1f} мм** · "
                    f"в интервале: **{precip_interval:+.1f} мм** · "
                    f"тип: **{ptype}**"
                )

                st.markdown(f"🧊 **Нулевая изотерма** — ~{int(zero_avg)} м")

                if h in synoptic_by_horizon:
                    with st.expander("🌍 Синоптическая ситуация", expanded=False):
                        st.markdown(
                            f'<div class="synoptic-box">'
                            f'{synoptic_by_horizon[h]}'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                        warning = check_synoptic_vs_numeric(
                            synoptic_by_horizon[h], precip_total
                        )
                        if warning:
                            st.warning(warning)

                with st.expander("📈 Численные детали", expanded=False):
                    st.markdown(colorize_temps(forecast_text), unsafe_allow_html=True)

        st.markdown("---")
        with st.expander("📈 Визуализация прогноза (3 источника)", expanded=False):
            df_chart = build_multi_source_dataframe(
                yr_data, mb_data, om_data, hours_ahead=60
            )
            render_multi_source_charts(df_chart)

        st.markdown("---")
        st.markdown("## 📊 Точность прогнозов")

        with st.expander("📈 Отчёт по источникам", expanded=False):
            report = accuracy_report()
            if not report or all(r["n"] == 0 for r in report.values()):
                st.info(
                    "ℹ️ Нет данных для отчёта. "
                    "Положите CSV со станции в папку `facts/`."
                )
            else:
                for src, data in report.items():
                    st.markdown(f"**{src}**")
                    c1, c2, c3 = st.columns(3)
                    c1.metric(
                        "Ошибка T (MAE)",
                        f"{data['temp_mae']}°C" if data['temp_mae'] is not None else "—"
                    )
                    c2.metric(
                        "Ошибка осадков",
                        f"{data['precip_mae']} мм" if data['precip_mae'] is not None else "—"
                    )
                    c3.metric("Сравнений", data['n'])

        with st.expander("📅 Когда были осадки (по факту)", expanded=False):
            facts_path = "history/facts.json"
            if not os.path.exists(facts_path):
                st.info("Нет данных о фактах.")
            else:
                try:
                    with open(facts_path, "r", encoding="utf-8") as f:
                        facts = json.load(f)
                except Exception:
                    facts = {}

                if not facts:
                    st.info("Файл facts.json пуст.")
                else:
                    for date_str in sorted(facts.keys(), reverse=True)[:7]:
                        fact = facts[date_str]
                        intervals = fact.get("precip_intervals", [])
                        total = fact.get("precip_total", 0.0)
                        ptype = fact.get("precip_type", "—")

                        if not intervals or total < 0.1:
                            st.markdown(f"**{date_str}** — осадков не было")
                            continue

                        lines = [f"**{date_str}** — всего **{total} мм** ({ptype})"]
                        for iv in intervals:
                            lines.append(f"  · {iv['start']}–{iv['end']} — {iv['mm']} мм")
                        st.markdown("  \n".join(lines))

    else:
        st.error("Не удалось собрать численные данные ни с одного источника.")
else:
    st.info("👈 Нажмите **«Собрать и проанализировать»** в боковой панели, "
            "чтобы получить прогноз.")
