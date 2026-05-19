from html import escape
from datetime import date
import hmac

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import ADMIN_PASSWORD, DATA_SOURCE, ENABLE_ADMIN
from src.database.connection import has_database_config
from src.metrics.averages import build_average_ranking as compute_average_ranking
from src.metrics.distribution import build_distribution as compute_distribution
from src.metrics.formatting import format_compact, format_int, initials
from src.metrics.rankings import build_general_ranking as compute_general_ranking
from src.metrics.rankings import get_best_catches as compute_best_catches
from src.metrics.states import build_state_stats as compute_state_stats
from src.services.data_source import get_data_source_fingerprint, load_dashboard_data
from src.services.admin_review import approve_record, list_pending_records, reject_record, update_pending_record
from src.services.submissions import submit_player_record
from src.validation.submissions import BRAZILIAN_STATES


st.set_page_config(
    page_title="Ranking BR - Pokémon GO Brasil",
    page_icon="🇧🇷",
    layout="wide",
    initial_sidebar_state="collapsed",
)


MAX_CATCHES_INPUT = 9_999_999_999


@st.cache_data(show_spinner=False, ttl=300)
def get_data(_fingerprint):
    return load_dashboard_data().data


@st.cache_data(show_spinner=False)
def get_best_catches(data):
    return compute_best_catches(data)


@st.cache_data(show_spinner=False)
def build_general_ranking(data):
    return compute_general_ranking(data)


@st.cache_data(show_spinner=False)
def build_average_ranking(data, somente_melhor, apenas_mensais):
    return compute_average_ranking(data, somente_melhor, apenas_mensais)


@st.cache_data(show_spinner=False)
def build_state_stats(base, order_by="Total capturas"):
    return compute_state_stats(base, order_by)


@st.cache_data(show_spinner=False)
def build_distribution(base):
    return compute_distribution(base)


def ui_html(markup):
    st.html(markup)


def clear_dashboard_caches():
    get_data.clear()
    get_best_catches.clear()
    build_general_ranking.clear()
    build_average_ranking.clear()
    build_state_stats.clear()
    build_distribution.clear()


def render_feedback(result, success_message, info_message=None):
    if not result:
        return
    if result.get("success"):
        st.success(success_message)
        if info_message:
            st.info(info_message)
        return
    st.error("; ".join(result.get("errors", ["Não foi possível concluir a ação."])))


def render_public_submission_page():
    ui_html("""
        <section class="page-hero submission-hero">
            <div class="eyebrow">Envio público</div>
            <h1 class="page-title">Enviar dados</h1>
            <p class="page-copy">
                Registros enviados pelo público entram como pendentes e só aparecem no ranking
                depois da revisão administrativa.
            </p>
        </section>
    """)

    if DATA_SOURCE != "database":
        st.warning("Envio público indisponível no modo Excel. Ative DATA_SOURCE=database para usar este formulário.")
        return
    if not has_database_config():
        st.warning("Envio público indisponível: banco de dados não configurado.")
        return

    render_feedback(
        st.session_state.pop("public_submission_result", None),
        "Registro enviado para revisão.",
        "O envio ficou como pendente. Depois da aprovação do admin, ele entra no dashboard.",
    )

    with st.container(key="public_submission_shell"):
        with st.form("public_submission_form", clear_on_submit=True):
            left, right = st.columns([0.58, 0.42], vertical_alignment="top")
            with left:
                nickname = st.text_input("Nickname", max_chars=80, placeholder="Seu nickname no jogo")
                data_referencia = st.date_input("Data do registro", value=date.today(), max_value=date.today())
                catches = st.number_input(
                    "Total de capturas",
                    min_value=1,
                    max_value=MAX_CATCHES_INPUT,
                    step=1,
                    format="%d",
                )
            with right:
                state = st.selectbox("Estado (UF)", BRAZILIAN_STATES, index=BRAZILIAN_STATES.index("SP"))
                contato = st.text_input("Contato opcional", max_chars=120, placeholder="Email, WhatsApp ou @")
                observacao = st.text_area("Observação opcional", max_chars=500, height=126)
            submitted = st.form_submit_button("Enviar para revisão", type="primary")

    if submitted:
        result = submit_player_record({
            "nickname": nickname,
            "state": state,
            "data_referencia": data_referencia,
            "catches": int(catches),
            "periodo_tipo": "mensal",
            "status": "pendente",
            "fonte": "site",
            "observacao": observacao,
            "contato_envio": contato,
        })
        st.session_state.public_submission_result = result
        st.rerun()


