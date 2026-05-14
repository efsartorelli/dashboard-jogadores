<<<<<<< HEAD
from html import escape

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils.load_data import load_data


st.set_page_config(
    page_title="Ranking BR - Pokémon GO Brasil",
    page_icon="🇧🇷",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_data(show_spinner=False)
def get_data():
    return load_data().sort_values(["nickname", "date"]).reset_index(drop=True)


@st.cache_data(show_spinner=False)
def get_best_catches(data):
    if data.empty:
        return pd.DataFrame(columns=["id_jogador", "nickname", "state", "catches", "date", "position"])

    idx = data.groupby("id_jogador")["catches"].idxmax()
    base = data.loc[idx, ["id_jogador", "nickname", "state", "catches", "date"]].copy()
    base = base.sort_values("catches", ascending=False).reset_index(drop=True)
    base["position"] = np.arange(1, len(base) + 1)
    return base


@st.cache_data(show_spinner=False)
def calculate_daily_averages(data, apenas_mensais):
    frames = []

    for _, group in data.groupby("id_jogador", sort=False):
        group = group.sort_values("date").reset_index(drop=True)
        size = len(group)

        if size < 2:
            continue

        starts, ends = np.triu_indices(size, k=1)
        dates = group["date"].to_numpy()
        catches = group["catches"].to_numpy()

        dias = ((dates[ends] - dates[starts]) / np.timedelta64(1, "D")).astype(int)
        ganho = catches[ends] - catches[starts]

        mask = (dias > 0) & (ganho > 0)
        if apenas_mensais:
            mask &= dias <= 32

        if not mask.any():
            continue

        starts = starts[mask]
        ends = ends[mask]
        dias = dias[mask]
        ganho = ganho[mask]

        frames.append(pd.DataFrame({
            "nickname": group["nickname"].iloc[-1],
            "state": group["state"].iloc[0],
            "media": (ganho / dias).astype(int),
            "data_inicial": pd.Series(dates[starts]).dt.date,
            "data_final": pd.Series(dates[ends]).dt.date,
            "dias": dias,
            "catches_periodo": ganho,
        }))

    if not frames:
        return pd.DataFrame(columns=[
            "nickname", "state", "media", "data_inicial",
            "data_final", "dias", "catches_periodo"
        ])

    return pd.concat(frames, ignore_index=True)


def ui_html(markup):
    st.html(markup)


def format_int(value):
    return f"{int(value):,}".replace(",", ".")


def format_compact(value):
    value = int(value)
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B".replace(".", ",")
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".", ",")
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def initials(name):
    cleaned = "".join(part[0] for part in str(name).replace("_", " ").split() if part)
    return (cleaned[:2] or "BR").upper()