def render_admin_page():
    if not ENABLE_ADMIN or not ADMIN_PASSWORD:
        return

    ui_html("""
        <section class="page-hero admin-hero">
            <div class="eyebrow">Área protegida</div>
            <h1 class="page-title">Admin</h1>
            <p class="page-copy">
                Inclusão manual, revisão de pendentes e auditoria operacional dos registros.
            </p>
        </section>
    """)

    last_result = st.session_state.pop("admin_last_result", None)
    if last_result and last_result.get("success"):
        if "jogador_criado" in last_result:
            acao = "criado" if last_result.get("jogador_criado") else "encontrado"
            st.success(
                f"Registro inserido. Jogador {acao}. "
                f"ID jogador: {last_result.get('jogador_id')} | "
                f"ID registro: {last_result.get('record_id')} | "
                f"Status: {last_result.get('status')}"
            )
        else:
            st.success(
                f"Ação aplicada no registro {last_result.get('record_id')}. "
                f"Status: {last_result.get('status', 'pendente')}"
            )
    elif last_result:
        st.error("; ".join(last_result.get("errors", ["Erro ao salvar registro."])))

    if not has_database_config():
        st.warning("Admin indisponível: banco não configurado.")
        return

    if not st.session_state.get("admin_authenticated"):
        with st.container(key="admin_login_shell"):
            password = st.text_input("Senha admin", type="password", key="admin_password_input")
            if st.button("Entrar", type="primary", key="admin_login_button"):
                if hmac.compare_digest(password or "", ADMIN_PASSWORD):
                    st.session_state.admin_authenticated = True
                    st.rerun()
                st.error("Senha inválida.")
        return

    with st.container(key="admin_session_bar"):
        left, right = st.columns([0.78, 0.22], vertical_alignment="center")
        with left:
            st.caption("Sessão administrativa ativa.")
        with right:
            if st.button("Sair", key="admin_logout_button"):
                st.session_state.admin_authenticated = False
                st.rerun()

    insert_tab, pending_tab = st.tabs(["Novo registro", "Pendentes"])

    with insert_tab:
        with st.container(key="admin_insert_shell"):
            with st.form("admin_insert_record_form", clear_on_submit=True):
                left, right = st.columns([0.58, 0.42], vertical_alignment="top")
                with left:
                    nickname = st.text_input("Nickname", max_chars=80)
                    data_referencia = st.date_input("Data do registro", value=date.today(), max_value=date.today())
                    catches = st.number_input(
                        "Total de capturas",
                        min_value=1,
                        max_value=MAX_CATCHES_INPUT,
                        step=1,
                        format="%d",
                    )
                with right:
                    state = st.selectbox("Estado (UF)", BRAZILIAN_STATES, index=BRAZILIAN_STATES.index("SP"))
                    periodo_tipo = st.selectbox("Tipo de período", ["mensal", "semanal"], index=0)
                    status = st.selectbox("Status", ["validado", "pendente"], index=0)
                    observacao = st.text_area("Observação opcional", max_chars=500, height=108)
                submitted = st.form_submit_button("Salvar registro", type="primary")

            if submitted:
                result = submit_player_record({
                    "nickname": nickname,
                    "state": state,
                    "data_referencia": data_referencia,
                    "catches": int(catches),
                    "periodo_tipo": periodo_tipo,
                    "status": status,
                    "fonte": "admin",
                    "observacao": observacao,
                }, allow_validated=True)
                if result.get("success"):
                    clear_dashboard_caches()
                st.session_state.admin_last_result = result
                st.rerun()

    with pending_tab:
        try:
            pending_records = list_pending_records()
        except Exception:
            st.error("Não foi possível carregar os registros pendentes agora.")
            return

        if not pending_records:
            st.info("Nenhum registro pendente.")
            return

        pending_table = pd.DataFrame(pending_records)
        preview_columns = [
            "id", "nickname", "state", "data_referencia", "catches",
            "periodo_tipo", "contato_envio", "observacao", "created_at", "status",
        ]
        st.dataframe(
            pending_table[preview_columns],
            hide_index=True,
            use_container_width=True,
            height=min(420, 82 + len(pending_table) * 36),
        )

        labels = [
            f"#{row['id']} · {row['nickname']} · {row['data_referencia']} · {format_int(row['catches'])}"
            for row in pending_records
        ]
        selected_label = st.selectbox("Selecionar registro", labels, key="admin_pending_select")
        selected_index = labels.index(selected_label)
        record = pending_records[selected_index]
        record_id = int(record["id"])
        state_value = str(record["state"] or "SP").upper()
        state_index = BRAZILIAN_STATES.index(state_value) if state_value in BRAZILIAN_STATES else BRAZILIAN_STATES.index("SP")

        with st.container(key="admin_review_shell"):
            with st.form("admin_review_record_form"):
                left, right = st.columns([0.52, 0.48], vertical_alignment="top")
                with left:
                    edited_state = st.selectbox("Estado (UF)", BRAZILIAN_STATES, index=state_index, key=f"state_{record_id}")
                    edited_date = st.date_input(
                        "Data",
                        value=record["data_referencia"],
                        max_value=date.today(),
                        key=f"date_{record_id}",
                    )
                    edited_catches = st.number_input(
                        "Total de capturas",
                        min_value=1,
                        max_value=MAX_CATCHES_INPUT,
                        value=int(record["catches"]),
                        step=1,
                        format="%d",
                        key=f"catches_{record_id}",
                    )
                    edited_period = st.selectbox(
                        "Tipo de período",
                        ["mensal", "semanal"],
                        index=["mensal", "semanal"].index(record["periodo_tipo"]),
                        key=f"period_{record_id}",
                    )
                with right:
                    st.text_input(
                        "Contato informado",
                        value=str(record.get("contato_envio") or ""),
                        disabled=True,
                        key=f"contact_{record_id}",
                    )
                    edited_note = st.text_area(
                        "Observação",
                        value=str(record.get("observacao") or ""),
                        max_chars=500,
                        height=104,
                        key=f"note_{record_id}",
                    )
                    admin_note = st.text_area("Nota do admin", max_chars=500, height=104, key=f"admin_note_{record_id}")
                action = st.radio(
                    "Ação",
                    ["Apenas salvar edição", "Aprovar", "Rejeitar", "Excluir logicamente"],
                    horizontal=True,
                    key=f"action_{record_id}",
                )
                review_submitted = st.form_submit_button("Aplicar", type="primary")

            if review_submitted:
                update_result = update_pending_record(
                    record_id,
                    {
                        "state": edited_state,
                        "data_referencia": edited_date,
                        "catches": int(edited_catches),
                        "periodo_tipo": edited_period,
                        "observacao": edited_note,
                        "admin_note": admin_note,
                    },
                )
                result = update_result
                if update_result.get("success") and action == "Aprovar":
                    result = approve_record(record_id, admin_note=admin_note)
                elif update_result.get("success") and action in {"Rejeitar", "Excluir logicamente"}:
                    note = admin_note
                    if action == "Excluir logicamente":
                        note = f"{admin_note}\nExclusão lógica solicitada pelo admin.".strip()
                    result = reject_record(record_id, admin_note=note)

                if result.get("success"):
                    clear_dashboard_caches()
                st.session_state.admin_last_result = result
                st.rerun()


def trainer_avatar(name, place):
    accents = {
        1: ("#e2b84f", "#7fa35a", "#242016"),
        2: ("#b9b6ff", "#8fa7ff", "#222638"),
        3: ("#b06b4f", "#e2b84f", "#2c1f1a"),
    }
    cap_color, jacket_color, shadow_color = accents.get(place, accents[2])
    badge = escape(initials(name)[:1])

    return f"""
        <svg class="trainer-avatar-svg" viewBox="0 0 120 120" role="img" aria-label="Avatar de treinador">
            <defs>
                <radialGradient id="trainer-glow-{place}" cx="50%" cy="28%" r="70%">
                    <stop offset="0%" stop-color="rgba(255,255,255,0.30)" />
                    <stop offset="52%" stop-color="rgba(226,184,79,0.14)" />
                    <stop offset="100%" stop-color="rgba(15,16,8,0)" />
                </radialGradient>
                <linearGradient id="trainer-jacket-{place}" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="{jacket_color}" />
                    <stop offset="100%" stop-color="{shadow_color}" />
                </linearGradient>
            </defs>
            <circle cx="60" cy="60" r="58" fill="url(#trainer-glow-{place})" />
            <path d="M26 105c5-21 18-32 34-32s29 11 34 32" fill="url(#trainer-jacket-{place})" />
            <path d="M40 97c4-11 11-17 20-17s16 6 20 17" fill="rgba(10,11,8,0.34)" />
            <circle cx="60" cy="54" r="21" fill="#d8b18b" />
            <path d="M39 55c2-15 11-24 25-24 11 0 19 7 22 19-9-5-18-7-29-6-8 1-14 4-18 11z" fill="#201912" />
            <path d="M31 43c12-15 39-20 61-4-14 1-30 4-47 11-5 2-10 0-14-7z" fill="{cap_color}" />
            <path d="M76 44c10 0 19 3 27 8-10 2-21 1-31-2z" fill="{cap_color}" opacity="0.78" />
            <circle cx="60" cy="40" r="8" fill="rgba(15,16,8,0.32)" />
            <circle cx="60" cy="40" r="5" fill="rgba(240,239,255,0.86)" />
            <text x="60" y="43" text-anchor="middle" font-size="7" font-weight="900" fill="#171207">{badge}</text>
            <path d="M50 59h.01M70 59h.01" stroke="#18140f" stroke-width="4" stroke-linecap="round" />
            <path d="M54 68c4 2.6 8 2.6 12 0" fill="none" stroke="#7b4638" stroke-width="2.4" stroke-linecap="round" />
            <path d="M43 82l17 14 17-14" fill="none" stroke="rgba(240,239,255,0.58)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M35 105h50" stroke="rgba(226,184,79,0.46)" stroke-width="3" stroke-linecap="round" />
        </svg>
    """