def inject_css(dark_mode):
    palette = {
        "bg": "#0f1008" if dark_mode else "#efe6cf",
        "bg2": "#15170c" if dark_mode else "#f8f0dc",
        "card": "rgba(36, 27, 19, 0.78)" if dark_mode else "rgba(255, 248, 228, 0.88)",
        "card2": "rgba(45, 33, 24, 0.66)" if dark_mode else "rgba(245, 235, 210, 0.9)",
        "card3": "rgba(18, 18, 12, 0.62)" if dark_mode else "rgba(255, 252, 242, 0.72)",
        "border": "rgba(214, 174, 72, 0.25)" if dark_mode else "rgba(92, 67, 37, 0.22)",
        "border2": "rgba(127, 163, 90, 0.26)" if dark_mode else "rgba(69, 107, 53, 0.22)",
        "line": "rgba(240, 218, 159, 0.12)" if dark_mode else "rgba(82, 62, 40, 0.13)",
        "text": "#f0efff" if dark_mode else "#28253b",
        "muted": "#b9b6ff" if dark_mode else "#5e5b78",
        "gold": "#e2b84f",
        "green": "#7fa35a",
        "terra": "#b06b4f",
        "blue": "#8fa7ff",
    }

    ui_html(f"""
    <style>
    :root {{
        --rb-bg: {palette["bg"]};
        --rb-bg-2: {palette["bg2"]};
        --rb-card: {palette["card"]};
        --rb-card-2: {palette["card2"]};
        --rb-card-3: {palette["card3"]};
        --rb-border: {palette["border"]};
        --rb-border-2: {palette["border2"]};
        --rb-line: {palette["line"]};
        --rb-text: {palette["text"]};
        --rb-muted: {palette["muted"]};
        --rb-gold: {palette["gold"]};
        --rb-green: {palette["green"]};
        --rb-terra: {palette["terra"]};
        --rb-blue: {palette["blue"]};
        --rb-radius-lg: 26px;
        --rb-radius-md: 18px;
        --rb-shadow: 0 28px 90px rgba(0, 0, 0, 0.36);
    }}

    html {{
        scroll-behavior: smooth;
    }}

    .stApp {{
        overflow-x: hidden;
        color: var(--rb-text);
        background:
            radial-gradient(circle at 12% 0%, rgba(226, 184, 79, 0.13), transparent 28rem),
            radial-gradient(circle at 88% 9%, rgba(127, 163, 90, 0.16), transparent 24rem),
            radial-gradient(circle at 82% 35%, rgba(176, 107, 79, 0.10), transparent 22rem),
            linear-gradient(140deg, var(--rb-bg), var(--rb-bg-2) 52%, #0b0c07);
    }}

    .block-container {{
        max-width: 1480px;
        padding: 0.7rem 1.55rem 4rem;
    }}

    .section-anchor {{
        scroll-margin-top: 7rem;
    }}

    .st-key-navbar {{
        position: sticky;
        top: 0;
        z-index: 80;
        margin: -0.7rem 0 0.75rem;
        padding: 0.72rem 1rem;
        border: 1px solid var(--rb-border);
        border-top: 0;
        border-radius: 0 0 22px 22px;
        background: rgba(24, 21, 14, 0.78);
        backdrop-filter: blur(22px);
        box-shadow: 0 16px 42px rgba(0, 0, 0, 0.24);
    }}

    .nav-shell {{
        display: grid;
        grid-template-columns: minmax(220px, 1fr) auto;
        gap: 1rem;
        align-items: center;
    }}

    .brand {{
        display: flex;
        align-items: center;
        gap: 0.78rem;
        min-width: 0;
    }}

    .brand-orb {{
        width: 40px;
        height: 40px;
        border-radius: 50%;
        display: grid;
        place-items: center;
        flex: 0 0 auto;
        color: #111008;
        font-weight: 950;
        background:
            radial-gradient(circle at 35% 32%, #fff4b8 0 12%, transparent 13%),
            linear-gradient(145deg, #f0cc67, #a9832d);
        box-shadow: 0 0 0 1px rgba(255,255,255,0.18), 0 10px 28px rgba(226,184,79,0.18);
    }}

    .brand-name {{
        color: var(--rb-text);
        font-size: 1.02rem;
        font-weight: 900;
        line-height: 1;
    }}

    .brand-sub {{
        margin-top: 0.22rem;
        color: var(--rb-muted);
        font-size: 0.72rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        white-space: nowrap;
    }}

    .nav-menu {{
        display: flex;
        align-items: center;
        gap: clamp(0.25rem, 1.7vw, 1.1rem);
        justify-content: flex-end;
        min-width: 0;
    }}

    .nav-menu a {{
        color: var(--rb-muted);
        text-decoration: none;
        font-size: 0.83rem;
        font-weight: 760;
        padding: 0.62rem 0.72rem;
        border-radius: 999px;
        transition: color 150ms ease, background 150ms ease, transform 150ms ease;
        white-space: nowrap;
    }}

    .nav-menu a:first-child,
    .nav-menu a:hover {{
        color: var(--rb-gold);
        background: rgba(226, 184, 79, 0.10);
        transform: translateY(-1px);
    }}

    .st-key-theme_toggle {{
        display: flex;
        justify-content: flex-end;
    }}

    .hero {{
        position: relative;
        overflow: hidden;
        min-height: 350px;
        border: 1px solid var(--rb-border);
        border-radius: 30px;
        padding: clamp(1.3rem, 3vw, 2.6rem);
        background:
            linear-gradient(140deg, rgba(226,184,79,0.12), transparent 38%),
            radial-gradient(circle at 95% 5%, rgba(127,163,90,0.18), transparent 18rem),
            linear-gradient(160deg, var(--rb-card), var(--rb-card-3));
        box-shadow: var(--rb-shadow), inset 0 1px 0 rgba(255,255,255,0.05);
    }}

    .hero::after {{
        content: "";
        position: absolute;
        right: -7rem;
        bottom: -7rem;
        width: 420px;
        height: 260px;
        opacity: 0.2;
        background:
            radial-gradient(ellipse at 20% 50%, rgba(127,163,90,0.75), transparent 45%),
            radial-gradient(ellipse at 62% 40%, rgba(127,163,90,0.42), transparent 45%);
        transform: rotate(-18deg);
        pointer-events: none;
    }}

    .hero-grid {{
        position: relative;
        z-index: 1;
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(520px, 0.86fr);
        gap: clamp(1.2rem, 4vw, 3.5rem);
        align-items: center;
    }}

    .eyebrow {{
        display: inline-flex;
        align-items: center;
        width: fit-content;
        padding: 0.42rem 0.72rem;
        border: 1px solid rgba(127,163,90,0.28);
        border-radius: 999px;
        color: var(--rb-green);
        background: rgba(127,163,90,0.13);
        font-size: 0.72rem;
        font-weight: 900;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }}

    .hero-title {{
        max-width: 720px;
        margin: 1.05rem 0 0.78rem;
        color: var(--rb-text);
        font-size: clamp(2.35rem, 4.7vw, 4.85rem);
        line-height: 0.96;
        font-weight: 950;
        letter-spacing: 0;
        text-shadow: 0 18px 36px rgba(0,0,0,0.34);
    }}

    .hero-copy {{
        max-width: 670px;
        margin: 0;
        color: var(--rb-muted);
        font-size: 1rem;
        line-height: 1.68;
    }}

    .hero-actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.72rem;
        margin-top: 1.5rem;
    }}

    .rb-button {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 45px;
        padding: 0.72rem 1.05rem;
        border-radius: 999px;
        border: 1px solid var(--rb-border);
        color: var(--rb-text) !important;
        text-decoration: none !important;
        font-size: 0.86rem;
        font-weight: 850;
        background: rgba(255,255,255,0.035);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
        transition: transform 160ms ease, background 160ms ease, border-color 160ms ease;
    }}

    .rb-button.primary {{
        color: #171207 !important;
        border-color: rgba(226,184,79,0.58);
        background: linear-gradient(145deg, #f0ce6b, var(--rb-gold));
    }}

    .rb-button:hover {{
        transform: translateY(-2px);
        border-color: rgba(226,184,79,0.6);
        background: rgba(226,184,79,0.12);
    }}

    .hero-stat-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 1.15rem;
        align-items: stretch;
    }}

    .stat-card {{
        min-height: 210px;
        padding: 1.25rem;
        border: 1px solid var(--rb-border);
        border-radius: 24px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        background: linear-gradient(160deg, rgba(45,33,24,0.72), rgba(12,13,9,0.48));
        box-shadow: 0 18px 54px rgba(0,0,0,0.24), inset 0 1px 0 rgba(255,255,255,0.045);
        transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease;
    }}

    .stat-card:hover {{
        transform: translateY(-4px);
        border-color: rgba(226,184,79,0.48);
        box-shadow: 0 24px 70px rgba(0,0,0,0.28), 0 0 38px rgba(226,184,79,0.08);
    }}

    .stat-icon {{
        color: var(--rb-gold);
        font-size: 2rem;
        line-height: 1;
        margin-bottom: 1rem;
    }}

    .stat-label {{
        color: var(--rb-muted);
        font-size: 0.72rem;
        font-weight: 820;
        letter-spacing: 0.16em;
        text-transform: uppercase;
    }}

    .stat-value {{
        margin-top: 0.85rem;
        color: var(--rb-text);
        font-size: clamp(2rem, 3.2vw, 3rem);
        line-height: 1;
        font-weight: 950;
        letter-spacing: 0;
    }}

    .section {{
        margin-top: 1.2rem;
        border: 1px solid var(--rb-border);
        border-radius: 28px;
        padding: clamp(1rem, 2vw, 1.45rem);
        background:
            linear-gradient(150deg, rgba(36,27,19,0.76), rgba(15,16,8,0.62)),
            radial-gradient(circle at 8% 2%, rgba(226,184,79,0.08), transparent 18rem);
        box-shadow: 0 18px 62px rgba(0,0,0,0.24);
    }}

    .st-key-podium_section,
    .st-key-chart_section,
    .st-key-rankings_section,
    .st-key-states_section,
    .st-key-ranges_section {{
        margin-top: 1.2rem;
        border: 1px solid var(--rb-border);
        border-radius: 28px;
        padding: clamp(1rem, 2vw, 1.45rem);
        background:
            linear-gradient(150deg, rgba(36,27,19,0.76), rgba(15,16,8,0.62)),
            radial-gradient(circle at 8% 2%, rgba(226,184,79,0.08), transparent 18rem);
        box-shadow: 0 18px 62px rgba(0,0,0,0.24);
    }}

    .section-head {{
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 1rem;
        margin-bottom: 1.05rem;
    }}

    .section-kicker {{
        color: var(--rb-green);
        font-size: 0.72rem;
        font-weight: 900;
        letter-spacing: 0.13em;
        text-transform: uppercase;
    }}

    .section-title {{
        margin: 0.3rem 0 0;
        color: var(--rb-text);
        font-size: clamp(1.45rem, 2.6vw, 2.15rem);
        line-height: 1.05;
        font-weight: 930;
        letter-spacing: 0;
    }}

    .section-copy {{
        max-width: 720px;
        margin: 0.4rem 0 0;
        color: var(--rb-muted);
        font-size: 0.9rem;
        line-height: 1.62;
    }}

    .podium {{
        display: grid;
        grid-template-columns: minmax(0, 0.94fr) minmax(0, 1.08fr) minmax(0, 0.94fr);
        gap: 1.45rem;
        align-items: end;
        padding-top: 0.3rem;
    }}

    .podium-card {{
        position: relative;
        overflow: hidden;
        min-height: 218px;
        padding: 1.18rem 1.1rem;
        border: 1px solid rgba(214,174,72,0.24);
        border-radius: 28px;
        background:
            radial-gradient(circle at 50% 0%, rgba(255,255,255,0.06), transparent 9rem),
            linear-gradient(155deg, rgba(45,33,24,0.88), rgba(16,15,10,0.68));
        box-shadow: 0 20px 62px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.045);
        text-align: center;
        transition: transform 170ms ease, border-color 170ms ease;
    }}

    .podium-card::after {{
        content: "";
        position: absolute;
        right: -2.5rem;
        bottom: -2.5rem;
        width: 150px;
        height: 130px;
        background: radial-gradient(ellipse, rgba(127,163,90,0.18), transparent 65%);
        pointer-events: none;
    }}

    .podium-card:hover {{
        transform: translateY(-4px);
        border-color: rgba(226,184,79,0.55);
    }}

    .podium-card.champion {{
        min-height: 280px;
        border-color: rgba(226,184,79,0.58);
        box-shadow: 0 22px 82px rgba(226,184,79,0.13), 0 22px 62px rgba(0,0,0,0.3);
    }}

    .podium-crown {{
        position: absolute;
        top: 0.45rem;
        left: 50%;
        transform: translateX(-50%);
        color: var(--rb-gold);
        font-size: 2rem;
        text-shadow: 0 0 24px rgba(226,184,79,0.55);
    }}

    .podium-medal {{
        position: absolute;
        top: 1.2rem;
        left: 1.15rem;
        width: 34px;
        height: 34px;
        display: grid;
        place-items: center;
        border-radius: 50%;
        color: #171207;
        font-weight: 950;
        background: linear-gradient(145deg, #f2cf70, var(--rb-gold));
        box-shadow: 0 0 0 1px rgba(255,255,255,0.18), 0 0 22px rgba(226,184,79,0.28);
    }}

    .podium-avatar {{
        width: 82px;
        height: 82px;
        margin: 0.15rem auto 0.8rem;
        display: grid;
        place-items: center;
        border-radius: 50%;
        color: #131108;
        font-size: 1.25rem;
        font-weight: 950;
        border: 3px solid rgba(226,184,79,0.65);
        background:
            radial-gradient(circle at 34% 28%, #fff5b9 0 10%, transparent 11%),
            linear-gradient(145deg, var(--rb-blue), var(--rb-gold));
        box-shadow: 0 16px 42px rgba(0,0,0,0.32);
    }}

    .champion .podium-avatar {{
        width: 98px;
        height: 98px;
        margin-top: 1.2rem;
    }}

    .podium-name {{
        color: var(--rb-text);
        font-size: clamp(1.1rem, 2vw, 1.55rem);
        font-weight: 920;
        overflow-wrap: anywhere;
    }}

    .podium-state {{
        margin-top: 0.28rem;
        color: var(--rb-muted);
        font-size: 0.78rem;
        font-weight: 790;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }}

    .podium-catches {{
        margin-top: 0.85rem;
        color: var(--rb-gold);
        font-size: clamp(1.55rem, 3vw, 2.25rem);
        line-height: 1;
        font-weight: 950;
    }}

    .podium-caption {{
        margin-top: 0.18rem;
        color: var(--rb-text);
        font-size: 0.82rem;
    }}

    .panel {{
        border: 1px solid var(--rb-border);
        border-radius: 24px;
        padding: clamp(0.9rem, 2vw, 1.2rem);
        background: linear-gradient(150deg, rgba(26,25,18,0.62), rgba(15,16,8,0.36));
    }}

    .st-key-chart_panel,
    .st-key-filters_panel,
    .st-key-ranking_general_panel,
    .st-key-ranking_average_panel,
    .st-key-distribution_panel {{
        border: 1px solid var(--rb-border);
        border-radius: 24px;
        padding: clamp(0.85rem, 1.8vw, 1.15rem);
        background: linear-gradient(150deg, rgba(26,25,18,0.62), rgba(15,16,8,0.36));
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.035);
    }}

    .st-key-state_sort_control {{
        display: flex;
        justify-content: flex-end;
        align-items: flex-end;
        padding-bottom: 1.05rem;
    }}

    .st-key-state_sort_control [data-testid="stWidgetLabel"] {{
        justify-content: flex-end;
    }}

    .st-key-state_sort_control [data-testid="stWidgetLabel"] p {{
        color: var(--rb-muted) !important;
        font-size: 0.68rem;
        font-weight: 900;
        letter-spacing: 0.11em;
        text-transform: uppercase;
    }}

    .st-key-state_sort_control div[role="radiogroup"] {{
        justify-content: flex-end;
        gap: 0.35rem;
    }}

    .st-key-state_sort_control div[role="radiogroup"] label {{
        min-height: 34px;
        border-radius: 999px !important;
        border-color: var(--rb-border) !important;
        background: rgba(255,255,255,0.035) !important;
        color: var(--rb-muted) !important;
        transition: transform 150ms ease, border-color 150ms ease, background 150ms ease;
    }}

    .st-key-state_sort_control div[role="radiogroup"] label:hover {{
        transform: translateY(-1px);
        border-color: rgba(127,163,90,0.46) !important;
        background: rgba(127,163,90,0.10) !important;
    }}

    .st-key-state_sort_control div[role="radiogroup"] label:has(input:checked) {{
        color: #171207 !important;
        border-color: rgba(226,184,79,0.62) !important;
        background: linear-gradient(145deg, rgba(226,184,79,0.95), rgba(127,163,90,0.82)) !important;
    }}

    .empty-state {{
        padding: 1.1rem;
        border: 1px dashed var(--rb-border);
        border-radius: 18px;
        color: var(--rb-muted);
        background: rgba(255,255,255,0.025);
        text-align: center;
    }}

    .selected-chips {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin: -0.2rem 0 0.9rem;
    }}

    .selected-chip {{
        padding: 0.28rem 0.55rem;
        border: 1px solid rgba(226,184,79,0.24);
        border-radius: 999px;
        color: var(--rb-muted);
        background: rgba(226,184,79,0.07);
        font-size: 0.76rem;
        font-weight: 760;
    }}

    .rb-table-wrap {{
        overflow-x: auto;
        border: 1px solid var(--rb-border);
        border-radius: 18px;
        background: rgba(8,8,6,0.16);
    }}

    .rb-table {{
        width: 100%;
        min-width: 620px;
        border-collapse: separate;
        border-spacing: 0;
        color: var(--rb-text);
        font-size: 0.78rem;
        line-height: 1.25;
    }}

    .rb-table th {{
        position: sticky;
        top: 0;
        z-index: 1;
        padding: 0.56rem 0.66rem;
        color: var(--rb-muted);
        text-align: left;
        font-size: 0.62rem;
        font-weight: 870;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        border-bottom: 1px solid var(--rb-line);
        background: rgba(29,24,18,0.94);
    }}

    .rb-table td {{
        padding: 0.48rem 0.66rem;
        border-bottom: 1px solid rgba(240,218,159,0.075);
        vertical-align: middle;
        white-space: nowrap;
    }}

    .rb-table td:nth-child(4),
    .rb-table th:nth-child(4),
    .rb-table td:last-child,
    .rb-table th:last-child {{
        text-align: right;
    }}

    .rb-table tr:last-child td {{
        border-bottom: 0;
    }}

    .rb-table tbody tr:hover {{
        background: rgba(127,163,90,0.09);
    }}

    .rb-table tr.top-10 td {{
        background: rgba(226,184,79,0.045);
    }}

    .rank-pill {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 28px;
        height: 24px;
        border-radius: 999px;
        color: var(--rb-gold);
        border: 1px solid rgba(226,184,79,0.2);
        background: rgba(226,184,79,0.10);
        font-size: 0.72rem;
        font-weight: 950;
    }}

    .rank-pill.medal {{
        color: #171207;
        background: linear-gradient(145deg, #f2cf70, var(--rb-gold));
    }}

    .page-note {{
        text-align: center;
        color: var(--rb-muted);
        font-size: 0.78rem;
        padding-top: 0.38rem;
    }}

    .state-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
        gap: 0.9rem;
    }}

    .state-card {{
        min-height: 172px;
        padding: 0.94rem;
        border: 1px solid var(--rb-border);
        border-radius: 21px;
        background: linear-gradient(155deg, rgba(45,33,24,0.72), rgba(15,16,8,0.48));
        box-shadow: 0 16px 44px rgba(0,0,0,0.18);
        transition: transform 160ms ease, border-color 160ms ease;
    }}

    .state-card:hover {{
        transform: translateY(-3px);
        border-color: rgba(127,163,90,0.48);
    }}

    .state-top {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.55rem;
    }}

    .state-uf {{
        color: var(--rb-text);
        font-size: 1.55rem;
        font-weight: 950;
        line-height: 1;
    }}

    .state-position {{
        padding: 0.25rem 0.46rem;
        border-radius: 999px;
        color: var(--rb-green);
        background: rgba(127,163,90,0.12);
        border: 1px solid rgba(127,163,90,0.18);
        font-size: 0.66rem;
        font-weight: 900;
        white-space: nowrap;
    }}

    .state-metrics {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.56rem;
        margin-top: 0.85rem;
    }}

    .mini-label {{
        color: var(--rb-muted);
        font-size: 0.58rem;
        font-weight: 850;
        letter-spacing: 0.1em;
        text-transform: uppercase;
    }}

    .mini-value {{
        margin-top: 0.22rem;
        color: var(--rb-text);
        font-size: 0.82rem;
        font-weight: 900;
        overflow-wrap: anywhere;
    }}

    .state-best {{
        margin-top: 0.85rem;
        padding-top: 0.75rem;
        border-top: 1px solid var(--rb-line);
        color: var(--rb-muted);
        font-size: 0.78rem;
        line-height: 1.45;
    }}

    .state-best strong {{
        color: var(--rb-text);
    }}

    .ranges-layout {{
        display: grid;
        grid-template-columns: minmax(0, 1.1fr) minmax(330px, 0.9fr);
        gap: 1.2rem;
        align-items: stretch;
    }}

    .bar-chart {{
        min-height: 310px;
        padding: 1rem 0.35rem 0.2rem;
        display: grid;
        grid-template-columns: repeat(7, minmax(44px, 1fr));
        gap: clamp(0.5rem, 1.5vw, 0.9rem);
        align-items: end;
        overflow-x: auto;
    }}

    .bar-column {{
        min-width: 44px;
        height: 286px;
        display: grid;
        grid-template-rows: 1fr auto;
        gap: 0.55rem;
    }}

    .bar-track {{
        display: flex;
        align-items: end;
        height: 100%;
        padding: 0.22rem;
        border-radius: 999px;
        border: 1px solid var(--rb-line);
        background: rgba(255,255,255,0.035);
    }}

    .bar-fill {{
        position: relative;
        width: 100%;
        min-height: 12px;
        border-radius: 999px;
        background: linear-gradient(180deg, var(--rb-gold), #d0a73c 38%, var(--rb-green));
        box-shadow: 0 16px 28px rgba(0,0,0,0.22), inset 0 1px 0 rgba(255,255,255,0.28);
    }}

    .bar-fill span {{
        position: absolute;
        top: -1.65rem;
        left: 50%;
        transform: translateX(-50%);
        color: var(--rb-text);
        font-size: 0.78rem;
        font-weight: 900;
        white-space: nowrap;
    }}

    .bar-label {{
        color: var(--rb-muted);
        text-align: center;
        font-size: 0.74rem;
        font-weight: 850;
    }}

    .range-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.8rem;
        height: 100%;
        align-content: center;
    }}

    .range-card {{
        min-height: 96px;
        padding: 0.9rem;
        border: 1px solid var(--rb-border);
        border-radius: 20px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
        background: linear-gradient(155deg, rgba(45,33,24,0.72), rgba(15,16,8,0.48));
    }}

    .range-name {{
        color: var(--rb-green);
        font-size: 0.82rem;
        font-weight: 920;
    }}

    .range-value {{
        margin-top: 0.2rem;
        color: var(--rb-text);
        font-size: 1.75rem;
        line-height: 1;
        font-weight: 950;
    }}

    .range-caption {{
        margin-top: 0.24rem;
        color: var(--rb-muted);
        font-size: 0.76rem;
    }}

    .footer {{
        margin-top: 1.2rem;
        padding: 1.1rem 1.25rem;
        border: 1px solid var(--rb-border);
        border-radius: 24px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        color: var(--rb-muted);
        background: rgba(15,16,8,0.42);
    }}

    .footer strong {{
        color: var(--rb-text);
    }}

    label, .stMarkdown, .stTextInput label, .stMultiSelect label {{
        color: var(--rb-text) !important;
    }}

    div[data-baseweb="input"], div[data-baseweb="select"] > div {{
        border-color: var(--rb-border) !important;
        background-color: rgba(255,255,255,0.045) !important;
        border-radius: 16px !important;
    }}

    div[data-baseweb="tag"] {{
        border-radius: 999px !important;
        background-color: rgba(226,184,79,0.16) !important;
    }}

    div[role="radiogroup"] {{
        flex-wrap: wrap;
        gap: 0.35rem;
    }}

    div[role="radiogroup"] label {{
        border-radius: 999px !important;
        border-color: var(--rb-border) !important;
    }}

    div[role="radiogroup"] label:has(input:checked) {{
        background: linear-gradient(145deg, #f0ce6b, var(--rb-gold)) !important;
        color: #161106 !important;
    }}

    .stButton > button {{
        min-height: 34px;
        width: 100%;
        border-radius: 999px;
        border: 1px solid var(--rb-border);
        background: rgba(255,255,255,0.035);
        color: var(--rb-text);
        font-size: 0.78rem;
        padding: 0.32rem 0.65rem;
        transition: transform 150ms ease, border-color 150ms ease, background 150ms ease;
    }}

    .stButton > button:hover {{
        transform: translateY(-1px);
        border-color: rgba(226,184,79,0.55);
        background: rgba(226,184,79,0.11);
        color: var(--rb-text);
    }}

    .stButton > button:disabled {{
        opacity: 0.38;
    }}

    @media (max-width: 1200px) {{
        .hero-grid {{
            grid-template-columns: 1fr;
        }}

        .hero-stat-grid {{
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }}
    }}

    @media (max-width: 1024px) {{
        .nav-menu a:nth-child(n+4) {{
            display: none;
        }}

        .ranges-layout {{
            grid-template-columns: 1fr;
        }}
    }}

    @media (max-width: 768px) {{
        .block-container {{
            padding-left: 0.85rem;
            padding-right: 0.85rem;
        }}

        .nav-shell {{
            grid-template-columns: 1fr auto;
        }}

        .nav-menu a {{
            display: none;
        }}

        .hero-stat-grid,
        .podium {{
            grid-template-columns: 1fr;
        }}

        .stat-card {{
            min-height: 154px;
        }}

        .podium-card.champion {{
            order: -1;
        }}

        .section-head {{
            display: block;
        }}

        .range-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .st-key-filters_panel [data-testid="stHorizontalBlock"],
        .st-key-chart_panel [data-testid="stHorizontalBlock"],
        .st-key-states_section [data-testid="stHorizontalBlock"] {{
            flex-wrap: wrap;
        }}

        .st-key-state_sort_control {{
            justify-content: flex-start;
            padding-bottom: 0.85rem;
        }}

        .st-key-state_sort_control [data-testid="stWidgetLabel"],
        .st-key-state_sort_control div[role="radiogroup"] {{
            justify-content: flex-start;
        }}
    }}

    @media (max-width: 480px) {{
        .block-container {{
            padding-left: 0.65rem;
            padding-right: 0.65rem;
        }}

        .hero,
        .section,
        .st-key-podium_section,
        .st-key-chart_section,
        .st-key-rankings_section,
        .st-key-states_section,
        .st-key-ranges_section {{
            border-radius: 22px;
            padding: 1rem;
        }}

        .hero-title {{
            font-size: clamp(2rem, 13vw, 3rem);
        }}

        .hero-actions .rb-button {{
            width: 100%;
        }}

        .state-grid,
        .range-grid {{
            grid-template-columns: 1fr;
        }}

        .bar-chart {{
            grid-template-columns: repeat(7, minmax(38px, 1fr));
            gap: 0.42rem;
        }}

        .bar-column {{
            min-width: 38px;
        }}

        .footer {{
            display: block;
        }}
    }}

    @media (max-width: 360px) {{
        .brand-sub {{
            display: none;
        }}

        .hero-title {{
            font-size: 2rem;
        }}
    }}
    </style>
    """)


def section_header(kicker, title, copy=None):
    copy_html = f'<p class="section-copy">{escape(copy)}</p>' if copy else ""
    ui_html(f"""
        <div class="section-head">
            <div>
                <div class="section-kicker">{escape(kicker)}</div>
                <h2 class="section-title">{escape(title)}</h2>
                {copy_html}
            </div>
        </div>
    """)


def render_navbar():
    with st.container(key="navbar"):
        left, right = st.columns([0.78, 0.22], vertical_alignment="center")
        with left:
            ui_html("""
                <div class="nav-shell">
                    <div class="brand">
                        <div class="brand-orb">BR</div>
                        <div>
                            <div class="brand-name">Ranking BR</div>
                            <div class="brand-sub">Pokémon GO · Brasil</div>
                        </div>
                    </div>
                    <nav class="nav-menu">
                        <a href="#dashboard">Dashboard</a>
                        <a href="#rankings">Rankings</a>
                        <a href="#estados">Estados</a>
                        <a href="#jogadores">Jogadores</a>
                        <a href="#sobre">Sobre</a>
                    </nav>
                </div>
            """)
        with right:
            with st.container(key="theme_toggle"):
                st.toggle("Tema escuro", key="dark_theme", label_visibility="collapsed")


def render_hero(base, historical_data):
    jogadores = base["id_jogador"].nunique()
    capturas = historical_data["catches"].sum()
    estados = base["state"].nunique()

    ui_html(f"""
        <section id="dashboard" class="hero section-anchor">
            <div class="hero-grid">
                <div>
                    <div class="eyebrow">Ranking nacional competitivo</div>
                    <h1 class="hero-title">Dashboard de Jogadores Brasileiros — Pokémon GO</h1>
                    <p class="hero-copy">
                        Monitoramento visual dos jogadores brasileiros por capturas, evolução,
                        médias diárias e presença por estado. Um painel escuro, direto e refinado
                        para acompanhar quem lidera a comunidade.
                    </p>
                    <div class="hero-actions">
                        <a class="rb-button primary" href="#podio">Ver pódio</a>
                        <a class="rb-button" href="#rankings">Explorar ranking</a>
                    </div>
                </div>
                <div class="hero-stat-grid">
                    <article class="stat-card">
                        <div class="stat-icon">●●</div>
                        <div class="stat-label">Jogadores monitorados</div>
                        <div class="stat-value">{format_int(jogadores)}</div>
                    </article>
                    <article class="stat-card">
                        <div class="stat-icon">◎</div>
                        <div class="stat-label">Capturas analisadas</div>
                        <div class="stat-value">{format_compact(capturas)}</div>
                    </article>
                    <article class="stat-card">
                        <div class="stat-icon">◇</div>
                        <div class="stat-label">Estados representados</div>
                        <div class="stat-value">{format_int(estados)}</div>
                    </article>
                </div>
            </div>
        </section>
    """)