def inject_css(dark_mode):
    palette = {
        "bg": "#0c1117" if dark_mode else "#f4f6f8",
        "bg2": "#111a21" if dark_mode else "#eef3f1",
        "card": "rgba(19, 27, 36, 0.86)" if dark_mode else "rgba(255, 255, 255, 0.92)",
        "card2": "rgba(25, 38, 47, 0.72)" if dark_mode else "rgba(244, 248, 247, 0.92)",
        "card3": "rgba(9, 14, 20, 0.66)" if dark_mode else "rgba(255, 255, 255, 0.78)",
        "border": "rgba(125, 220, 205, 0.24)" if dark_mode else "rgba(27, 85, 82, 0.18)",
        "border2": "rgba(226, 184, 79, 0.28)" if dark_mode else "rgba(178, 124, 38, 0.24)",
        "line": "rgba(177, 207, 219, 0.12)" if dark_mode else "rgba(39, 64, 73, 0.12)",
        "text": "#eef6f8" if dark_mode else "#17242b",
        "muted": "#a9bdc7" if dark_mode else "#526870",
        "gold": "#e2b84f",
        "green": "#4cc9b0",
        "terra": "#d47b63",
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
        --rb-radius-lg: 12px;
        --rb-radius-md: 8px;
        --rb-shadow: 0 28px 90px rgba(0, 0, 0, 0.36);
    }}

    html {{
        scroll-behavior: smooth;
    }}

    .stApp {{
        padding-top: 0 !important;
        overflow-x: hidden;
        color: var(--rb-text);
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: linear-gradient(140deg, var(--rb-bg), var(--rb-bg-2) 54%, #071016);
    }}

    .block-container {{
        max-width: 1480px;
        padding: 2rem 1.55rem 4rem !important;
    }}

    section.main > div {{
        padding-top: 4rem !important;
    }}

    .section-anchor {{
        scroll-margin-top: 7rem;
    }}

    .st-key-navbar {{
        position: sticky;
        top: 0.35rem;
        z-index: 80;
        margin: 0 0 0.75rem;
        padding: 0.72rem 1rem;
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-md);
        background: rgba(13, 20, 27, 0.86);
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
        border-radius: var(--rb-radius-md);
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
        border-radius: var(--rb-radius-lg);
        padding: clamp(1.3rem, 3vw, 2.6rem);
        background:
            linear-gradient(140deg, rgba(76,201,176,0.12), transparent 42%),
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
        opacity: 0.12;
        background: linear-gradient(135deg, rgba(76,201,176,0.72), rgba(226,184,79,0.34));
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
        position: relative;
        overflow: hidden;
        min-height: 210px;
        padding: 1.45rem 1.15rem;
        border: 1px solid var(--rb-border);
        border-radius: 24px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 0.15rem;
        text-align: center;
        background: linear-gradient(160deg, rgba(45,33,24,0.72), rgba(12,13,9,0.48));
        box-shadow: 0 18px 54px rgba(0,0,0,0.24), inset 0 1px 0 rgba(255,255,255,0.045);
        transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease, background 180ms ease;
    }}

    .stat-card::before {{
        content: "";
        position: absolute;
        inset: 0;
        background:
            radial-gradient(circle at 50% 18%, rgba(226,184,79,0.10), transparent 8.5rem),
            linear-gradient(180deg, rgba(255,255,255,0.045), transparent 38%);
        pointer-events: none;
    }}

    .stat-card:hover {{
        transform: translateY(-5px);
        border-color: rgba(226,184,79,0.48);
        box-shadow: 0 24px 70px rgba(0,0,0,0.30), 0 0 42px rgba(226,184,79,0.10);
    }}

    .stat-icon {{
        position: relative;
        z-index: 1;
        color: var(--rb-gold);
        width: 48px;
        height: 48px;
        margin-bottom: 0.92rem;
        display: grid;
        place-items: center;
        border-radius: 18px;
        border: 1px solid rgba(226,184,79,0.20);
        background: rgba(226,184,79,0.075);
        box-shadow: 0 12px 34px rgba(226,184,79,0.10), inset 0 1px 0 rgba(255,255,255,0.08);
    }}

    .stat-icon svg {{
        width: 27px;
        height: 27px;
        display: block;
        stroke: currentColor;
        fill: none;
        stroke-width: 1.9;
        stroke-linecap: round;
        stroke-linejoin: round;
    }}

    .stat-label {{
        position: relative;
        z-index: 1;
        color: var(--rb-muted);
        font-size: 0.68rem;
        font-weight: 850;
        letter-spacing: 0.17em;
        text-transform: uppercase;
        max-width: 12.5rem;
        line-height: 1.45;
    }}

    .stat-value {{
        position: relative;
        z-index: 1;
        margin-top: 0.7rem;
        color: var(--rb-text);
        font-size: clamp(2.1rem, 3.25vw, 3.15rem);
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
        padding: 1.28rem 1.1rem 1.18rem;
        border: 1px solid rgba(214,174,72,0.24);
        border-radius: 28px;
        background:
            radial-gradient(circle at 50% 0%, rgba(255,255,255,0.06), transparent 9rem),
            linear-gradient(155deg, rgba(45,33,24,0.88), rgba(16,15,10,0.68));
        box-shadow: 0 20px 62px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.045);
        text-align: center;
        transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
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
        transform: translateY(-5px);
        border-color: rgba(226,184,79,0.55);
        box-shadow: 0 26px 72px rgba(0,0,0,0.30), 0 0 38px rgba(127,163,90,0.08);
    }}

    .podium-card.champion {{
        min-height: 280px;
        border-color: rgba(226,184,79,0.58);
        box-shadow: 0 22px 82px rgba(226,184,79,0.13), 0 22px 62px rgba(0,0,0,0.3);
    }}

    .podium-crown {{
        position: absolute;
        top: 0.38rem;
        left: 50%;
        transform: translateX(-50%);
        color: var(--rb-gold);
        width: 38px;
        height: 38px;
        text-shadow: 0 0 24px rgba(226,184,79,0.55);
        filter: drop-shadow(0 0 14px rgba(226,184,79,0.38));
        z-index: 2;
    }}

    .podium-crown svg {{
        width: 100%;
        height: 100%;
        display: block;
        fill: currentColor;
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
        width: 92px;
        height: 92px;
        margin: 0.05rem auto 0.78rem;
        display: grid;
        place-items: center;
        border-radius: 50%;
        border: 3px solid rgba(226,184,79,0.65);
        background:
            radial-gradient(circle at 42% 18%, rgba(255,255,255,0.26), transparent 28%),
            linear-gradient(145deg, rgba(143,167,255,0.42), rgba(226,184,79,0.24) 48%, rgba(127,163,90,0.28));
        box-shadow: 0 16px 42px rgba(0,0,0,0.34), 0 0 24px rgba(226,184,79,0.13), inset 0 1px 0 rgba(255,255,255,0.18);
        overflow: hidden;
        position: relative;
        z-index: 1;
    }}

    .podium-avatar svg {{
        width: 100%;
        height: 100%;
        display: block;
    }}

    .champion .podium-avatar {{
        width: 110px;
        height: 110px;
        margin-top: 1.38rem;
        border-color: rgba(226,184,79,0.86);
        box-shadow: 0 20px 54px rgba(0,0,0,0.38), 0 0 34px rgba(226,184,79,0.23), inset 0 1px 0 rgba(255,255,255,0.2);
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

    .ranking-toggles,
    .st-key-filter_toggle_bar {{
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 14px;
        flex-wrap: wrap;
        width: 100%;
        margin: -0.35rem 0 0.7rem;
        overflow: visible;
    }}

    .st-key-filter_toggle_bar > [data-testid="stHorizontalBlock"],
    .st-key-filter_toggle_bar > div > [data-testid="stHorizontalBlock"],
    .st-key-filter_toggle_bar > div > div > [data-testid="stHorizontalBlock"] {{
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 14px;
        flex-wrap: wrap;
        width: 100%;
        overflow: visible;
    }}

    .st-key-filters_panel [data-testid="stHorizontalBlock"] {{
        align-items: flex-end;
    }}

    .st-key-filter_states [data-testid="stWidgetLabel"] {{
        text-align: center;
    }}

    .st-key-filter_states [data-testid="stWidgetLabel"] p {{
        text-align: center;
        width: 100%;
    }}

    .st-key-filter_states div[data-testid="stButtonGroup"] {{
        justify-content: center;
    }}

    .toggle-pill,
    .st-key-filter_switch_mean,
    .st-key-filter_switch_monthly {{
        flex: 0 0 auto;
        flex-shrink: 0;
        width: auto;
        min-width: 180px;
        min-height: 46px;
        padding: 10px 18px;
        border: 1px solid rgba(226,184,79,0.22);
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        box-sizing: border-box;
        white-space: nowrap;
        overflow: hidden;
        overflow-wrap: normal;
        word-break: keep-all;
        background: rgba(255,255,255,0.035);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.06);
        transition: transform 150ms ease, border-color 150ms ease, background 150ms ease, box-shadow 150ms ease;
    }}

    .st-key-filter_switch_mean > div,
    .st-key-filter_switch_monthly > div {{
        width: auto !important;
        min-width: max-content !important;
        max-width: none !important;
        flex: 0 0 auto !important;
        overflow: visible !important;
    }}

    .st-key-filter_switch_mean [data-testid="stToggle"],
    .st-key-filter_switch_monthly [data-testid="stToggle"] {{
        width: auto !important;
        min-width: max-content !important;
        max-width: none !important;
        display: inline-flex !important;
        align-items: center !important;
        gap: 12px !important;
        flex: 0 0 auto !important;
        flex-shrink: 0 !important;
        overflow: visible !important;
        white-space: nowrap !important;
    }}

    .st-key-filter_switch_mean label,
    .st-key-filter_switch_monthly label {{
        display: inline-flex !important;
        align-items: center !important;
        gap: 12px !important;
        width: auto !important;
        min-width: max-content !important;
        white-space: nowrap !important;
        flex-shrink: 0 !important;
    }}

    .st-key-filter_switch_mean [data-testid="stWidgetLabel"],
    .st-key-filter_switch_monthly [data-testid="stWidgetLabel"] {{
        width: auto !important;
        min-width: max-content !important;
        max-width: none !important;
        flex: 0 0 auto !important;
        overflow: visible !important;
        white-space: nowrap !important;
    }}

    .st-key-filter_switch_mean:hover,
    .st-key-filter_switch_monthly:hover {{
        border-color: rgba(127,163,90,0.46);
        background: rgba(127,163,90,0.085);
        box-shadow: 0 12px 28px rgba(0,0,0,0.16), 0 0 24px rgba(127,163,90,0.06);
    }}

    .st-key-filter_switch_mean [data-testid="stWidgetLabel"] p,
    .st-key-filter_switch_monthly [data-testid="stWidgetLabel"] p {{
        font-size: 0.78rem;
        font-weight: 820;
        color: var(--rb-text) !important;
        white-space: nowrap;
        overflow-wrap: normal;
        word-break: keep-all;
        line-height: 1.2;
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
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 0.9rem;
    }}

    .state-card {{
        min-height: 172px;
        padding: 1rem;
        border: 1px solid var(--rb-border);
        border-radius: 21px;
        background: linear-gradient(155deg, rgba(45,33,24,0.72), rgba(15,16,8,0.48));
        box-shadow: 0 16px 44px rgba(0,0,0,0.18);
        transition: transform 170ms ease, border-color 170ms ease, box-shadow 170ms ease;
    }}

    .state-card:hover {{
        transform: translateY(-4px);
        border-color: rgba(127,163,90,0.48);
        box-shadow: 0 20px 54px rgba(0,0,0,0.23), 0 0 28px rgba(127,163,90,0.08);
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
        padding: 0.26rem 0.55rem;
        border-radius: 999px;
        color: var(--rb-green);
        background: rgba(127,163,90,0.12);
        border: 1px solid rgba(127,163,90,0.18);
        font-size: 0.7rem;
        font-weight: 900;
        white-space: nowrap;
        line-height: 1;
    }}

    .state-metrics {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: clamp(0.62rem, 1vw, 0.9rem);
        margin-top: 1rem;
    }}

    .state-metrics > div {{
        min-width: 0;
        padding: 0.52rem 0.58rem;
        border: 1px solid rgba(240,218,159,0.075);
        border-radius: 14px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        background: rgba(255,255,255,0.025);
        text-align: center;
        box-sizing: border-box;
    }}

    .mini-label {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: fit-content;
        min-width: 72px;
        max-width: 100%;
        padding: 0 0.72rem;
        box-sizing: border-box;
        color: var(--rb-muted);
        font-size: 0.55rem;
        font-weight: 850;
        letter-spacing: 0.11em;
        text-transform: uppercase;
        line-height: 1.35;
        white-space: nowrap;
        overflow-wrap: normal;
        word-break: keep-all;
    }}

    .mini-value {{
        margin-top: 0.3rem;
        color: var(--rb-text);
        font-size: 0.86rem;
        line-height: 1.1;
        font-weight: 900;
        white-space: nowrap;
        overflow-wrap: normal;
        word-break: keep-all;
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

    .creator-line {{
        display: inline-flex;
        align-items: center;
        gap: 0.42rem;
        margin-top: 0.22rem;
        color: var(--rb-muted);
    }}

    .creator-mark {{
        width: 18px;
        height: 18px;
        border-radius: 999px;
        display: inline-grid;
        place-items: center;
        color: #171207;
        background: linear-gradient(145deg, #f0cc67, var(--rb-gold));
        font-size: 0.72rem;
        font-weight: 950;
        box-shadow: 0 0 18px rgba(226,184,79,0.18);
    }}

    .page-hero {{
        margin-bottom: 1rem;
        padding: clamp(1rem, 2.6vw, 1.55rem);
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-lg);
        background: linear-gradient(150deg, var(--rb-card), var(--rb-card-3));
        box-shadow: 0 18px 54px rgba(0,0,0,0.22);
    }}

    .page-title {{
        margin: 0.85rem 0 0.45rem;
        color: var(--rb-text);
        font-size: clamp(2rem, 4.3vw, 3.5rem);
        line-height: 1;
        font-weight: 950;
        letter-spacing: 0;
    }}

    .page-copy {{
        max-width: 760px;
        margin: 0;
        color: var(--rb-muted);
        line-height: 1.62;
    }}

    .st-key-public_submission_shell,
    .st-key-admin_login_shell,
    .st-key-admin_session_bar,
    .st-key-admin_insert_shell,
    .st-key-admin_review_shell {{
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-md);
        padding: clamp(0.9rem, 2vw, 1.15rem);
        background: linear-gradient(150deg, rgba(19,27,36,0.74), rgba(9,14,20,0.48));
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
    }}

    .st-key-admin_session_bar {{
        margin-bottom: 1rem;
    }}

    .stTabs [data-baseweb="tab-list"] {{
        gap: 0.45rem;
        border-bottom: 1px solid var(--rb-line);
    }}

    .stTabs [data-baseweb="tab"] {{
        border-radius: var(--rb-radius-md) var(--rb-radius-md) 0 0;
        color: var(--rb-muted);
        font-weight: 820;
    }}

    .stTabs [aria-selected="true"] {{
        color: var(--rb-text) !important;
        background: rgba(76,201,176,0.10);
    }}

    .stAlert {{
        border-radius: var(--rb-radius-md);
    }}

    .stat-card,
    .podium-card,
    .state-card,
    .range-card,
    .st-key-chart_panel,
    .st-key-filters_panel,
    .st-key-ranking_general_panel,
    .st-key-ranking_average_panel,
    .st-key-distribution_panel,
    .rb-table-wrap,
    .empty-state {{
        border-radius: var(--rb-radius-md) !important;
    }}

    label, .stMarkdown, .stTextInput label, .stMultiSelect label {{
        color: var(--rb-text) !important;
    }}

    div[data-baseweb="input"], div[data-baseweb="select"] > div {{
        border-color: var(--rb-border) !important;
        background-color: rgba(255,255,255,0.045) !important;
        border-radius: var(--rb-radius-md) !important;
    }}

    textarea {{
        border-radius: var(--rb-radius-md) !important;
        border-color: var(--rb-border) !important;
        background-color: rgba(255,255,255,0.045) !important;
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

    .stButton > button,
    .stFormSubmitButton > button {{
        min-height: 34px;
        width: 100%;
        border-radius: var(--rb-radius-md);
        border: 1px solid var(--rb-border);
        background: rgba(255,255,255,0.035);
        color: var(--rb-text);
        font-size: 0.78rem;
        padding: 0.32rem 0.65rem;
        transition: transform 150ms ease, border-color 150ms ease, background 150ms ease;
    }}

    .stButton > button:hover,
    .stFormSubmitButton > button:hover {{
        transform: translateY(-1px);
        border-color: rgba(226,184,79,0.55);
        background: rgba(226,184,79,0.11);
        color: var(--rb-text);
    }}

    .stButton > button:disabled,
    .stFormSubmitButton > button:disabled {{
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
            padding: 1.15rem 1rem;
        }}

        .stat-icon {{
            width: 44px;
            height: 44px;
            margin-bottom: 0.75rem;
        }}

        .stat-icon svg {{
            width: 25px;
            height: 25px;
        }}

        .podium-card.champion {{
            order: -1;
        }}

        .podium-avatar {{
            width: 88px;
            height: 88px;
        }}

        .champion .podium-avatar {{
            width: 104px;
            height: 104px;
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

        .ranking-toggles,
        .st-key-filter_toggle_bar {{
            justify-content: flex-start;
            margin: -0.1rem 0 0.65rem;
        }}

        .st-key-filter_toggle_bar > [data-testid="stHorizontalBlock"],
        .st-key-filter_toggle_bar > div > [data-testid="stHorizontalBlock"],
        .st-key-filter_toggle_bar > div > div > [data-testid="stHorizontalBlock"] {{
            justify-content: flex-start;
            flex-wrap: wrap;
            width: 100%;
            overflow: visible;
        }}

        .st-key-filter_switch_mean,
        .st-key-filter_switch_monthly {{
            min-width: 180px;
        }}

        .st-key-filter_states div[data-testid="stButtonGroup"] {{
            justify-content: flex-start;
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

        .stat-card {{
            min-height: 148px;
        }}

        .stat-value {{
            font-size: clamp(1.85rem, 11vw, 2.55rem);
        }}

        .state-grid,
        .range-grid {{
            grid-template-columns: 1fr;
        }}

        .state-card {{
            padding: 0.9rem;
        }}

        .state-metrics {{
            gap: 0.44rem;
        }}

        .state-metrics > div {{
            padding: 0.44rem 0.22rem;
            border-radius: 12px;
        }}

        .mini-label {{
            font-size: 0.48rem;
            letter-spacing: 0.06em;
            min-width: 64px;
            padding: 0 0.42rem;
        }}

        .mini-value {{
            font-size: 0.78rem;
        }}

        .st-key-filter_switch_mean,
        .st-key-filter_switch_monthly {{
            width: auto;
            min-width: 180px;
            min-height: 44px;
            padding: 9px 16px;
        }}

        .st-key-filter_switch_mean [data-testid="stToggle"],
        .st-key-filter_switch_monthly [data-testid="stToggle"] {{
            min-width: max-content;
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
                        <div class="stat-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24">
                                <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
                                <circle cx="9" cy="7" r="4" />
                                <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
                                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                            </svg>
                        </div>
                        <div class="stat-label">Jogadores monitorados</div>
                        <div class="stat-value">{format_int(jogadores)}</div>
                    </article>
                    <article class="stat-card">
                        <div class="stat-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24">
                                <circle cx="12" cy="12" r="9" />
                                <circle cx="12" cy="12" r="4" />
                                <path d="M12 3v3" />
                                <path d="M12 18v3" />
                                <path d="M3 12h3" />
                                <path d="M18 12h3" />
                            </svg>
                        </div>
                        <div class="stat-label">Capturas analisadas</div>
                        <div class="stat-value">{format_compact(capturas)}</div>
                    </article>
                    <article class="stat-card">
                        <div class="stat-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24">
                                <path d="M3 7l6-3 6 3 6-3v13l-6 3-6-3-6 3V7z" />
                                <path d="M9 4v13" />
                                <path d="M15 7v13" />
                                <circle cx="17" cy="8" r="1.8" />
                            </svg>
                        </div>
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
    crown = """
        <div class="podium-crown" aria-hidden="true">
            <svg viewBox="0 0 64 64">
                <path d="M8 24l13 12 11-24 11 24 13-12-6 28H14L8 24z" />
                <path d="M16 56h32" stroke="currentColor" stroke-width="5" stroke-linecap="round" />
            </svg>
        </div>
    """ if place == 1 else ""
    avatar = trainer_avatar(row["nickname"], place)
    return f"""
        <article class="{class_name}">
            {crown}
            <div class="podium-medal">{medal_labels[place]}</div>
            <div class="podium-avatar">{avatar}</div>
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

    with st.container(
        key="filter_toggle_bar",
        horizontal=True,
        horizontal_alignment="right",
        vertical_alignment="center",
        gap="small",
    ):
        with st.container(key="filter_switch_mean", width="content"):
            somente_melhor = st.toggle("Melhor média", value=False)
        with st.container(key="filter_switch_monthly", width="content"):
            apenas_mensais = st.toggle("Apenas mensais", value=False)

    with st.container(key="filters_panel"):
        search_col, states_col = st.columns([0.30, 0.70], vertical_alignment="bottom")
        with search_col:
            search = st.text_input("Buscar por nickname", placeholder="⌕ Buscar por nickname")
        with states_col:
            with st.container(key="filter_states"):
                selected_states = st.pills(
                    "Filtrar por estado",
                    states,
                    selection_mode="multi",
                    default=[],
                )

    filtered = data
    if search:
        filtered = filtered[filtered["nickname"].str.contains(search.strip(), case=False, na=False)]
    if selected_states:
        filtered = filtered[filtered["state"].isin(selected_states)]

    return filtered, somente_melhor, apenas_mensais


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
                    <div class="state-position">#{int(row["Posição"])}</div>
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
                <br><span class="creator-line"><span class="creator-mark">E</span>feito por Enzo Sartorelli</span>
            </div>
            <div>© 2026 Ranking BR. Não afiliado à Niantic, Inc.</div>
        </footer>
    """)


if "dark_theme" not in st.session_state:
    st.session_state.dark_theme = True

inject_css(st.session_state.dark_theme)
page_param = str(st.query_params.get("page", "")).strip().lower()
page_options = ["Dashboard", "Enviar dados"]
if ENABLE_ADMIN and ADMIN_PASSWORD:
    page_options.append("Admin")

if page_param in {"enviar", "enviar-dados", "submit"}:
    default_page = "Enviar dados"
elif page_param == "admin" and "Admin" in page_options:
    default_page = "Admin"
else:
    default_page = "Dashboard"

current_page = st.sidebar.radio(
    "Página",
    page_options,
    index=page_options.index(default_page),
)

render_navbar()

if current_page == "Enviar dados":
    render_public_submission_page()
    render_footer()
    st.stop()

if current_page == "Admin":
    render_admin_page()
    render_footer()
    st.stop()

with st.spinner("Carregando ranking..."):
    df = get_data(get_data_source_fingerprint())
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