def podium_card(row, place):
    medal_labels = {1: "1", 2: "2", 3: "3"}
    class_name = "podium-card champion" if place == 1 else "podium-card"
    crown = '<div class="podium-crown">♛</div>' if place == 1 else ""
    return f"""
        <article class="{class_name}">
            {crown}
            <div class="podium-medal">{medal_labels[place]}</div>
            <div class="podium-avatar">{escape(initials(row["nickname"]))}</div>
            <div class="podium-name">{escape(str(row["nickname"]))}</div>
            <div class="podium-state">{escape(str(row["state"]))}</div>
            <div class="podium-catches">{format_int(row["catches"])}</div>
            <div class="podium-caption">capturas</div>
        </article>
    """


def render_podium(base):
    top3 = base.head(3).reset_index(drop=True)
    if top3.empty:
        ui_html('<div class="empty-state">Nenhum jogador encontrado para montar o pódio.</div>')
        return

    cards = []
    for index in [1, 0, 2]:
        if index < len(top3):
            cards.append(podium_card(top3.iloc[index], index + 1))

    ui_html(f'<div class="podium">{"".join(cards)}</div>')


def filter_by_period(data, selected_period):
    if data.empty or selected_period == "Tudo":
        return data

    days_by_period = {"7d": 7, "30d": 30, "90d": 90, "1a": 365, "3a": 1095}
    cutoff = data["date"].max() - pd.Timedelta(days=days_by_period[selected_period])
    return data[data["date"] >= cutoff]


def render_selected_chips(players):
    if not players:
        return

    chips = "".join(f'<span class="selected-chip">{escape(player)}</span>' for player in players)
    ui_html(f'<div class="selected-chips">{chips}</div>')


def render_chart(data, player_options, default_players):
    with st.container(key="chart_panel"):
        controls_left, controls_right = st.columns([0.68, 0.32], vertical_alignment="bottom")
        with controls_left:
            selected_players = st.multiselect(
                "Selecionar jogadores (1–10)",
                player_options,
                default=default_players,
                max_selections=10,
                placeholder="Buscar jogadores",
            )
        with controls_right:
            period = st.segmented_control(
                "Período",
                ["7d", "30d", "90d", "1a", "3a", "Tudo"],
                default="Tudo",
                selection_mode="single",
            )

        render_selected_chips(selected_players)

        if not selected_players:
            ui_html('<div class="empty-state">Selecione pelo menos um jogador para visualizar a evolução.</div>')
            return

        plot_data = filter_by_period(data[data["nickname"].isin(selected_players)], period)
        colors = ["#e2b84f", "#7fa35a", "#6f7fd9", "#b06b4f", "#8bb6c9", "#d9a48f", "#b6c56d", "#d0c7a8", "#7f9471", "#a97862"]

        fig = go.Figure()
        for index, player in enumerate(selected_players):
            df_player = plot_data[plot_data["nickname"] == player].sort_values("date")
            fig.add_trace(go.Scatter(
                x=df_player["date"],
                y=df_player["catches"],
                mode="lines+markers",
                name=player,
                line=dict(width=3, color=colors[index % len(colors)], shape="spline"),
                marker=dict(size=6, line=dict(width=1.3, color="rgba(255,255,255,0.38)")),
                hovertemplate="<b>%{fullData.name}</b><br>%{x|%d/%m/%Y}<br>%{y:,.0f} capturas<extra></extra>",
            ))

        fig.update_layout(
            template="plotly_dark",
            height=500,
            margin=dict(l=10, r=10, t=34, b=8),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(16,17,12,0.28)",
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=12)),
            font=dict(color="#f0efff", family="Inter, Segoe UI, Arial"),
            xaxis=dict(showgrid=True, gridcolor="rgba(240,218,159,0.08)", zeroline=False),
            yaxis=dict(showgrid=True, gridcolor="rgba(240,218,159,0.08)", zeroline=False, tickformat=","),
            hoverlabel=dict(bgcolor="#241b13", bordercolor="#e2b84f", font_size=13),
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "responsive": True})


def build_general_ranking(data):
    if data.empty:
        return pd.DataFrame(columns=["#", "Jogador", "Estado", "Capturas", "Dias ativo"])

    idx = data.groupby("id_jogador")["catches"].idxmax()
    ranking = data.loc[idx, ["id_jogador", "nickname", "state", "catches"]].sort_values("catches", ascending=False).reset_index(drop=True)
    active_days = data.groupby("id_jogador")["date"].agg(lambda x: max((x.max() - x.min()).days, 1)).to_dict()
    ranking["#"] = np.arange(1, len(ranking) + 1)
    ranking["Jogador"] = ranking["nickname"]
    ranking["Estado"] = ranking["state"]
    ranking["Capturas"] = ranking["catches"].map(format_int)
    ranking["Dias ativo"] = ranking["id_jogador"].map(active_days).fillna(0).astype(int)
    return ranking[["#", "Jogador", "Estado", "Capturas", "Dias ativo"]]


def build_average_ranking(data, somente_melhor, apenas_mensais):
    df_media = calculate_daily_averages(data, apenas_mensais)

    if df_media.empty:
        return pd.DataFrame(columns=["#", "Jogador", "Estado", "Média", "Período", "Dias"])

    if somente_melhor:
        df_media = df_media.sort_values("media", ascending=False).groupby("nickname").head(1)

    df_media = df_media.sort_values("media", ascending=False).reset_index(drop=True)
    df_media["#"] = np.arange(1, len(df_media) + 1)
    df_media["Jogador"] = df_media["nickname"]
    df_media["Estado"] = df_media["state"]
    df_media["Média"] = df_media["media"].map(format_int)
    df_media["Período"] = df_media["data_inicial"].astype(str) + " - " + df_media["data_final"].astype(str)
    df_media["Dias"] = df_media["dias"]
    return df_media[["#", "Jogador", "Estado", "Média", "Período", "Dias"]]


def table_html(data):
    if data.empty:
        return '<div class="empty-state">Nenhum resultado encontrado com os filtros atuais.</div>'

    header = "".join(f"<th>{escape(str(column))}</th>" for column in data.columns)
    rows = []

    for _, row in data.iterrows():
        rank = int(row["#"]) if "#" in row else 0
        row_class = "top-10" if rank <= 10 else ""
        cells = []
        for column in data.columns:
            value = escape(str(row[column]))
            if column == "#":
                medal_class = " medal" if rank <= 3 else ""
                value = f'<span class="rank-pill{medal_class}">{rank}</span>'
            cells.append(f"<td>{value}</td>")
        rows.append(f'<tr class="{row_class}">{"".join(cells)}</tr>')

    return f"""
        <div class="rb-table-wrap">
            <table class="rb-table">
                <thead><tr>{header}</tr></thead>
                <tbody>{"".join(rows)}</tbody>
            </table>
        </div>
    """


def render_paginated_table(title, data, key):
    st.markdown(f"#### {title}")
    page_size = 10
    page_count = max(1, int(np.ceil(len(data) / page_size)))
    page_key = f"{key}_page"
    st.session_state.setdefault(page_key, 0)
    st.session_state[page_key] = min(st.session_state[page_key], page_count - 1)

    prev_col, page_col, next_col = st.columns([0.24, 0.52, 0.24], vertical_alignment="center")
    with prev_col:
        if st.button("Anterior", key=f"{key}_prev", disabled=st.session_state[page_key] <= 0):
            st.session_state[page_key] -= 1
    with page_col:
        ui_html(f'<div class="page-note">Página {st.session_state[page_key] + 1} de {page_count}</div>')
    with next_col:
        if st.button("Próxima", key=f"{key}_next", disabled=st.session_state[page_key] >= page_count - 1):
            st.session_state[page_key] += 1

    start = st.session_state[page_key] * page_size
    page = data.iloc[start:start + page_size]
    ui_html(table_html(page))


def render_filters(data):
    states = sorted(data["state"].dropna().astype(str).unique())

    with st.container(key="filters_panel"):
        search_col, states_col = st.columns([0.28, 0.72], vertical_alignment="bottom")
        with search_col:
            search = st.text_input("Buscar por nickname", placeholder="⌕ Buscar por nickname")
        with states_col:
            selected_states = st.pills(
                "Filtrar por estado",
                states,
                selection_mode="multi",
                default=[],
            )

        _, switch_col_1, switch_col_2 = st.columns([0.58, 0.21, 0.21])
        with switch_col_1:
            somente_melhor = st.toggle("Melhor média", value=False)
        with switch_col_2:
            apenas_mensais = st.toggle("Apenas mensais", value=False)

    filtered = data
    if search:
        filtered = filtered[filtered["nickname"].str.contains(search.strip(), case=False, na=False)]
    if selected_states:
        filtered = filtered[filtered["state"].isin(selected_states)]

    return filtered, somente_melhor, apenas_mensais


def build_state_stats(base, order_by="Total capturas"):
    if base.empty:
        return pd.DataFrame(columns=[
            "Estado", "Posição", "Jogadores", "Total", "Média",
            "Melhor jogador", "Valor melhor jogador"
        ])

    rows = []
    for state, group in base.groupby("state", dropna=True):
        total = group["catches"].sum()
        best = group.sort_values("catches", ascending=False).iloc[0]
        rows.append({
            "Estado": state,
            "Jogadores": group["id_jogador"].nunique(),
            "Total": total,
            "Média": int(group["catches"].mean()),
            "Melhor jogador": best["nickname"],
            "Valor melhor jogador": best["catches"],
        })

    sort_columns = {
        "Total capturas": "Total",
        "Nº de jogadores": "Jogadores",
        "Média": "Média",
    }
    sort_column = sort_columns.get(order_by, "Total")

    stats = (
        pd.DataFrame(rows)
        .sort_values([sort_column, "Estado"], ascending=[False, True])
        .reset_index(drop=True)
    )
    stats["Posição"] = np.arange(1, len(stats) + 1)
    return stats


def render_state_cards(stats):
    if stats.empty:
        ui_html('<div class="empty-state">Nenhum estado encontrado com os filtros atuais.</div>')
        return

    cards = []
    for _, row in stats.iterrows():
        cards.append(f"""
            <article class="state-card">
                <div class="state-top">
                    <div class="state-uf">{escape(str(row["Estado"]))}</div>
                    <div class="state-position">#{int(row["Posição"])} no BR</div>
                </div>
                <div class="state-metrics">
                    <div>
                        <div class="mini-label">Jogadores</div>
                        <div class="mini-value">{format_int(row["Jogadores"])}</div>
                    </div>
                    <div>
                        <div class="mini-label">Total</div>
                        <div class="mini-value">{format_compact(row["Total"])}</div>
                    </div>
                    <div>
                        <div class="mini-label">Média</div>
                        <div class="mini-value">{format_compact(row["Média"])}</div>
                    </div>
                </div>
                <div class="state-best">
                    Melhor jogador: <strong>{escape(str(row["Melhor jogador"]))}</strong><br>
                    {format_int(row["Valor melhor jogador"])} capturas
                </div>
            </article>
        """)

    ui_html(f'<div class="state-grid">{"".join(cards)}</div>')


def build_distribution(base):
    thresholds = [100_000, 300_000, 500_000, 700_000, 900_000, 1_000_000, 2_000_000]
    labels = ["100k+", "300k+", "500k+", "700k+", "900k+", "1M+", "2M+"]
    catches = base["catches"].to_numpy()
    counts = [int((catches >= threshold).sum()) for threshold in thresholds]
    return pd.DataFrame({"Faixa": labels, "Jogadores": counts})


def render_distribution(distribution):
    max_count = max(int(distribution["Jogadores"].max()), 1)
    bars = []
    cards = []

    for _, row in distribution.iterrows():
        count = int(row["Jogadores"])
        height = max(8, round((count / max_count) * 100, 2))
        label = escape(str(row["Faixa"]))
        bars.append(f"""
            <div class="bar-column">
                <div class="bar-track">
                    <div class="bar-fill" style="height:{height}%"><span>{format_int(count)}</span></div>
                </div>
                <div class="bar-label">{label}</div>
            </div>
        """)
        cards.append(f"""
            <article class="range-card">
                <div class="range-name">{label}</div>
                <div class="range-value">{format_int(count)}</div>
                <div class="range-caption">jogadores</div>
            </article>
        """)

    ui_html(f"""
        <div class="ranges-layout">
            <div class="bar-chart">{"".join(bars)}</div>
            <div class="range-grid">{"".join(cards)}</div>
        </div>
    """)


def render_footer():
    ui_html("""
        <footer id="sobre" class="footer section-anchor">
            <div>
                <strong>Ranking BR · Pokémon GO</strong><br>
                Feito com orgulho pela comunidade brasileira.
            </div>
            <div>© 2026 Ranking BR. Não afiliado à Niantic, Inc.</div>
        </footer>
    """)


if "dark_theme" not in st.session_state:
    st.session_state.dark_theme = True

inject_css(st.session_state.dark_theme)
render_navbar()

with st.spinner("Carregando ranking..."):
    df = get_data()
    base_all = get_best_catches(df)

render_hero(base_all, df)

with st.container(key="podium_section"):
    ui_html('<div id="podio" class="section-anchor"></div>')
    section_header("Pódio", "Top 3 jogadores", "Os líderes atuais por maior quantidade registrada de capturas.")
    render_podium(base_all)

with st.container(key="chart_section"):
    ui_html('<div id="jogadores" class="section-anchor"></div>')
    section_header("Comparação", "Evolução de capturas", "Compare a evolução de até 10 jogadores no período selecionado.")
    chart_options = sorted(df["nickname"].dropna().unique())
    default_chart_players = base_all["nickname"].head(3).tolist()
    render_chart(df, chart_options, default_chart_players)

with st.container(key="rankings_section"):
    ui_html('<div id="rankings" class="section-anchor"></div>')
    section_header("Rankings", "Filtros & rankings", "Busque por nickname, filtre por estado e alterne as regras da média diária.")
    filtered_df, somente_melhor, apenas_mensais = render_filters(df)

    ranking_col, average_col = st.columns(2)
    with ranking_col:
        with st.container(key="ranking_general_panel"):
            render_paginated_table("Ranking geral por capturas totais", build_general_ranking(filtered_df), "ranking_general")

    with average_col:
        with st.container(key="ranking_average_panel"):
            render_paginated_table("Ranking por média diária", build_average_ranking(filtered_df, somente_melhor, apenas_mensais), "ranking_average")

filtered_base = get_best_catches(filtered_df)

with st.container(key="states_section"):
    ui_html('<div id="estados" class="section-anchor"></div>')
    state_title_col, state_sort_col = st.columns([0.62, 0.38], vertical_alignment="bottom")
    with state_title_col:
        section_header("Estados", "Estatísticas por estado", "Resumo dos estados representados no ranking filtrado.")
    with state_sort_col:
        with st.container(key="state_sort_control"):
            state_order = st.segmented_control(
                "Ordenar por",
                ["Total capturas", "Nº de jogadores", "Média"],
                default="Total capturas",
                selection_mode="single",
            )
    render_state_cards(build_state_stats(filtered_base, state_order))

with st.container(key="ranges_section"):
    ui_html('<div id="faixas" class="section-anchor"></div>')
    section_header("Distribuição", "Faixas de capturas", "Quantidade de jogadores acima dos principais marcos de captura.")
    with st.container(key="distribution_panel"):
        render_distribution(build_distribution(filtered_base))

render_footer()
=======
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from utils.load_data import load_data

# ======================
# CONFIG
# ======================
st.set_page_config(layout="wide")

# ======================
# CSS
# ======================
st.markdown("""
<style>

/* ================= HEADER ================= */
.header-container {
    display: flex;
    justify-content: center;
    margin-bottom: 60px;
}

.header-box {
    background: linear-gradient(135deg,#fff3b0,#ffe082);
    padding: 18px 28px;
    border-radius: 18px;
    box-shadow: 0px 6px 18px rgba(0,0,0,0.25);
}

.header-title {
    font-size: 34px;
    font-weight: 800;
    color: #5c4a00;
}

.header-sub {
    color: #7a6500;
    margin-left: 10px;
}

/* ================= TITULO PODIO ================= */
.podium-title {
    text-align: center;
    margin-bottom: 20px;
}

.podium-title span {
    display: inline-block;
    padding: 10px 24px;
    border-radius: 16px;
    background: #2e7d32;
    color: white;
    font-weight: 700;
    font-size: 20px;
}

/* ================= PODIO ================= */
.podium-container {
    display: flex;
    justify-content: center;
    overflow-x: auto;          /* ✅ permite scroll */
    padding-bottom: 10px;
}

/* container real */
.podium {
    display: flex;
    gap: 16px;
    align-items: flex-end;
    min-width: 650px;          /* ✅ força largura mínima */
}

.podium {
    display: flex;
    gap: 16px;
    align-items: flex-end;
}

/* BLOCO */
.block {
    width: 130px;
    padding: 12px;
    border-radius: 18px 18px 0 0;
    text-align: center;
    font-weight: bold;
    font-size: 16px;

    /* ✅ CONTRASTE GARANTIDO */
    color: #1a1a1a;

    /* ✅ CONTORNO */
    text-shadow:
        0px 1px 0px rgba(255,255,255,0.6),
        0px 0px 4px rgba(0,0,0,0.4);

    transition: 0.25s;
}

/* ALTURA + CORES */
.first  { height: 210px; background: #d4edda; color:#1b5e20 !important;}
.second { height: 170px; background: #e8f5e9; color:#1b5e20 !important;}
.third  { height: 150px; background: #fff9c4; color:#8a5a00 !important;}
.fourth { height: 130px; background: #e3f2fd; color:#0d47a1 !important;}
.fifth  { height: 120px; background: #f1f8e9; color:#33691e !important;}

/* HOVER */
.block:hover {
    transform: translateY(-6px) scale(1.03);
}

/* ================= NOMES ================= */
.player {
    display: flex;
    justify-content: center;
    width: 100%;
    margin-top: 10px;
}

.player span {
    display: flex;
    justify-content: center;
    align-items: center;

    min-width: 110px;
    text-align: center;

    padding: 6px 14px;
    border-radius: 12px;

    background: rgba(255,255,255,0.9);
    color: #111;

    font-weight: 600;

    /* efeito moderno */
    box-shadow: 0px 3px 8px rgba(0,0,0,0.2);
}

/* DARK MODE */
@media (prefers-color-scheme: dark) {
    .player span {
        background: rgba(200,200,200,0.2);
        color: white;
    }
}

</style>
""", unsafe_allow_html=True)

# ======================
# DATA
# ======================
@st.cache_data
def get_data():
    return load_data()

df = get_data()

# ======================
# HEADER
# ======================
st.markdown(
'<div class="header-container"><div class="header-box">'
'<span class="header-title">Dashboard de Jogadores PoGo</span>'
'<span class="header-sub">by Enzo Sartorelli</span>'
'</div></div>', unsafe_allow_html=True
)

# ======================
# PODIO
# ======================
idx = df.groupby("id_jogador")["catches"].idxmax()
ranking_podio = df.loc[idx][["nickname","catches"]].sort_values("catches", ascending=False).head(5).reset_index(drop=True)

visual_order = [3,1,0,2,4]
classes_map = {0:"first",1:"second",2:"third",3:"fourth",4:"fifth"}
medals = {0:"🥇",1:"🥈",2:"🥉",3:"🏅",4:"🏅"}

html = '<div class="podium-container"><div class="podium">'

for pos in visual_order:
    if pos >= len(ranking_podio): continue
    row = ranking_podio.iloc[pos]
    val = f"{int(row['catches']):,}".replace(",", ".")

    html += f'<div><div class="block {classes_map[pos]}">{medals[pos]}<br>#{pos+1}<br>{val}</div>'
    html += f'<div class="player"><span>{row["nickname"]}</span></div></div>'

html += '</div></div>'
st.markdown(html, unsafe_allow_html=True)

st.divider()

# ======================
# GRAFICO
# ======================
st.subheader("📊 Comparação entre Jogadores")

players_selected = st.multiselect(
    "Selecione até 8 jogadores",
    sorted(df["nickname"].unique()),
    max_selections=8
)

if players_selected:
    fig = go.Figure()
    cores = ["#00E676","#69F0AE","#00C853","#18FFFF","#40C4FF","#FFD740","#FFAB00","#FF6F00"]

    for i, player in enumerate(players_selected):
        df_p = df[df["nickname"]==player].sort_values("date")

        fig.add_trace(go.Scatter(
            x=df_p["date"],
            y=df_p["catches"],
            mode="lines+markers",
            name=player,
            line=dict(width=4,color=cores[i%len(cores)],shape="spline")
        ))

    fig.update_layout(template="plotly_dark",height=520,hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

# ======================
# FILTROS
# ======================
st.divider()
st.subheader("🎯 Filtros")

col1,col2,col3,col4 = st.columns([2,2,1,1])

states = sorted(df["state"].dropna().unique())

with col1:
    selected_states = st.multiselect("📍 Estado", states)

df_filtered = df.copy()

if selected_states:
    df_filtered = df_filtered[df_filtered["state"].isin(selected_states)]

players = sorted(df_filtered["nickname"].unique())

with col2:
    selected_players = st.multiselect("👤 Jogadores", players)

if selected_players:
    df_filtered = df_filtered[df_filtered["nickname"].isin(selected_players)]

with col3:
    somente_melhor = st.checkbox("🏆 Melhor média")

with col4:
    apenas_mensais = st.checkbox("📅 Apenas mensais")

df = df_filtered

# ======================
# RANKINGS
# ======================
col1,col2 = st.columns(2)

with col1:
    st.subheader("🏆 Maior Captura por Jogador")

    idx = df.groupby("id_jogador")["catches"].idxmax()

    ranking = df.loc[idx][["nickname","state","catches","date"]]
    ranking = ranking.sort_values("catches", ascending=False)

    ranking["Ranking"] = range(1, len(ranking)+1)
    ranking["Catches"] = ranking["catches"].apply(lambda x: f"{int(x):,}".replace(",", "."))
    ranking["Data"] = pd.to_datetime(ranking["date"]).dt.date

    ranking = ranking[["Ranking","nickname","state","Catches","Data"]]
    ranking.columns = ["Ranking","Jogador","Estado","Catches","Data"]

    st.dataframe(ranking, use_container_width=True, height=500, hide_index=True)

with col2:
    st.subheader("📈 Maior Média Diária")

    resultados = []

    for id_jogador, group in df.groupby("id_jogador"):
        group = group.sort_values("date").reset_index(drop=True)

        if len(group) < 2:
            continue

        nome = group["nickname"].iloc[-1]
        estado = group["state"].iloc[0]

        for i in range(len(group)):
            for j in range(i+1, len(group)):

                d1 = group.loc[i, "date"]
                d2 = group.loc[j, "date"]

                c1 = group.loc[i, "catches"]
                c2 = group.loc[j, "catches"]

                dias = (d2 - d1).days
                ganho = c2 - c1

                if dias <= 0 or ganho <= 0:
                    continue

                if apenas_mensais and dias > 32:
                    continue

                media = ganho / dias

                resultados.append({
                    "nickname": nome,
                    "state": estado,
                    "media": int(media),
                    "data_inicial": d1.date(),
                    "data_final": d2.date(),
                    "dias": dias,
                    "catches_periodo": ganho
                })

    df_media = pd.DataFrame(resultados)

    if not df_media.empty:

        if somente_melhor:
            df_media = df_media.sort_values("media", ascending=False) \
                               .groupby("nickname") \
                               .head(1)

        df_media = df_media.sort_values("media", ascending=False)

        df_media["ranking"] = range(1, len(df_media)+1)

        df_media = df_media[[
            "ranking","nickname","state","media",
            "data_inicial","data_final","dias","catches_periodo"
        ]]

        df_media.columns = [
            "Ranking","Jogador","Estado","Média",
            "Data Inicial","Data Final","Dias","Catches no Período"
        ]

        st.dataframe(df_media, use_container_width=True, height=500, hide_index=True)

# ======================
# 📊 Estatísticas Gerais
# ======================
st.divider()
st.subheader("📊 Estatísticas Gerais")

idx = df.groupby("id_jogador")["catches"].idxmax()

base = df.loc[idx][["id_jogador","nickname","state","catches"]]

base = base.sort_values("catches", ascending=False)
base["position"] = range(1, len(base)+1)

# KPIs
c1, c2, c3, c4 = st.columns(4)

c1.metric("Estados", base["state"].nunique())
c2.metric("Jogadores", base["id_jogador"].nunique())
c3.metric("Soma Top", f"{int(base['catches'].sum()):,}".replace(",", "."))
c4.metric("Soma Total", f"{int(df['catches'].sum()):,}".replace(",", "."))

# ======================
# 📊 TABELA POR ESTADO (COMPLETA)
# ======================
dados = []
total = len(base)

for estado, group in base.groupby("state"):

    qtd = len(group)
    perc = qtd / total

    avg_catch = group["catches"].mean()
    avg_pos = group["position"].mean()
    best_pos = group["position"].min()

    best_player = group.loc[group["position"].idxmin(),"nickname"]

    dados.append({
        "Estado": estado,
        "Qtd Jogadores": qtd,
        "%": f"{perc:.0%}",
        "Média Catches": int(avg_catch),
        "Média Ranking": round(avg_pos, 2),
        "Melhor Ranking": f"{best_pos} 👤 {best_player}"
    })

df_estado = pd.DataFrame(dados)

df_estado = df_estado.sort_values("Estado")

df_estado["Média Catches"] = df_estado["Média Catches"].apply(
    lambda x: f"{x:,}".replace(",", ".")
)

st.dataframe(df_estado, use_container_width=True, height=400, hide_index=True)

# ======================
# DISTRIBUIÇÃO (ATUALIZADA)
# ======================
st.divider()
st.subheader("📊 Distribuição de Jogadores por Faixa de Catches")

faixas = [
    300000, 400000, 500000, 600000, 700000, 800000, 900000,
    1000000, 1100000, 1200000, 1300000, 1400000,
    1500000, 1750000, 2000000, 2250000, 2500000,
    2750000, 3000000
]

resultados = []

for i in range(len(faixas)-1):

    inferior = faixas[i]
    superior = faixas[i+1]

    faixa_df = base[
        (base["catches"] >= inferior) &
        (base["catches"] < superior)
    ]

    acima_df = base[base["catches"] >= superior]

    resultados.append({
        "Faixa": f"{inferior:,} - {superior:,}".replace(",", "."),
        "Jogadores na Faixa": len(faixa_df),
        "Jogadores Acima": len(acima_df)
    })

df_faixas = pd.DataFrame(resultados)

st.dataframe(
    df_faixas,
    use_container_width=True,
    hide_index=True,
    height=450
)
>>>>>>> 8de7978d80c81cd9934320adbf1ebd3395b7fa29
