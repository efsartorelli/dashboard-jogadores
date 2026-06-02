from html import escape
from datetime import date
import os
import time
from urllib.parse import urlencode

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

import src.config as app_config
from src.auth import AuthError, AuthSession, get_auth_client
from src.database.connection import DatabaseUnavailable, has_database_config
from src.metrics.averages import build_average_ranking as compute_average_ranking
from src.metrics.distribution import build_distribution as compute_distribution
from src.metrics.formatting import format_compact, format_int
from src.metrics.medals import CAPTURE_MEDAL_COUNT, calculate_medal_progress
from src.metrics.rankings import build_general_ranking as compute_general_ranking
from src.metrics.rankings import get_best_catches as compute_best_catches
from src.metrics.states import build_state_stats as compute_state_stats
from src.services.data_source import get_data_source_fingerprint, load_dashboard_data
from src.services.admin_review import (
    approve_record,
    list_curation_records,
    list_pending_records,
    reject_record,
    update_pending_record,
)
from src.services.monthly_imports import (
    analyze_monthly_import,
    confirm_monthly_import,
    list_monthly_imports,
    undo_monthly_import,
)
from src.services.payments import create_upgrade_checkout
from src.services.submissions import submit_player_record
from src.services.users import (
    ensure_profile,
    get_public_profile_index,
    get_profile_overview,
    get_user_entitlement,
    update_user_profile,
    user_can_moderate,
    profile_has_location,
)
from src.validation.submissions import BRAZILIAN_STATES
from src.validation.profiles import COUNTRIES, normalize_nickname_match_key, validate_profile_fields


PRODUCTION_APP_URL_FALLBACK = "https://dashboard-jogadores-yhkbgujmiz4nkfgsh3xnvq.streamlit.app"


class FallbackSettingsValidation:
    def __init__(self, missing):
        self.missing = tuple(missing)

    @property
    def ok(self):
        return not self.missing

    def message(self):
        if self.ok:
            return "Configuracao obrigatoria presente."
        return "Variaveis obrigatorias ausentes: " + ", ".join(self.missing)


def fallback_get_setting(key, default=None):
    try:
        secrets = dict(st.secrets)
        value = str(secrets.get(key, "")).strip()
        if value:
            return value
    except Exception:
        pass
    value = str(os.getenv(key, "")).strip()
    return value or default


def fallback_validate_required_settings(keys):
    return FallbackSettingsValidation([key for key in keys if not get_setting(key)])


def config_bool(name, default=False):
    value = getattr(app_config, name, None)
    if value is None:
        raw = get_setting(name, str(default).lower())
        return str(raw or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


get_setting = getattr(app_config, "get_setting", fallback_get_setting)
validate_required_settings = getattr(app_config, "validate_required_settings", fallback_validate_required_settings)
AUTH_SESSION_VALIDATE_INTERVAL_SECONDS = int(getattr(app_config, "AUTH_SESSION_VALIDATE_INTERVAL_SECONDS", 300) or 300)
DATA_SOURCE = str(getattr(app_config, "DATA_SOURCE", "auto") or "auto").strip().lower()
SUPABASE_AUTH_REDIRECT_URL = str(
    getattr(app_config, "SUPABASE_AUTH_REDIRECT_URL", PRODUCTION_APP_URL_FALLBACK)
    or PRODUCTION_APP_URL_FALLBACK
).rstrip("/")
ENABLE_PREMIUM = config_bool("ENABLE_PREMIUM", False)


st.set_page_config(
    page_title="Ranking BR - Pokémon GO Brasil",
    page_icon="🇧🇷",
    layout="wide",
    initial_sidebar_state="collapsed",
)


MAX_CATCHES_INPUT = 9_999_999_999
PAGINATION_DEBOUNCE_SECONDS = 0.35


@st.cache_data(show_spinner=False, ttl=300)
def get_data(_fingerprint):
    return load_dashboard_data().data


@st.cache_data(show_spinner=False, ttl=60)
def get_data_fingerprint_cached():
    return get_data_source_fingerprint()


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
def build_state_stats(base, order_by="Total capturas", ranking_base=None):
    return compute_state_stats(base, order_by, ranking_base)


@st.cache_data(show_spinner=False)
def build_distribution(base):
    return compute_distribution(base)


@st.cache_data(show_spinner=False, ttl=30)
def get_curation_queue(admin_user_id, status, search, order_by, order_direction, page, page_size):
    return list_curation_records(
        admin_user_id=admin_user_id,
        status=status,
        search=search,
        order_by=order_by,
        order_direction=order_direction,
        page=page,
        page_size=page_size,
    )


@st.cache_resource(show_spinner=False)
def get_cached_auth_client():
    return get_auth_client()


@st.cache_data(show_spinner=False, ttl=60)
def get_profile_overview_cached(user_id, profile_updated_at=None):
    return get_profile_overview(user_id)


@st.cache_data(show_spinner=False, ttl=300)
def get_public_profile_index_cached():
    return get_public_profile_index()


def ui_html(markup):
    st.html(markup)


SCROLL_TO_TOP_PENDING_KEY = "scroll_to_top_pending"
LAST_RENDERED_PAGE_KEY = "last_rendered_page"


def request_scroll_to_top() -> None:
    st.session_state[SCROLL_TO_TOP_PENDING_KEY] = True


def scroll_to_top_once() -> None:
    if not st.session_state.pop(SCROLL_TO_TOP_PENDING_KEY, False):
        return

    components.html(
        """
        <script>
        const scrollToTop = () => {
          try {
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            parentWindow.scrollTo({ top: 0, left: 0, behavior: "auto" });
            parentDocument.documentElement.scrollTop = 0;
            parentDocument.body.scrollTop = 0;
            [
              '[data-testid="stAppViewContainer"]',
              '[data-testid="stMain"]',
              '.main'
            ].forEach((selector) => {
              const element = parentDocument.querySelector(selector);
              if (element) {
                element.scrollTop = 0;
              }
            });
          } catch (error) {}
        };
        scrollToTop();
        setTimeout(scrollToTop, 50);
        setTimeout(scrollToTop, 220);
        </script>
        """,
        height=0,
        width=0,
    )


def clear_dashboard_caches():
    get_data_fingerprint_cached.clear()
    get_data.clear()
    get_best_catches.clear()
    build_general_ranking.clear()
    build_average_ranking.clear()
    build_state_stats.clear()
    build_distribution.clear()


def clear_curation_caches():
    get_curation_queue.clear()


def clear_profile_caches():
    get_profile_overview_cached.clear()
    get_public_profile_index_cached.clear()


def render_feedback(result, success_message, info_message=None):
    if not result:
        return
    if result.get("success"):
        st.success(success_message)
        if info_message:
            st.info(info_message)
        return
    st.error("; ".join(result.get("errors", ["Não foi possível concluir a ação."])))


AUTH_SESSION_STATE_KEY = "supabase_auth_session"
AUTH_VALIDATED_AT_STATE_KEY = "supabase_auth_validated_at"
RESET_PASSWORD_PAGE = "reset-password"


def get_session_from_state() -> AuthSession | None:
    return AuthSession.from_dict(st.session_state.get(AUTH_SESSION_STATE_KEY))


def store_auth_session(session: AuthSession) -> None:
    st.session_state[AUTH_SESSION_STATE_KEY] = session.to_dict()
    st.session_state[AUTH_VALIDATED_AT_STATE_KEY] = int(time.time())


def clear_auth_session() -> None:
    for key in [
        AUTH_SESSION_STATE_KEY,
        AUTH_VALIDATED_AT_STATE_KEY,
        "current_profile",
        "profile_overview",
        "auth_feedback",
        "auth_attempts",
    ]:
        st.session_state.pop(key, None)


def logout_current_user() -> None:
    session = get_session_from_state()
    if session:
        try:
            get_cached_auth_client().sign_out(session.access_token)
        except AuthError:
            pass
    clear_auth_session()
    st.rerun()


def auth_attempt_allowed() -> bool:
    now = int(time.time())
    attempts = [stamp for stamp in st.session_state.get("auth_attempts", []) if now - stamp < 600]
    st.session_state.auth_attempts = attempts
    return len(attempts) < 8


def record_auth_attempt() -> None:
    attempts = list(st.session_state.get("auth_attempts", []))
    attempts.append(int(time.time()))
    st.session_state.auth_attempts = attempts[-12:]


def build_auth_redirect_url(page: str | None = None) -> str:
    base_url = SUPABASE_AUTH_REDIRECT_URL.rstrip("/")
    if not page:
        return base_url
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'page': page})}"


def friendly_auth_error(exc: Exception | str) -> str:
    message = str(exc or "").casefold()
    if any(term in message for term in ("invalid login", "invalid credentials", "email not found", "invalid_grant")):
        return "Email ou senha incorretos. Verifique os dados e tente novamente."
    if any(term in message for term in ("email not confirmed", "email_confirmed", "confirm")):
        return "Seu email ainda nao foi confirmado. Verifique sua caixa de entrada."
    if any(term in message for term in ("rate limit", "too many", "muitas tentativas")):
        return "Muitas tentativas de login. Aguarde alguns minutos e tente novamente."
    if any(term in message for term in ("conectar", "connection", "timeout", "network")):
        return "Nao foi possivel conectar ao servidor. Tente novamente em instantes."
    if any(term in message for term in ("already registered", "user already", "already exists")):
        return "Ja existe uma conta com este email. Tente entrar ou recupere sua senha."
    return "Nao foi possivel concluir esta acao agora. Tente novamente."


def get_reset_access_token_from_query() -> str:
    token = st.query_params.get("access_token", "")
    if isinstance(token, list):
        token = token[0] if token else ""
    return str(token or "").strip()


def inject_recovery_hash_bridge() -> None:
    components.html(
        """
        <script>
        const hash = window.location.hash ? window.location.hash.substring(1) : "";
        if (hash) {
            const hashParams = new URLSearchParams(hash);
            const type = hashParams.get("type");
            const accessToken = hashParams.get("access_token");
            if (accessToken && (!type || type === "recovery")) {
                const url = new URL(window.location.href);
                url.hash = "";
                url.searchParams.set("page", "reset-password");
                for (const key of ["access_token", "refresh_token", "expires_at", "expires_in", "token_type", "type"]) {
                    const value = hashParams.get(key);
                    if (value) {
                        url.searchParams.set(key, value);
                    }
                }
                window.location.replace(url.toString());
            }
        }
        </script>
        """,
        height=0,
    )


def render_reset_password_page():
    inject_recovery_hash_bridge()

    ui_html("""
        <section class="auth-page section-anchor">
            <div class="auth-brand">
                <div class="brand-orb auth-brand-orb">BR</div>
                <div class="auth-brand-text">
                    <div class="auth-title">Redefinir senha</div>
                    <div class="auth-subtitle">Digite sua nova senha abaixo para recuperar o acesso a sua conta.</div>
                </div>
            </div>
        </section>
    """)

    client = get_cached_auth_client()
    auth_config = validate_required_settings(["SUPABASE_URL", "SUPABASE_ANON_KEY"])
    if not client.is_configured or not auth_config.ok:
        st.error("Supabase Auth nao configurado. Defina SUPABASE_URL e SUPABASE_ANON_KEY nos secrets do ambiente.")
        return

    access_token = get_reset_access_token_from_query()
    if not access_token:
        st.info("Validando link de recuperacao. Se esta mensagem continuar, abra novamente o link recebido por email.")
        return

    with st.container(key="auth_reset_shell"):
        with st.form("reset_password_form"):
            password = st.text_input("Nova senha", type="password", key="reset_password")
            confirm = st.text_input("Confirmar nova senha", type="password", key="reset_confirm")
            submitted = st.form_submit_button("Salvar nova senha", type="primary")

        if submitted:
            if len(password) < 8:
                st.error("Use uma senha com pelo menos 8 caracteres.")
                return
            if password != confirm:
                st.error("As senhas nao conferem.")
                return
            try:
                client.update_password(access_token, password)
                clear_auth_session()
                st.session_state.auth_feedback = (
                    "success",
                    "Senha alterada com sucesso. Voce ja pode fazer login novamente.",
                )
                st.query_params.clear()
                st.query_params["page"] = "login"
                st.rerun()
            except AuthError:
                st.error("Nao foi possivel alterar a senha. Abra novamente o link de recuperacao ou solicite um novo email.")


def render_auth_page():
    ui_html("""
        <section class="auth-page section-anchor">
            <div class="auth-brand">
                <div class="brand-orb auth-brand-orb">BR</div>
                <div class="auth-brand-text">
                    <div class="auth-title">PokéGO Brasil</div>
                    <div class="auth-subtitle">Ranking nacional competitivo de Pokémon GO</div>
                </div>
            </div>
        </section>
    """)

    client = get_cached_auth_client()
    auth_config = validate_required_settings(["SUPABASE_URL", "SUPABASE_ANON_KEY"])
    if not client.is_configured or not auth_config.ok:
        st.error("Supabase Auth nao configurado. Defina SUPABASE_URL e SUPABASE_ANON_KEY nos secrets do ambiente.")
        return

    # Supabase envia emails de confirmacao/recuperacao. O SMTP profissional
    # deve ser configurado no painel do Supabase, nao em codigo Streamlit.
    email_redirect_to = build_auth_redirect_url()
    recovery_redirect_to = build_auth_redirect_url(RESET_PASSWORD_PAGE)

    feedback = st.session_state.pop("auth_feedback", None)
    if feedback:
        level, message = feedback
        getattr(st, level)(message)

    with st.container(key="auth_card_shell"):
        login_tab, signup_tab, recover_tab = st.tabs(["Entrar", "Criar conta", "Recuperar senha"])

        with login_tab:
            with st.container(key="auth_login_shell"):
                st.caption("Acesse sua conta para abrir o dashboard.")
                with st.form("login_form"):
                    email = st.text_input("Email", key="login_email").strip().lower()
                    password = st.text_input("Senha", type="password", key="login_password")
                    submitted = st.form_submit_button("Entrar", type="primary")
                st.caption("Novo por aqui ou esqueceu a senha? Use as abas acima.")

                if submitted:
                    if not auth_attempt_allowed():
                        st.error("Muitas tentativas de login. Aguarde alguns minutos.")
                        return
                    record_auth_attempt()
                    try:
                        session = client.sign_in(email, password)
                        store_auth_session(session)
                        st.rerun()
                    except AuthError as exc:
                        st.error(friendly_auth_error(exc))

        with signup_tab:
            with st.container(key="auth_signup_shell"):
                st.caption("Crie seu acesso com os dados usados no ranking.")
                with st.form("signup_form"):
                    nickname = st.text_input("Nickname", max_chars=40, key="signup_nickname")
                    email = st.text_input("Email", key="signup_email").strip().lower()
                    pais = st.selectbox("Pais", COUNTRIES, index=0, key="signup_country")
                    estado = st.selectbox("Estado (UF)", BRAZILIAN_STATES, index=BRAZILIAN_STATES.index("SP"), key="signup_state")
                    cidade = st.text_input("Cidade", max_chars=80, key="signup_city")
                    password = st.text_input("Senha", type="password", key="signup_password")
                    confirm = st.text_input("Confirmar senha", type="password", key="signup_confirm")
                    accepted = st.checkbox("Li e aceito os termos de uso da plataforma.", key="signup_terms")
                    submitted = st.form_submit_button("Criar conta", type="primary")
                st.caption("Os dados enviados podem passar por revisao antes de entrar no ranking principal.")

                if submitted:
                    normalized_profile, profile_errors = validate_profile_fields(nickname, pais, estado, cidade)
                    if profile_errors:
                        st.error("; ".join(profile_errors))
                        return
                    if len(password) < 8:
                        st.error("Use uma senha com pelo menos 8 caracteres.")
                        return
                    if password != confirm:
                        st.error("As senhas nao conferem.")
                        return
                    if not accepted:
                        st.error("Aceite os termos para criar a conta.")
                        return
                    try:
                        session = client.sign_up(
                            email,
                            password,
                            name=normalized_profile["nickname"],
                            nickname=normalized_profile["nickname"],
                            pais=normalized_profile["pais"],
                            estado=normalized_profile["estado"],
                            cidade=normalized_profile["cidade"],
                            redirect_to=email_redirect_to,
                        )
                        if session:
                            store_auth_session(session)
                            st.rerun()
                        st.success("Conta criada. Verifique seu email para validar o acesso.")
                    except AuthError as exc:
                        st.error(friendly_auth_error(exc))

        with recover_tab:
            with st.container(key="auth_recover_shell"):
                st.caption("Informe seu email para receber as instrucoes de acesso.")
                with st.form("recover_form"):
                    email = st.text_input("Email da conta", key="recover_email").strip().lower()
                    submitted = st.form_submit_button("Enviar recuperacao", type="primary")
                st.caption("Se houver uma conta vinculada a este email, voce recebera instrucoes para redefinir a senha.")
                if submitted:
                    try:
                        client.recover_password(email, redirect_to=recovery_redirect_to)
                        st.success("Se o email existir, enviaremos o link de recuperacao.")
                    except AuthError as exc:
                        st.error(friendly_auth_error(exc))


def require_authenticated_user() -> tuple[AuthSession, dict]:
    client = get_cached_auth_client()
    session = get_session_from_state()
    if not session:
        render_auth_page()
        st.stop()

    try:
        should_sync_profile = False
        if session.should_refresh:
            session = client.refresh(session.refresh_token)
            store_auth_session(session)
            should_sync_profile = True

        last_validated = int(st.session_state.get(AUTH_VALIDATED_AT_STATE_KEY, 0) or 0)
        if int(time.time()) - last_validated >= AUTH_SESSION_VALIDATE_INTERVAL_SECONDS:
            user = client.get_user(session.access_token)
            session = session.with_user(user)
            store_auth_session(session)
            should_sync_profile = True

        cached_profile = st.session_state.get("current_profile")
        if (
            not should_sync_profile
            and cached_profile
            and str(cached_profile.get("id")) == str(session.user.get("id"))
        ):
            return session, cached_profile

        profile = ensure_profile(session.user)
        st.session_state.current_profile = profile
        return session, profile
    except AuthError as exc:
        clear_auth_session()
        st.error("Sua sessao expirou. Entre novamente para continuar.")
        render_auth_page()
        st.stop()
    except (DatabaseUnavailable, Exception) as exc:
        st.error(f"Nao foi possivel validar o perfil agora: {exc}")
        st.stop()


def render_public_submission_page(profile):
    ui_html("""
        <section class="page-hero submission-hero">
            <div class="eyebrow">Curadoria manual</div>
            <h1 class="page-title">Enviar dados</h1>
            <p class="page-copy">
                Registros enviados entram como pendentes e so aparecem no ranking
                depois da revisao administrativa.
            </p>
        </section>
    """)

    if DATA_SOURCE != "database":
        st.warning("Envio indisponivel no modo Excel. Ative DATA_SOURCE=database para usar este formulario.")
        return
    if not has_database_config():
        st.warning("Envio indisponivel: banco de dados nao configurado.")
        return

    try:
        entitlement = get_user_entitlement(profile)
    except Exception:
        st.error("Nao foi possivel carregar seu limite mensal. Verifique a migration SaaS no Supabase.")
        return

    st.caption(
        f"Inputs restantes neste mes: {entitlement.remaining_this_month} de {entitlement.monthly_limit}."
    )

    render_feedback(
        st.session_state.pop("user_submission_result", None),
        "Registro enviado para revisao.",
        "O envio ficou como pendente. Depois da aprovacao, ele entra no dashboard.",
    )

    if not entitlement.can_submit:
        st.warning("Voce atingiu o limite mensal do plano atual. A pagina Premium mostra as opcoes de upgrade.")
        return

    has_location = profile_has_location(profile)
    profile_nickname = str(profile.get("nickname") or "").strip()
    if not has_location:
        st.info("Complete país, estado e cidade neste primeiro envio. Depois disso, a localidade fica salva no Perfil.")
    if not profile_nickname:
        st.info("Complete seu nickname para vincular os envios ao seu perfil.")

    with st.container(key="public_submission_shell"):
        with st.form("public_submission_form", clear_on_submit=True):
            left, right = st.columns([0.58, 0.42], vertical_alignment="top")
            with left:
                if profile_nickname:
                    st.text_input("Nickname", value=profile_nickname, disabled=True)
                    nickname = profile_nickname
                else:
                    nickname = st.text_input("Nickname", max_chars=40, placeholder="Seu nickname no jogo")
                data_referencia = st.date_input("Data do registro", value=date.today(), max_value=date.today())
                catches = st.number_input(
                    "Total de capturas",
                    min_value=1,
                    max_value=MAX_CATCHES_INPUT,
                    step=1,
                    format="%d",
                )
            with right:
                if has_location:
                    pais = str(profile.get("pais") or "")
                    state = str(profile.get("estado") or "")
                    cidade = str(profile.get("cidade") or "")
                    st.text_input("Localidade", value=f"{cidade} · {state} · {pais}", disabled=True)
                else:
                    pais = st.selectbox("País", COUNTRIES, index=0, key="submission_country")
                    state = st.selectbox("Estado (UF)", BRAZILIAN_STATES, index=BRAZILIAN_STATES.index("SP"))
                    cidade = st.text_input("Cidade", max_chars=80, key="submission_city")
                contato = st.text_input(
                    "Contato opcional",
                    max_chars=120,
                    value=str(profile.get("email") or ""),
                    placeholder="Email, WhatsApp ou @",
                )
                observacao = st.text_area("Observação opcional", max_chars=500, height=126)
            submitted = st.form_submit_button("Enviar para revisao", type="primary")

    if submitted:
        normalized_profile, profile_errors = validate_profile_fields(nickname, pais, state, cidade)
        if profile_errors:
            st.session_state.user_submission_result = {"success": False, "errors": profile_errors}
            st.rerun()

        if not has_location or not profile_nickname:
            try:
                updated_profile = update_user_profile(
                    profile.get("id"),
                    profile.get("nome") or normalized_profile["nickname"],
                    normalized_profile["nickname"],
                    normalized_profile["pais"],
                    normalized_profile["estado"],
                    normalized_profile["cidade"],
                )
                if updated_profile:
                    st.session_state.current_profile = updated_profile
                    clear_profile_caches()
                    profile = updated_profile
            except Exception as exc:
                st.session_state.user_submission_result = {"success": False, "errors": [str(exc)]}
                st.rerun()

        result = submit_player_record({
            "nickname": normalized_profile["nickname"],
            "state": normalized_profile["estado"],
            "pais": normalized_profile["pais"],
            "cidade": normalized_profile["cidade"],
            "data_referencia": data_referencia,
            "catches": int(catches),
            "periodo_tipo": "mensal",
            "status": "pendente",
            "fonte": "site",
            "observacao": observacao,
            "contato_envio": contato,
            "created_by": profile.get("id"),
        }, require_authenticated=True, enforce_monthly_limit=True, enforce_rate_limit=True)
        clear_profile_caches()
        st.session_state.user_submission_result = result
        st.rerun()


def render_admin_page(profile):
    if not user_can_moderate(profile):
        st.error("Acesso restrito a moderadores.")
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
        st.warning("Admin indisponivel: banco nao configurado.")
        return

    with st.container(key="admin_session_bar"):
        st.caption(f"Curadoria ativa para {profile.get('email', 'moderador')}.")

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
                    "created_by": profile.get("id"),
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
                    admin_user_id=profile.get("id"),
                )
                result = update_result
                if update_result.get("success") and action == "Aprovar":
                    result = approve_record(record_id, admin_note=admin_note, admin_user_id=profile.get("id"))
                elif update_result.get("success") and action in {"Rejeitar", "Excluir logicamente"}:
                    note = admin_note
                    if action == "Excluir logicamente":
                        note = f"{admin_note}\nExclusão lógica solicitada pelo admin.".strip()
                    result = reject_record(record_id, admin_note=note, admin_user_id=profile.get("id"))

                if result.get("success"):
                    clear_dashboard_caches()
                st.session_state.admin_last_result = result
                st.rerun()


def trainer_avatar(name, place):
    # SVG inline rendered inside .podium-avatar; CSS also adds an embedded SVG fallback span for Streamlit-safe visibility.
    return f"""
        <svg
            class="trainer-avatar-svg"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            style="display:block; width:42px; height:42px; stroke:#f4c95d; fill:none; overflow:visible;"
            role="img"
            aria-label="Avatar de treinador"
            fill="none"
            stroke="#f4c95d"
            stroke-width="2.3"
            stroke-linecap="round"
            stroke-linejoin="round"
        >
            <circle cx="12" cy="8" r="4.2" />
            <path d="M4.5 21c1.15-5.15 4.05-7.75 7.5-7.75S18.35 15.85 19.5 21" />
            <path d="M8.4 19.1h7.2" />
        </svg>
    """


def inject_css():
    palette = {
        "bg": "#0c1117",
        "bg2": "#111a21",
        "card": "rgba(19, 27, 36, 0.86)",
        "card2": "rgba(25, 38, 47, 0.72)",
        "card3": "rgba(9, 14, 20, 0.66)",
        "border": "rgba(125, 220, 205, 0.24)",
        "border2": "rgba(226, 184, 79, 0.28)",
        "line": "rgba(177, 207, 219, 0.12)",
        "text": "#eef6f8",
        "muted": "#a9bdc7",
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
        color-scheme: dark;
    }}

    [data-testid="stAppViewContainer"],
    [data-testid="stHeader"],
    [data-testid="stToolbar"],
    [data-testid="stSidebar"],
    [data-testid="stSidebarContent"] {{
        color: var(--rb-text) !important;
        background-color: transparent !important;
    }}

    [data-testid="stSidebar"] {{
        background:
            linear-gradient(180deg, rgba(13,20,27,0.96), rgba(7,16,22,0.98)) !important;
        border-right: 1px solid var(--rb-line);
    }}

    .block-container {{
        max-width: 1480px;
        padding: 4.75rem 1.55rem 4rem !important;
    }}

    section.main > div {{
        padding-top: 0 !important;
    }}

    .section-anchor {{
        scroll-margin-top: 7rem;
    }}

    .st-key-navbar {{
        position: sticky;
        top: 3.35rem;
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
        z-index: 5;
        color: var(--rb-gold);
        width: 54px;
        height: 54px;
        margin-bottom: 1rem;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 20px;
        border: 1px solid rgba(226,184,79,0.28);
        background:
            radial-gradient(circle at 38% 24%, rgba(255,255,255,0.16), transparent 32%),
            linear-gradient(145deg, rgba(226,184,79,0.15), rgba(76,201,176,0.07));
        box-shadow:
            0 14px 34px rgba(226,184,79,0.13),
            0 0 28px rgba(76,201,176,0.08),
            inset 0 1px 0 rgba(255,255,255,0.12);
        transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease, color 180ms ease;
    }}

    .stat-icon svg {{
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
        position: relative;
        z-index: 10;
        width: 34px;
        height: 34px;
        overflow: visible !important;
        stroke: #f4c95d !important;
        fill: none !important;
    }}

    .stat-icon-fallback,
    .podium-avatar-fallback {{
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
        position: absolute;
        z-index: 9;
        pointer-events: none;
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
    }}

    .stat-icon-fallback {{
        width: 32px;
        height: 32px;
    }}

    .stat-icon-users-fallback {{
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f4c95d' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M16 21v-1.6a4.4 4.4 0 0 0-4.4-4.4H7.4A4.4 4.4 0 0 0 3 19.4V21'/%3E%3Ccircle cx='9.5' cy='7.4' r='3.7'/%3E%3Cpath d='M21 21v-1.4a3.8 3.8 0 0 0-3.1-3.7'/%3E%3Cpath d='M16.2 4.1a3.55 3.55 0 0 1 0 6.8'/%3E%3Cpath d='M4.8 19.5h9.4'/%3E%3C/svg%3E");
    }}

    .stat-icon-chart-fallback {{
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f4c95d' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M4 19V5'/%3E%3Cpath d='M4 19h16'/%3E%3Cpath d='M8 15v-4'/%3E%3Cpath d='M12 15V8'/%3E%3Cpath d='M16 15v-6'/%3E%3Cpath d='M7.2 7.7 10 5l3 2 4-4'/%3E%3Cpath d='M16.7 3H20v3.3'/%3E%3C/svg%3E");
    }}

    .stat-icon-map-fallback {{
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f4c95d' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 21s6-5.4 6-11a6 6 0 0 0-12 0c0 5.6 6 11 6 11z'/%3E%3Ccircle cx='12' cy='10' r='2.35'/%3E%3Cpath d='M4.5 20.2c1.5-1 3.2-1.5 5.1-1.5'/%3E%3Cpath d='M14.4 18.7c1.9 0 3.6.5 5.1 1.5'/%3E%3C/svg%3E");
    }}

    .stat-card:hover .stat-icon {{
        transform: translateY(-2px) scale(1.035);
        color: #f0ce6b;
        border-color: rgba(226,184,79,0.48);
        box-shadow:
            0 18px 44px rgba(226,184,79,0.18),
            0 0 36px rgba(76,201,176,0.13),
            inset 0 1px 0 rgba(255,255,255,0.16);
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
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        border: 3px solid rgba(226,184,79,0.68);
        background:
            radial-gradient(circle at 42% 18%, rgba(255,255,255,0.26), transparent 28%),
            linear-gradient(145deg, rgba(143,167,255,0.30), rgba(226,184,79,0.22) 48%, rgba(76,201,176,0.18));
        box-shadow:
            0 16px 42px rgba(0,0,0,0.34),
            0 0 26px rgba(226,184,79,0.16),
            inset 0 1px 0 rgba(255,255,255,0.18);
        overflow: hidden;
        position: relative;
        z-index: 5;
    }}

    .podium-avatar svg {{
        display: block !important;
        visibility: visible !important;
        opacity: 1 !important;
        position: relative;
        z-index: 10;
        width: 44px;
        height: 44px;
        overflow: visible !important;
        stroke: #f4c95d !important;
        fill: none !important;
    }}

    .podium-avatar-fallback {{
        width: 42px;
        height: 42px;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23f4c95d' stroke-width='2.3' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='8' r='4.2'/%3E%3Cpath d='M4.5 21c1.15-5.15 4.05-7.75 7.5-7.75S18.35 15.85 19.5 21'/%3E%3Cpath d='M8.4 19.1h7.2'/%3E%3C/svg%3E");
    }}

    .champion .podium-avatar {{
        width: 110px;
        height: 110px;
        margin-top: 1.38rem;
        border-color: rgba(226,184,79,0.86);
        box-shadow: 0 20px 54px rgba(0,0,0,0.38), 0 0 34px rgba(226,184,79,0.23), inset 0 1px 0 rgba(255,255,255,0.2);
    }}

    .champion .podium-avatar svg {{
        width: 48px;
        height: 48px;
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
        border: 1px solid rgba(244,201,93,0.38);
        border-radius: 999px;
        color: #f6f1d5;
        background: rgba(244,201,93,0.10);
        font-size: 0.76rem;
        font-weight: 760;
    }}

    .js-plotly-plot .hoverlayer .hovertext path,
    .js-plotly-plot .hoverlayer .hovertext rect {{
        fill: #10140f !important;
        stroke: #f4c95d !important;
    }}

    .js-plotly-plot .hoverlayer .hovertext text,
    .js-plotly-plot .hoverlayer .hovertext tspan {{
        fill: #f6f1d5 !important;
    }}

    .rb-table-wrap {{
        overflow-x: auto;
        border: 1px solid var(--rb-border);
        border-radius: 18px;
        background: rgba(8,8,6,0.16);
    }}

    .mobile-ranking-cards {{
        display: none;
    }}

    .mobile-ranking-rank {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 40px;
        height: 40px;
        padding: 0 0.5rem;
        border-radius: 999px;
        color: var(--rb-gold);
        border: 1px solid rgba(226,184,79,0.26);
        background: rgba(226,184,79,0.11);
        font-size: 0.95rem;
        font-weight: 950;
        line-height: 1;
    }}

    .mobile-ranking-body {{
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 0.38rem;
    }}

    .player-card-header,
    .mobile-ranking-heading {{
        min-width: 0;
        display: flex;
        align-items: center;
        gap: 0.28rem;
        flex-wrap: wrap;
    }}

    .mobile-ranking-player,
    .mobile-ranking-player:visited {{
        width: fit-content;
        max-width: 100%;
        color: var(--rb-text);
        font-size: 1.08rem;
        font-weight: 930;
        line-height: 1.16;
        text-decoration: none;
        overflow-wrap: anywhere;
    }}

    .mobile-ranking-player.available {{
        color: #f6f1d5;
        border-bottom: 1px solid rgba(244,201,93,0.42);
        text-shadow: 0 0 14px rgba(244,201,93,0.12);
    }}

    .mobile-ranking-player.available:hover {{
        color: var(--rb-gold);
    }}

    [class*="st-key-ranking_general_mobile_card_header_"] [data-testid="stHorizontalBlock"],
    [class*="st-key-ranking_average_mobile_card_header_"] [data-testid="stHorizontalBlock"],
    [class*="st-key-ranking-general-mobile-card-header-"] [data-testid="stHorizontalBlock"],
    [class*="st-key-ranking-average-mobile-card-header-"] [data-testid="stHorizontalBlock"] {{
        align-items: center;
        justify-content: flex-start;
        gap: 0.28rem;
        flex-wrap: wrap;
    }}

    [class*="st-key-ranking_general_mobile_card_header_"] [data-testid="stMarkdownContainer"],
    [class*="st-key-ranking_average_mobile_card_header_"] [data-testid="stMarkdownContainer"],
    [class*="st-key-ranking-general-mobile-card-header-"] [data-testid="stMarkdownContainer"],
    [class*="st-key-ranking-average-mobile-card-header-"] [data-testid="stMarkdownContainer"] {{
        min-width: 0;
    }}

    [class*="st-key-ranking_general_mobile_player_link_"] .stButton,
    [class*="st-key-ranking_average_mobile_player_link_"] .stButton,
    [class*="st-key-ranking-general-mobile-player-link-"] .stButton,
    [class*="st-key-ranking-average-mobile-player-link-"] .stButton {{
        margin: 0;
    }}

    [class*="st-key-ranking_general_mobile_player_link_"] .stButton > button,
    [class*="st-key-ranking_average_mobile_player_link_"] .stButton > button,
    [class*="st-key-ranking-general-mobile-player-link-"] .stButton > button,
    [class*="st-key-ranking-average-mobile-player-link-"] .stButton > button {{
        width: fit-content !important;
        max-width: 100%;
        min-height: 0;
        padding: 0 0 0.08rem !important;
        border: 0 !important;
        border-bottom: 1px solid rgba(244,201,93,0.42) !important;
        border-radius: 0 !important;
        color: #f6f1d5 !important;
        background: transparent !important;
        box-shadow: none !important;
        font-size: 1.08rem;
        font-weight: 930;
        line-height: 1.16;
        text-align: left !important;
        white-space: normal !important;
        overflow-wrap: anywhere !important;
        justify-content: flex-start;
        text-shadow: 0 0 14px rgba(244,201,93,0.12);
    }}

    [class*="st-key-ranking_general_mobile_player_link_"] .stButton > button p,
    [class*="st-key-ranking_average_mobile_player_link_"] .stButton > button p,
    [class*="st-key-ranking-general-mobile-player-link-"] .stButton > button p,
    [class*="st-key-ranking-average-mobile-player-link-"] .stButton > button p {{
        color: inherit !important;
        font-size: inherit !important;
        font-weight: inherit !important;
        line-height: inherit !important;
        text-align: inherit !important;
        white-space: inherit !important;
        overflow-wrap: inherit !important;
    }}

    [class*="st-key-ranking_general_mobile_player_link_"] .stButton > button:hover,
    [class*="st-key-ranking_average_mobile_player_link_"] .stButton > button:hover,
    [class*="st-key-ranking-general-mobile-player-link-"] .stButton > button:hover,
    [class*="st-key-ranking-average-mobile-player-link-"] .stButton > button:hover {{
        color: var(--rb-gold) !important;
        border-bottom-color: rgba(127,163,90,0.62) !important;
        text-shadow: 0 0 16px rgba(244,201,93,0.16);
    }}

    .mobile-ranking-state {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        max-width: 100%;
        min-height: 24px;
        padding: 0.22rem 0.48rem;
        border: 1px solid rgba(127,163,90,0.22);
        border-radius: 999px;
        color: var(--rb-green);
        background: rgba(127,163,90,0.11);
        font-size: 0.68rem;
        font-weight: 920;
        line-height: 1;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        overflow-wrap: anywhere;
    }}

    .mobile-ranking-meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.42rem;
        align-items: center;
        color: var(--rb-muted);
        font-size: 0.76rem;
        font-weight: 850;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }}

    .mobile-ranking-metric {{
        color: var(--rb-gold);
        font-size: 1.18rem;
        font-weight: 950;
        line-height: 1.05;
        overflow-wrap: anywhere;
    }}

    .mobile-ranking-sub {{
        color: rgba(240,218,159,0.74);
        font-size: 0.82rem;
        font-weight: 760;
        line-height: 1.35;
    }}

    .mobile-ranking-extra {{
        color: rgba(220,231,231,0.66);
        font-size: 0.74rem;
        line-height: 1.35;
        overflow-wrap: anywhere;
    }}

    [class*="st-key-ranking_general_mobile_card_item_"],
    [class*="st-key-ranking_average_mobile_card_item_"],
    [class*="st-key-ranking-general-mobile-card-item-"],
    [class*="st-key-ranking-average-mobile-card-item-"] {{
        display: none;
    }}

    .desktop-ranking-wrap {{
        width: 100%;
        overflow: hidden;
        margin-top: 0.82rem;
        border: 1px solid rgba(240,218,159,0.16);
        border-radius: 20px;
        background:
            radial-gradient(circle at 0% 0%, rgba(226,184,79,0.08), transparent 17rem),
            radial-gradient(circle at 100% 0%, rgba(76,201,176,0.045), transparent 18rem),
            linear-gradient(180deg, rgba(18,20,15,0.82), rgba(7,10,8,0.58));
        box-shadow:
            0 16px 44px rgba(0,0,0,0.18),
            inset 0 1px 0 rgba(255,255,255,0.045);
    }}

    .desktop-ranking-table {{
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        color: var(--rb-text);
        table-layout: fixed;
        font-variant-numeric: tabular-nums;
    }}

    .desktop-ranking-table col.rank-col {{
        width: 9%;
    }}

    .desktop-ranking-table col.player-col {{
        width: 34%;
    }}

    .desktop-ranking-table col.state-col {{
        width: 17%;
    }}

    .desktop-ranking-table col.metric-col {{
        width: 22%;
    }}

    .desktop-ranking-table col.days-col {{
        width: 18%;
    }}

    .desktop-ranking-table col.avg-player-col {{
        width: 30%;
    }}

    .desktop-ranking-table col.avg-state-col {{
        width: 15%;
    }}

    .desktop-ranking-table col.avg-metric-col {{
        width: 14%;
    }}

    .desktop-ranking-table col.period-col {{
        width: 26%;
    }}

    .desktop-ranking-table col.avg-days-col {{
        width: 15%;
    }}

    .desktop-ranking-table th {{
        padding: 0.98rem 0.75rem;
        color: rgba(220,231,231,0.76);
        text-align: center;
        font-size: 0.66rem;
        font-weight: 940;
        letter-spacing: 0.13em;
        text-transform: uppercase;
        border-bottom: 1px solid rgba(240,218,159,0.16);
        background:
            linear-gradient(180deg, rgba(255,255,255,0.055), rgba(255,255,255,0.018)),
            rgba(226,184,79,0.025);
    }}

    .desktop-ranking-table th + th,
    .desktop-ranking-table td + td {{
        border-left: 1px solid rgba(240,218,159,0.055);
    }}

    .desktop-ranking-table td {{
        padding: 0.98rem 0.75rem;
        border-bottom: 1px solid rgba(240,218,159,0.095);
        vertical-align: middle;
        font-size: 0.88rem;
        line-height: 1.34;
        text-align: center;
    }}

    .desktop-ranking-table tr:last-child td {{
        border-bottom: 0;
    }}

    .desktop-ranking-table tbody tr {{
        background: rgba(255,255,255,0.018);
        transition: background 150ms ease, box-shadow 150ms ease, transform 150ms ease;
    }}

    .desktop-ranking-table tbody tr:nth-child(even) {{
        background: rgba(255,255,255,0.035);
    }}

    .desktop-ranking-table tbody tr.top-10 {{
        background:
            linear-gradient(90deg, rgba(226,184,79,0.085), rgba(255,255,255,0.018) 42%),
            rgba(255,255,255,0.018);
    }}

    .desktop-ranking-table tbody tr:hover {{
        background: rgba(127,163,90,0.105);
        box-shadow: inset 4px 0 0 rgba(226,184,79,0.82);
    }}

    .desktop-ranking-table th.rank-column,
    .desktop-ranking-table td.rank-column {{
        text-align: center;
        padding-left: 0.82rem;
        padding-right: 0.58rem;
    }}

    .desktop-ranking-table .rank-pill {{
        min-width: 30px;
        height: 30px;
        font-size: 0.75rem;
        box-shadow: 0 0 0 1px rgba(255,255,255,0.055), 0 0 16px rgba(226,184,79,0.10);
    }}

    .desktop-ranking-table th.player-column,
    .desktop-ranking-table td.player-column {{
        text-align: left;
    }}

    .desktop-ranking-table th.state-column,
    .desktop-ranking-table td.state-column {{
        text-align: center;
    }}

    .desktop-ranking-table th.numeric-column,
    .desktop-ranking-table td.numeric-column {{
        text-align: center;
    }}

    .desktop-ranking-table th.period-column,
    .desktop-ranking-table td.period-column {{
        text-align: center;
    }}

    .desktop-ranking-player,
    .desktop-ranking-player:visited {{
        color: var(--rb-text);
        font-weight: 930;
        text-decoration: none;
        overflow-wrap: anywhere;
    }}

    .desktop-ranking-player.available {{
        color: #f6f1d5;
        border-bottom: 1px solid rgba(244,201,93,0.38);
        text-shadow: 0 0 12px rgba(244,201,93,0.10);
    }}

    .desktop-ranking-player.available:hover {{
        color: var(--rb-gold);
    }}

    .desktop-state-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 48px;
        padding: 0.31rem 0.62rem;
        border: 1px solid rgba(127,163,90,0.22);
        border-radius: 999px;
        color: var(--rb-green);
        background: rgba(127,163,90,0.11);
        font-size: 0.74rem;
        font-weight: 930;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }}

    .desktop-ranking-value {{
        color: var(--rb-text);
        font-weight: 940;
        white-space: nowrap;
    }}

    .desktop-ranking-period {{
        display: inline-block;
        color: rgba(220,231,231,0.78);
        font-size: 0.82rem;
        font-weight: 780;
        line-height: 1.45;
        overflow-wrap: normal;
        word-break: keep-all;
        white-space: normal;
        text-align: center;
    }}

    .st-key-ranking_general_pagination,
    .st-key-ranking_average_pagination {{
        margin: 0.4rem 0 0.35rem;
        padding: 0.28rem;
        border: 1px solid rgba(240,218,159,0.075);
        border-radius: 14px;
        background:
            linear-gradient(180deg, rgba(255,255,255,0.028), rgba(255,255,255,0.012)),
            rgba(0,0,0,0.12);
    }}

    .st-key-ranking_general_pagination [data-testid="stHorizontalBlock"],
    .st-key-ranking_average_pagination [data-testid="stHorizontalBlock"] {{
        display: flex !important;
        flex-wrap: nowrap !important;
        justify-content: space-between !important;
        align-items: center !important;
        gap: 0.72rem !important;
        width: 100% !important;
        min-width: 0 !important;
    }}

    .st-key-ranking_general_pagination [data-testid="column"],
    .st-key-ranking_average_pagination [data-testid="column"] {{
        width: auto !important;
        min-width: 0 !important;
        flex: 0 0 auto !important;
    }}

    .st-key-ranking_general_pagination [data-testid="column"]:nth-child(2),
    .st-key-ranking_average_pagination [data-testid="column"]:nth-child(2) {{
        flex: 1 1 auto !important;
        min-width: 150px !important;
    }}

    .st-key-ranking_general_pagination .page-note,
    .st-key-ranking_average_pagination .page-note {{
        min-height: 42px;
        min-width: 150px;
        border-color: rgba(76,201,176,0.18);
        background: rgba(76,201,176,0.045);
        color: rgba(220,231,231,0.9);
        font-size: 0.76rem;
        font-weight: 900;
    }}

    .st-key-ranking_general_pagination .stButton > button,
    .st-key-ranking_average_pagination .stButton > button {{
        min-height: 42px;
        min-width: 92px;
        width: 100%;
        border-radius: 12px;
        font-weight: 900;
        white-space: nowrap !important;
        word-break: keep-all !important;
        overflow-wrap: normal !important;
        writing-mode: horizontal-tb !important;
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

    .st-key-ranking_general_native_table,
    .st-key-ranking_average_native_table {{
        width: 100%;
        margin-top: 0.92rem;
        padding: 0.82rem;
        border: 1px solid rgba(240,218,159,0.14);
        border-radius: 20px;
        background:
            radial-gradient(circle at 0% 0%, rgba(226,184,79,0.07), transparent 18rem),
            radial-gradient(circle at 100% 0%, rgba(76,201,176,0.045), transparent 18rem),
            linear-gradient(180deg, rgba(18,20,15,0.84), rgba(7,10,8,0.62));
        box-shadow: 0 16px 44px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.045);
        overflow: hidden;
    }}

    .st-key-ranking_general_native_table [data-testid="stHorizontalBlock"],
    .st-key-ranking_average_native_table [data-testid="stHorizontalBlock"] {{
        align-items: center !important;
        gap: 0.82rem !important;
        min-height: 52px;
        padding: 0.62rem 0.72rem;
        border-bottom: 1px solid rgba(240,218,159,0.065);
    }}

    .st-key-ranking_general_native_table [data-testid="column"],
    .st-key-ranking_average_native_table [data-testid="column"] {{
        min-width: 0 !important;
        display: flex;
        align-items: center;
    }}

    [class*="st-key-ranking_general_native_header"],
    [class*="st-key-ranking_average_native_header"] {{
        border-bottom: 1px solid rgba(240,218,159,0.12);
        background: rgba(255,255,255,0.018);
    }}

    [class*="st-key-ranking_general_native_header"] [data-testid="stHorizontalBlock"],
    [class*="st-key-ranking_average_native_header"] [data-testid="stHorizontalBlock"] {{
        min-height: 40px;
        padding-top: 0.48rem;
        padding-bottom: 0.48rem;
        border-bottom: 0;
    }}

    [class*="st-key-ranking_general_native_header"] [data-testid="stCaptionContainer"],
    [class*="st-key-ranking_average_native_header"] [data-testid="stCaptionContainer"] {{
        color: rgba(220,231,231,0.62) !important;
        font-size: 0.62rem !important;
        font-weight: 920 !important;
        letter-spacing: 0.14em !important;
        text-transform: uppercase !important;
    }}

    [class*="st-key-ranking_general_native_row_"],
    [class*="st-key-ranking_average_native_row_"] {{
        padding: 0.72rem 0.72rem;
        border-bottom: 1px solid rgba(240,218,159,0.06);
        transition: background 150ms ease, box-shadow 150ms ease;
    }}

    [class*="st-key-ranking_general_native_row_"]:hover,
    [class*="st-key-ranking_average_native_row_"]:hover {{
        background: rgba(127,163,90,0.055);
        box-shadow: inset 3px 0 0 rgba(226,184,79,0.18);
    }}

    [class*="st-key-ranking_general_native_row_"]:last-child,
    [class*="st-key-ranking_average_native_row_"]:last-child {{
        border-bottom: 0;
    }}

    .st-key-ranking_general_native_table button[kind="secondary"],
    .st-key-ranking_average_native_table button[kind="secondary"] {{
        min-height: 32px;
        width: auto !important;
        max-width: 100%;
        padding: 0.15rem 0 !important;
        border: 0 !important;
        border-bottom: 1px solid rgba(244,201,93,0.36) !important;
        border-radius: 0 !important;
        color: var(--rb-text) !important;
        background: transparent !important;
        box-shadow: none !important;
        font-weight: 900 !important;
        text-align: left !important;
        white-space: normal !important;
        overflow-wrap: anywhere !important;
    }}

    .st-key-ranking_general_native_table button[kind="secondary"]:hover,
    .st-key-ranking_average_native_table button[kind="secondary"]:hover {{
        color: var(--rb-gold) !important;
        border-bottom-color: rgba(127,163,90,0.62) !important;
        text-shadow: 0 0 16px rgba(244,201,93,0.16);
    }}

    .player-profile-disabled {{
        color: var(--rb-text);
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
        min-height: 38px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0.38rem 0.5rem;
        border: 1px solid var(--rb-line);
        border-radius: var(--rb-radius-md);
        background: rgba(255,255,255,0.028);
        font-weight: 820;
    }}

    .state-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
        gap: 0.9rem;
    }}

    .state-card {{
        min-height: 188px;
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

    .state-name-line {{
        min-width: 0;
        display: flex;
        align-items: baseline;
        gap: 0.42rem;
    }}

    .state-uf {{
        color: var(--rb-text);
        font-size: 1.55rem;
        font-weight: 950;
        line-height: 1;
    }}

    .state-share {{
        color: rgba(244,201,93,0.84);
        font-size: 0.86rem;
        font-weight: 900;
        line-height: 1;
        white-space: nowrap;
        text-shadow: 0 0 14px rgba(244,201,93,0.16);
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
        line-height: 1.5;
    }}

    .state-best strong {{
        color: var(--rb-text);
    }}

    .state-average-position {{
        display: block;
        margin-top: 0.34rem;
        color: rgba(240,218,159,0.72);
        font-size: 0.78rem;
        font-weight: 820;
        line-height: 1.25;
    }}

    .state-average-position strong {{
        color: var(--rb-green);
        font-weight: 950;
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

    .auth-page {{
        width: min(100%, 560px);
        margin: clamp(0.25rem, 4vh, 2.4rem) auto 1rem;
        display: grid;
        place-items: center;
    }}

    .auth-brand {{
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.95rem;
        text-align: left;
    }}

    .auth-brand-orb {{
        width: 52px;
        height: 52px;
        font-size: 1rem;
    }}

    .auth-brand-text {{
        min-width: 0;
    }}

    .auth-title {{
        color: var(--rb-text);
        font-size: clamp(2rem, 5vw, 3.2rem);
        font-weight: 950;
        line-height: 1;
        letter-spacing: 0;
    }}

    .auth-subtitle {{
        margin-top: 0.42rem;
        color: var(--rb-muted);
        font-size: clamp(0.86rem, 2vw, 1rem);
        font-weight: 720;
        line-height: 1.35;
    }}

    .st-key-auth_card_shell {{
        width: min(100%, 520px);
        margin: 0 auto clamp(1rem, 4vh, 2rem);
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-lg);
        padding: clamp(0.95rem, 3vw, 1.35rem);
        background:
            linear-gradient(150deg, rgba(19,27,36,0.92), rgba(9,14,20,0.78)),
            radial-gradient(circle at 20% 0%, rgba(76,201,176,0.13), transparent 15rem);
        box-shadow: var(--rb-shadow), inset 0 1px 0 rgba(255,255,255,0.055);
    }}

    .st-key-auth_login_shell,
    .st-key-auth_signup_shell,
    .st-key-auth_recover_shell {{
        padding-top: 0.85rem;
    }}

    .st-key-auth_card_shell .stTabs [data-baseweb="tab-list"] {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.35rem;
        padding: 0.18rem;
        border: 1px solid var(--rb-line);
        border-radius: var(--rb-radius-md);
        background: rgba(255,255,255,0.035);
    }}

    .st-key-auth_card_shell .stTabs [data-baseweb="tab"] {{
        justify-content: center;
        border-radius: calc(var(--rb-radius-md) - 2px);
        min-height: 38px;
        padding: 0.35rem 0.42rem;
        font-size: 0.82rem;
    }}

    .st-key-auth_card_shell .stTabs [aria-selected="true"] {{
        background: linear-gradient(145deg, rgba(76,201,176,0.22), rgba(226,184,79,0.14)) !important;
        box-shadow: inset 0 0 0 1px rgba(226,184,79,0.22);
    }}

    .profile-metric-grid,
    .premium-grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.85rem;
        margin: 1rem 0;
    }}

    .premium-grid {{
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }}

    .profile-metric,
    .premium-card {{
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-md);
        padding: 1rem;
        background: linear-gradient(150deg, rgba(19,27,36,0.74), rgba(9,14,20,0.48));
        min-height: 112px;
    }}

    .profile-metric-label,
    .premium-card-label {{
        color: var(--rb-muted);
        font-size: 0.78rem;
        font-weight: 820;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }}

    .profile-metric-value,
    .premium-card-title {{
        margin-top: 0.45rem;
        color: var(--rb-text);
        font-size: 1.45rem;
        font-weight: 930;
        line-height: 1.08;
    }}

    .premium-card-copy {{
        margin-top: 0.6rem;
        color: var(--rb-muted);
        line-height: 1.52;
    }}

    .sidebar-profile {{
        display: flex;
        align-items: center;
        gap: 0.72rem;
        margin: 0.2rem 0 1rem;
        padding: 0.85rem;
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-md);
        background: rgba(255,255,255,0.035);
    }}

    .sidebar-avatar {{
        width: 38px;
        height: 38px;
        display: grid;
        place-items: center;
        border-radius: var(--rb-radius-md);
        color: #111008;
        font-weight: 950;
        background: linear-gradient(145deg, #f0cc67, #a9832d);
    }}

    .sidebar-name {{
        color: var(--rb-text);
        font-weight: 900;
        line-height: 1.1;
        word-break: break-word;
    }}

    .sidebar-plan {{
        margin-top: 0.18rem;
        color: var(--rb-green);
        font-size: 0.75rem;
        font-weight: 820;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }}

    .skeleton-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.85rem;
        margin-bottom: 0.9rem;
    }}

    .skeleton-card {{
        min-height: 118px;
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-md);
        background:
            linear-gradient(90deg, rgba(255,255,255,0.035), rgba(76,201,176,0.10), rgba(255,255,255,0.035));
        background-size: 220% 100%;
        animation: rb-shimmer 1.25s ease-in-out infinite;
    }}

    @keyframes rb-shimmer {{
        0% {{ background-position: 120% 0; }}
        100% {{ background-position: -120% 0; }}
    }}

    .profile-hero-modern,
    .premium-hero-modern {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(280px, 0.42fr);
        gap: clamp(1rem, 3vw, 2rem);
        align-items: center;
        margin-bottom: 1rem;
        padding: clamp(1rem, 2.5vw, 1.5rem);
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-lg);
        background:
            radial-gradient(circle at 12% 5%, rgba(76,201,176,0.13), transparent 20rem),
            linear-gradient(150deg, rgba(19,27,36,0.92), rgba(9,14,20,0.72));
        box-shadow: 0 18px 54px rgba(0,0,0,0.22);
    }}

    .profile-identity {{
        display: flex;
        align-items: center;
        gap: clamp(0.9rem, 2vw, 1.35rem);
        min-width: 0;
    }}

    .profile-avatar {{
        width: clamp(92px, 15vw, 132px);
        height: clamp(92px, 15vw, 132px);
        flex: 0 0 auto;
    }}

    .profile-avatar svg {{
        width: 100%;
        height: 100%;
        display: block;
    }}

    .profile-name {{
        margin: 0.55rem 0 0.22rem;
        color: var(--rb-text);
        font-size: clamp(2rem, 5vw, 3.4rem);
        line-height: 0.98;
        font-weight: 950;
        letter-spacing: 0;
        overflow-wrap: anywhere;
    }}

    .profile-location,
    .profile-meta,
    .plan-progress-foot {{
        color: var(--rb-muted);
    }}

    .profile-meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin-top: 0.7rem;
    }}

    .profile-meta span {{
        border: 1px solid var(--rb-line);
        border-radius: 999px;
        padding: 0.32rem 0.55rem;
        background: rgba(255,255,255,0.035);
        color: var(--rb-text);
        font-size: 0.78rem;
        font-weight: 780;
    }}

    .plan-progress,
    .premium-price-card,
    .premium-panel,
    .saas-readiness {{
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-md);
        padding: 1rem;
        background: linear-gradient(150deg, rgba(19,27,36,0.74), rgba(9,14,20,0.48));
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
    }}

    .plan-progress-top {{
        display: flex;
        justify-content: space-between;
        gap: 0.8rem;
        color: var(--rb-text);
        font-weight: 900;
    }}

    .progress-track {{
        height: 10px;
        margin: 0.75rem 0 0.55rem;
        border-radius: 999px;
        overflow: hidden;
        background: rgba(255,255,255,0.07);
    }}

    .progress-fill {{
        height: 100%;
        border-radius: inherit;
        background: linear-gradient(90deg, var(--rb-green), var(--rb-gold));
        box-shadow: 0 0 24px rgba(76,201,176,0.28);
        transition: width 360ms ease;
    }}

    .achievement-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.65rem;
        margin-top: 0.8rem;
    }}

    .achievement-card {{
        display: flex;
        gap: 0.62rem;
        align-items: center;
        min-height: 76px;
        border: 1px solid var(--rb-line);
        border-radius: var(--rb-radius-md);
        padding: 0.72rem;
        background: rgba(255,255,255,0.035);
    }}

    .achievement-badge {{
        width: 38px;
        height: 38px;
        flex: 0 0 auto;
        display: grid;
        place-items: center;
        border-radius: 999px;
        color: #111008;
        font-size: 0.72rem;
        font-weight: 950;
        background: linear-gradient(145deg, var(--rb-gold), var(--rb-green));
    }}

    .achievement-title {{
        color: var(--rb-text);
        font-weight: 900;
    }}

    .achievement-copy {{
        margin-top: 0.18rem;
        color: var(--rb-muted);
        font-size: 0.82rem;
        line-height: 1.35;
    }}

    .achievement-empty {{
        margin-top: 0.8rem;
        border: 1px dashed rgba(240,218,159,0.18);
        border-radius: var(--rb-radius-md);
        padding: 0.95rem;
        color: var(--rb-muted);
        background: rgba(255,255,255,0.026);
        font-size: 0.88rem;
        line-height: 1.45;
    }}

    .capture-medals-section {{
        margin: 1rem 0;
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-lg);
        padding: clamp(0.95rem, 2vw, 1.25rem);
        background:
            radial-gradient(circle at 12% 0%, rgba(244,201,93,0.11), transparent 18rem),
            radial-gradient(circle at 90% 12%, rgba(76,201,176,0.10), transparent 16rem),
            linear-gradient(150deg, rgba(19,27,36,0.82), rgba(9,14,20,0.56));
        box-shadow: 0 18px 54px rgba(0,0,0,0.22), inset 0 1px 0 rgba(255,255,255,0.04);
    }}

    .capture-medals-top {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(260px, 0.42fr);
        gap: 1rem;
        align-items: stretch;
    }}

    .capture-medals-title {{
        margin: 0.34rem 0 0.35rem;
        color: var(--rb-text);
        font-size: clamp(1.35rem, 3vw, 2.1rem);
        line-height: 1.05;
        font-weight: 950;
    }}

    .capture-medals-copy {{
        max-width: 680px;
        margin: 0;
        color: var(--rb-muted);
        line-height: 1.52;
        font-size: 0.92rem;
    }}

    .capture-medals-summary {{
        border: 1px solid rgba(244,201,93,0.22);
        border-radius: var(--rb-radius-md);
        padding: 0.9rem;
        background: rgba(255,255,255,0.035);
    }}

    .capture-medals-count {{
        color: var(--rb-text);
        font-size: clamp(1.55rem, 4vw, 2.35rem);
        line-height: 1;
        font-weight: 950;
    }}

    .capture-medals-count span {{
        color: var(--rb-gold);
    }}

    .capture-next {{
        margin-top: 0.72rem;
        color: var(--rb-muted);
        font-size: 0.82rem;
        line-height: 1.45;
    }}

    .capture-next strong {{
        color: var(--rb-text);
    }}

    .capture-medal-progress {{
        height: 10px;
        margin-top: 0.7rem;
        border-radius: 999px;
        overflow: hidden;
        background: rgba(255,255,255,0.07);
    }}

    .capture-medal-progress > div {{
        height: 100%;
        border-radius: inherit;
        background: linear-gradient(90deg, var(--rb-green), var(--rb-gold));
        box-shadow: 0 0 24px rgba(244,201,93,0.20);
        transition: width 360ms ease;
    }}

    .capture-medal-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
        gap: 0.72rem;
        margin-top: 1rem;
    }}

    .capture-medal-card {{
        position: relative;
        min-height: 154px;
        padding: 0.82rem;
        border: 1px solid var(--medal-border);
        border-radius: var(--rb-radius-md);
        overflow: hidden;
        background:
            radial-gradient(circle at 50% -22%, var(--medal-glow), transparent 8rem),
            linear-gradient(155deg, rgba(255,255,255,0.052), rgba(255,255,255,0.018));
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 14px 34px rgba(0,0,0,0.18);
        transition: transform 160ms ease, border-color 160ms ease, box-shadow 160ms ease, opacity 160ms ease;
    }}

    .capture-medal-card:hover {{
        transform: translateY(-3px);
    }}

    .capture-medal-card.unlocked {{
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 16px 42px rgba(0,0,0,0.22), 0 0 22px var(--medal-glow);
    }}

    .capture-medal-card.current {{
        border-color: rgba(244,201,93,0.66);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 16px 44px rgba(0,0,0,0.24), 0 0 30px rgba(244,201,93,0.14);
        animation: medal-current-glow 2.4s ease-in-out infinite;
    }}

    .capture-medal-card.locked {{
        filter: grayscale(0.75);
        opacity: 0.58;
        background: linear-gradient(155deg, rgba(255,255,255,0.032), rgba(255,255,255,0.012));
    }}

    .capture-medal-card.latest::after {{
        content: "Ultima";
        position: absolute;
        top: 0.58rem;
        right: 0.58rem;
        border: 1px solid rgba(244,201,93,0.32);
        border-radius: 999px;
        padding: 0.18rem 0.42rem;
        color: var(--rb-gold);
        background: rgba(244,201,93,0.08);
        font-size: 0.58rem;
        font-weight: 920;
    }}

    .capture-medal-card.bronze {{
        --medal-main: #d7955b;
        --medal-soft: #f0c08a;
        --medal-fill: rgba(215,149,91,0.20);
        --medal-border: rgba(215,149,91,0.32);
        --medal-glow: rgba(215,149,91,0.16);
    }}

    .capture-medal-card.silver {{
        --medal-main: #91b7d9;
        --medal-soft: #d7ebff;
        --medal-fill: rgba(145,183,217,0.20);
        --medal-border: rgba(145,183,217,0.34);
        --medal-glow: rgba(91,166,224,0.16);
    }}

    .capture-medal-card.gold {{
        --medal-main: #f4c95d;
        --medal-soft: #ffe6a3;
        --medal-fill: rgba(244,201,93,0.20);
        --medal-border: rgba(244,201,93,0.38);
        --medal-glow: rgba(244,201,93,0.18);
    }}

    .capture-medal-card.platinum {{
        --medal-main: #62f0c8;
        --medal-soft: #d7fff3;
        --medal-fill: rgba(98,240,200,0.20);
        --medal-border: rgba(98,240,200,0.38);
        --medal-glow: rgba(98,240,200,0.18);
    }}

    .capture-medal-icon-wrap {{
        position: relative;
        z-index: 2;
        width: 62px;
        height: 62px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto 0.72rem;
        color: var(--medal-soft);
        background: linear-gradient(145deg, var(--medal-fill), rgba(255,255,255,0.04));
        border: 1px solid var(--medal-border);
        box-shadow: 0 0 24px var(--medal-glow);
    }}

    .capture-medal-icon-wrap::before {{
        content: "";
        position: absolute;
        inset: 15px;
        z-index: 4;
        display: block;
        background: currentColor;
        opacity: 1;
        pointer-events: none;
        filter: drop-shadow(0 0 10px var(--medal-glow));
    }}

    .capture-medal-icon-wrap.medal-icon-target::before {{
        inset: 13px;
        border-radius: 999px;
        background:
            radial-gradient(circle, currentColor 0 14%, transparent 15% 32%, currentColor 33% 43%, transparent 44% 60%, currentColor 61% 72%, transparent 73%);
    }}

    .capture-medal-icon-wrap.medal-icon-map::before {{
        inset: 14px 12px;
        clip-path: polygon(0 12%, 30% 0, 64% 12%, 100% 0, 100% 86%, 70% 100%, 36% 86%, 0 100%);
    }}

    .capture-medal-icon-wrap.medal-icon-bolt::before {{
        inset: 10px 16px;
        clip-path: polygon(58% 0, 8% 58%, 43% 58%, 32% 100%, 94% 39%, 56% 39%);
    }}

    .capture-medal-icon-wrap.medal-icon-spark::before,
    .capture-medal-icon-wrap.medal-icon-shine::before {{
        inset: 10px;
        clip-path: polygon(50% 0, 61% 35%, 100% 50%, 61% 65%, 50% 100%, 39% 65%, 0 50%, 39% 35%);
    }}

    .capture-medal-icon-wrap.medal-icon-radar::before {{
        inset: 11px;
        border-radius: 999px;
        background:
            conic-gradient(from 315deg, currentColor 0deg 42deg, transparent 43deg 360deg),
            radial-gradient(circle, currentColor 0 10%, transparent 11% 28%, currentColor 29% 36%, transparent 37% 54%, currentColor 55% 64%, transparent 65%);
    }}

    .capture-medal-icon-wrap.medal-icon-orbit::before {{
        inset: 13px;
        border-radius: 999px;
        background:
            radial-gradient(circle at 72% 28%, currentColor 0 9%, transparent 10%),
            radial-gradient(circle, currentColor 0 17%, transparent 18%),
            linear-gradient(30deg, transparent 28%, currentColor 29% 35%, transparent 36% 64%, currentColor 65% 71%, transparent 72%);
    }}

    .capture-medal-icon-wrap.medal-icon-chart::before {{
        inset: 13px 12px;
        background:
            linear-gradient(to top, currentColor 0 45%, transparent 46%) left bottom / 24% 100% no-repeat,
            linear-gradient(to top, currentColor 0 70%, transparent 71%) center bottom / 24% 100% no-repeat,
            linear-gradient(to top, currentColor 0 96%, transparent 97%) right bottom / 24% 100% no-repeat;
        border-radius: 4px;
    }}

    .capture-medal-icon-wrap.medal-icon-evolution::before {{
        inset: 12px;
        clip-path: polygon(7% 73%, 35% 73%, 35% 100%, 7% 100%, 7% 73%, 48% 60%, 68% 34%, 54% 34%, 54% 10%, 94% 10%, 94% 50%, 71% 50%, 71% 39%, 50% 68%, 7% 84%);
    }}

    .capture-medal-icon-wrap.medal-icon-streak::before,
    .capture-medal-icon-wrap.medal-icon-flame::before {{
        inset: 9px 14px;
        clip-path: polygon(53% 100%, 25% 91%, 10% 70%, 15% 45%, 38% 22%, 37% 0, 62% 24%, 70% 47%, 89% 35%, 90% 65%, 77% 87%);
    }}

    .capture-medal-icon-wrap.medal-icon-shield::before {{
        inset: 9px 13px;
        clip-path: polygon(50% 0, 96% 17%, 86% 72%, 50% 100%, 14% 72%, 4% 17%);
    }}

    .capture-medal-icon-wrap.medal-icon-trophy::before {{
        inset: 10px 12px;
        clip-path: polygon(25% 0, 75% 0, 75% 12%, 100% 12%, 92% 44%, 70% 54%, 60% 70%, 76% 70%, 76% 88%, 92% 88%, 92% 100%, 8% 100%, 8% 88%, 24% 88%, 24% 70%, 40% 70%, 30% 54%, 8% 44%, 0 12%, 25% 12%);
    }}

    .capture-medal-icon-wrap.medal-icon-star::before {{
        inset: 9px;
        clip-path: polygon(50% 0, 63% 34%, 100% 36%, 70% 58%, 80% 96%, 50% 74%, 20% 96%, 30% 58%, 0 36%, 37% 34%);
    }}

    .capture-medal-icon-wrap.medal-icon-diamond::before,
    .capture-medal-icon-wrap.medal-icon-crystal::before {{
        inset: 9px;
        clip-path: polygon(25% 0, 75% 0, 100% 35%, 50% 100%, 0 35%);
    }}

    .capture-medal-icon-wrap.medal-icon-crown::before {{
        inset: 12px 9px;
        clip-path: polygon(0 28%, 24% 55%, 50% 0, 76% 55%, 100% 28%, 88% 83%, 12% 83%);
    }}

    .capture-medal-icon-wrap.circle {{
        border-radius: 999px;
    }}

    .capture-medal-icon-wrap.hexagon {{
        clip-path: polygon(25% 4%, 75% 4%, 100% 50%, 75% 96%, 25% 96%, 0 50%);
    }}

    .capture-medal-icon-wrap.shield {{
        clip-path: polygon(50% 0, 93% 16%, 84% 74%, 50% 100%, 16% 74%, 7% 16%);
    }}

    .capture-medal-icon-wrap.diamond {{
        clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%);
    }}

    .capture-medal-icon-wrap.star {{
        clip-path: polygon(50% 0, 62% 33%, 98% 35%, 69% 57%, 79% 92%, 50% 72%, 21% 92%, 31% 57%, 2% 35%, 38% 33%);
    }}

    .capture-medal-icon-wrap svg {{
        display: block !important;
        width: 38px;
        height: 38px;
        visibility: visible !important;
        opacity: 1 !important;
        position: relative;
        z-index: 6;
        stroke: none !important;
        fill: #f4c95d !important;
        overflow: visible;
        filter: drop-shadow(0 0 10px var(--medal-glow));
    }}

    .capture-medal-icon-wrap svg * {{
        visibility: visible !important;
        opacity: 1 !important;
        stroke: none !important;
        fill: #f4c95d !important;
    }}

    .capture-medal-card.bronze .capture-medal-icon-wrap svg,
    .capture-medal-card.bronze .capture-medal-icon-wrap svg * {{
        fill: #f0c08a !important;
    }}

    .capture-medal-card.silver .capture-medal-icon-wrap svg,
    .capture-medal-card.silver .capture-medal-icon-wrap svg * {{
        fill: #d7ebff !important;
    }}

    .capture-medal-card.gold .capture-medal-icon-wrap svg,
    .capture-medal-card.gold .capture-medal-icon-wrap svg * {{
        fill: #f4c95d !important;
    }}

    .capture-medal-card.platinum .capture-medal-icon-wrap svg,
    .capture-medal-card.platinum .capture-medal-icon-wrap svg * {{
        fill: #d7fff3 !important;
    }}

    .capture-medal-title {{
        color: var(--rb-text);
        font-size: 0.88rem;
        font-weight: 930;
        line-height: 1.15;
        min-height: 2.05em;
        text-align: center;
    }}

    .capture-medal-threshold {{
        margin-top: 0.34rem;
        color: var(--medal-soft);
        font-size: 0.78rem;
        font-weight: 900;
        text-align: center;
    }}

    .capture-medal-status {{
        display: inline-flex;
        width: fit-content;
        margin: 0.58rem auto 0;
        border: 1px solid var(--medal-border);
        border-radius: 999px;
        padding: 0.18rem 0.42rem;
        color: var(--medal-soft);
        background: rgba(255,255,255,0.035);
        font-size: 0.63rem;
        font-weight: 900;
    }}

    .capture-medal-lock {{
        position: absolute;
        top: 0.62rem;
        right: 0.62rem;
        color: rgba(240,239,255,0.58);
    }}

    @keyframes medal-current-glow {{
        0%, 100% {{ box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 16px 44px rgba(0,0,0,0.24), 0 0 20px rgba(244,201,93,0.11); }}
        50% {{ box-shadow: inset 0 1px 0 rgba(255,255,255,0.10), 0 16px 44px rgba(0,0,0,0.24), 0 0 34px rgba(244,201,93,0.22); }}
    }}

    .activity-list {{
        display: grid;
        gap: 0.55rem;
        margin-top: 0.8rem;
    }}

    .activity-row {{
        display: grid;
        grid-template-columns: 88px minmax(0, 1fr);
        gap: 0.3rem 0.65rem;
        align-items: center;
        border: 1px solid var(--rb-line);
        border-radius: var(--rb-radius-md);
        padding: 0.68rem;
        background: rgba(255,255,255,0.035);
    }}

    .activity-row span {{
        color: var(--rb-green);
        font-size: 0.78rem;
        font-weight: 850;
    }}

    .activity-row strong {{
        color: var(--rb-text);
        overflow-wrap: anywhere;
    }}

    .activity-row em {{
        grid-column: 2;
        color: var(--rb-muted);
        font-style: normal;
        font-size: 0.82rem;
    }}

    .empty-state.compact {{
        padding: 0.85rem;
        min-height: auto;
    }}

    .premium-price {{
        margin: 0.45rem 0;
        color: var(--rb-text);
        font-size: clamp(2rem, 4vw, 3rem);
        line-height: 1;
        font-weight: 950;
    }}

    .pricing-grid {{
        display: grid;
        grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
        gap: 1rem;
        margin-bottom: 1rem;
    }}

    .pricing-card {{
        border: 1px solid var(--rb-border);
        border-radius: var(--rb-radius-lg);
        padding: clamp(1rem, 2.4vw, 1.35rem);
        background: linear-gradient(150deg, rgba(19,27,36,0.80), rgba(9,14,20,0.56));
    }}

    .pricing-card.highlighted {{
        border-color: rgba(226,184,79,0.46);
        background:
            radial-gradient(circle at 18% 0%, rgba(226,184,79,0.15), transparent 18rem),
            linear-gradient(150deg, rgba(28,34,30,0.88), rgba(9,14,20,0.62));
        box-shadow: 0 22px 64px rgba(0,0,0,0.24), 0 0 42px rgba(226,184,79,0.08);
    }}

    .pricing-kicker {{
        color: var(--rb-green);
        font-size: 0.76rem;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 0.12em;
    }}

    .pricing-title {{
        margin-top: 0.42rem;
        color: var(--rb-text);
        font-size: 1.7rem;
        font-weight: 950;
    }}

    .pricing-limit {{
        margin: 0.38rem 0 0.9rem;
        color: var(--rb-gold);
        font-weight: 920;
    }}

    .pricing-card ul {{
        margin: 0;
        padding-left: 1.1rem;
        color: var(--rb-muted);
        line-height: 1.72;
    }}

    .pricing-card li::marker {{
        color: var(--rb-green);
    }}

    .readiness-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.55rem;
        margin-top: 0.75rem;
    }}

    .readiness-grid span {{
        border: 1px solid var(--rb-line);
        border-radius: 999px;
        padding: 0.5rem 0.7rem;
        color: var(--rb-text);
        background: rgba(255,255,255,0.035);
        font-size: 0.82rem;
        font-weight: 820;
        text-align: center;
    }}

    .st-key-public_submission_shell,
    .st-key-profile_edit_shell,
    .st-key-session_shell,
    .st-key-premium_cta_shell,
    .st-key-curation_filter_shell,
    .st-key-curation_queue_shell,
    .st-key-curation_review_shell,
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
            padding-top: 4.1rem !important;
            max-width: 100% !important;
            overflow-x: hidden;
        }}

        html,
        body,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"] {{
            max-width: 100%;
            overflow-x: hidden;
        }}

        .nav-shell {{
            grid-template-columns: 1fr auto;
        }}

        .nav-menu a {{
            display: none;
        }}

        .st-key-navbar {{
            top: 2.9rem;
            padding: 0.62rem 0.72rem;
        }}

        .brand-orb {{
            width: 36px;
            height: 36px;
        }}

        .brand-name {{
            font-size: 0.95rem;
        }}

        .brand-sub {{
            font-size: 0.64rem;
            white-space: normal;
        }}

        .hero-stat-grid,
        .podium {{
            grid-template-columns: 1fr;
        }}

        .st-key-ranking_general_desktop_table,
        .st-key-ranking_average_desktop_table {{
            display: none !important;
        }}

        .mobile-ranking-cards {{
            display: block;
            width: 100%;
        }}

        [class*="st-key-ranking_general_mobile_card_item_"],
        [class*="st-key-ranking_average_mobile_card_item_"],
        [class*="st-key-ranking-general-mobile-card-item-"],
        [class*="st-key-ranking-average-mobile-card-item-"] {{
            display: block !important;
            position: relative !important;
            width: 100%;
            margin-top: 0.72rem;
            padding: 0.92rem;
            border: 1px solid rgba(226,184,79,0.18);
            border-radius: 18px;
            background:
                radial-gradient(circle at 88% 0%, rgba(127,163,90,0.12), transparent 8rem),
                linear-gradient(155deg, rgba(30,28,20,0.82), rgba(10,13,14,0.62));
            box-shadow: 0 14px 34px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.04);
            overflow: hidden;
            box-sizing: border-box;
        }}

        [class*="st-key-ranking_general_mobile_card_header_"],
        [class*="st-key-ranking_average_mobile_card_header_"],
        [class*="st-key-ranking-general-mobile-card-header-"],
        [class*="st-key-ranking-average-mobile-card-header-"] {{
            margin: 0 0 0.42rem;
            min-width: 0;
            width: 100%;
        }}

        [class*="st-key-ranking_general_mobile_card_header_"] [data-testid="stHorizontalBlock"],
        [class*="st-key-ranking_average_mobile_card_header_"] [data-testid="stHorizontalBlock"],
        [class*="st-key-ranking-general-mobile-card-header-"] [data-testid="stHorizontalBlock"],
        [class*="st-key-ranking-average-mobile-card-header-"] [data-testid="stHorizontalBlock"] {{
            display: flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
            gap: 0.28rem !important;
            flex-wrap: wrap !important;
            width: 100%;
        }}

        [class*="st-key-ranking_general_mobile_card_header_"] [data-testid="stVerticalBlock"],
        [class*="st-key-ranking_average_mobile_card_header_"] [data-testid="stVerticalBlock"],
        [class*="st-key-ranking-general-mobile-card-header-"] [data-testid="stVerticalBlock"],
        [class*="st-key-ranking-average-mobile-card-header-"] [data-testid="stVerticalBlock"] {{
            flex: 0 1 auto !important;
            min-width: 0;
            width: auto !important;
            max-width: 100%;
        }}

        [class*="st-key-ranking_general_mobile_card_header_"] [data-testid="stElementContainer"],
        [class*="st-key-ranking_average_mobile_card_header_"] [data-testid="stElementContainer"],
        [class*="st-key-ranking-general-mobile-card-header-"] [data-testid="stElementContainer"],
        [class*="st-key-ranking-average-mobile-card-header-"] [data-testid="stElementContainer"] {{
            width: auto !important;
            min-width: 0 !important;
            flex: 0 1 auto !important;
        }}

        [class*="st-key-ranking_general_mobile_player_link_"],
        [class*="st-key-ranking_average_mobile_player_link_"],
        [class*="st-key-ranking-general-mobile-player-link-"],
        [class*="st-key-ranking-average-mobile-player-link-"] {{
            flex: 0 1 auto !important;
            min-width: 0;
            max-width: 100%;
        }}

        [class*="st-key-ranking_general_mobile_card_body_"] .mobile-ranking-body,
        [class*="st-key-ranking_average_mobile_card_body_"] .mobile-ranking-body,
        [class*="st-key-ranking-general-mobile-card-body-"] .mobile-ranking-body,
        [class*="st-key-ranking-average-mobile-card-body-"] .mobile-ranking-body {{
            margin-left: calc(40px + 0.28rem);
        }}

        [class*="st-key-ranking_general_mobile_card_item_"][class*="_top_"],
        [class*="st-key-ranking_average_mobile_card_item_"][class*="_top_"],
        [class*="st-key-ranking-general-mobile-card-item-"][class*="-top-"],
        [class*="st-key-ranking-average-mobile-card-item-"][class*="-top-"] {{
            border-color: rgba(226,184,79,0.38);
            box-shadow: 0 18px 44px rgba(0,0,0,0.22), 0 0 26px rgba(226,184,79,0.08);
        }}

        [class*="st-key-ranking_general_mobile_card_item_"][class*="_top_"] .mobile-ranking-rank,
        [class*="st-key-ranking_average_mobile_card_item_"][class*="_top_"] .mobile-ranking-rank,
        [class*="st-key-ranking-general-mobile-card-item-"][class*="-top-"] .mobile-ranking-rank,
        [class*="st-key-ranking-average-mobile-card-item-"][class*="-top-"] .mobile-ranking-rank {{
            color: #171207;
            background: linear-gradient(145deg, #f2cf70, var(--rb-gold));
            box-shadow: 0 0 20px rgba(226,184,79,0.18);
        }}

        .st-key-ranking_general_panel,
        .st-key-ranking_average_panel {{
            width: 100%;
            max-width: 100%;
            overflow: hidden;
        }}

        .st-key-ranking_general_panel [data-testid="stMarkdownContainer"] h4,
        .st-key-ranking_average_panel [data-testid="stMarkdownContainer"] h4 {{
            text-align: center;
            max-width: 100%;
            margin-left: auto;
            margin-right: auto;
            line-height: 1.16;
        }}

        .rb-table-wrap {{
            display: none;
        }}

        .rb-table {{
            min-width: 0;
            font-size: 0.74rem;
        }}

        .rb-table th,
        .rb-table td {{
            padding: 0.56rem 0.52rem;
        }}

        .page-note {{
            min-height: 46px;
            font-size: 0.76rem;
            padding: 0.45rem 0.35rem;
        }}

        .st-key-ranking_general_pagination,
        .st-key-ranking_average_pagination {{
            margin: 0.72rem 0 1rem;
            padding: 0.42rem;
            border: 1px solid rgba(240,218,159,0.12);
            border-radius: 18px;
            background:
                radial-gradient(circle at 50% 0%, rgba(226,184,79,0.06), transparent 8rem),
                rgba(5,8,7,0.34);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.045);
            width: 100%;
            max-width: 100%;
            box-sizing: border-box;
        }}

        .st-key-ranking_general_pagination [data-testid="stHorizontalBlock"],
        .st-key-ranking_average_pagination [data-testid="stHorizontalBlock"],
        .st-key-curation_pagination [data-testid="stHorizontalBlock"] {{
            display: grid !important;
            grid-template-columns: minmax(74px, 0.82fr) minmax(112px, 1.2fr) minmax(74px, 0.82fr) !important;
            gap: clamp(0.28rem, 2.2vw, 0.48rem) !important;
            align-items: stretch !important;
            justify-items: stretch !important;
            width: 100% !important;
            max-width: 100% !important;
            overflow: visible !important;
        }}

        .st-key-ranking_general_pagination [data-testid="column"],
        .st-key-ranking_average_pagination [data-testid="column"],
        .st-key-curation_pagination [data-testid="column"] {{
            width: 100% !important;
            min-width: 0 !important;
            max-width: none !important;
            flex: unset !important;
        }}

        .st-key-ranking_general_pagination .stButton,
        .st-key-ranking_average_pagination .stButton,
        .st-key-curation_pagination .stButton {{
            height: 100%;
        }}

        .st-key-ranking_general_pagination .stButton > button,
        .st-key-ranking_average_pagination .stButton > button,
        .st-key-curation_pagination .stButton > button {{
            min-height: 48px;
            height: 48px;
            width: 100% !important;
            min-width: 0 !important;
            padding: 0.38rem 0.34rem;
            border-radius: 14px;
            font-size: clamp(0.72rem, 3.2vw, 0.82rem);
            font-weight: 900;
            white-space: nowrap;
            background: rgba(255,255,255,0.04);
            border-color: rgba(127,163,90,0.26);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.055);
        }}

        .st-key-ranking_general_pagination .page-note,
        .st-key-ranking_average_pagination .page-note,
        .st-key-curation_pagination .page-note {{
            min-height: 48px;
            height: 48px;
            width: 100%;
            min-width: 0;
            padding: 0.34rem 0.28rem;
            border-radius: 14px;
            border-color: rgba(76,201,176,0.22);
            background: rgba(76,201,176,0.06);
            color: rgba(220,231,231,0.92);
            font-size: clamp(0.66rem, 3vw, 0.74rem);
            font-weight: 950;
            line-height: 1.18;
            text-align: center;
            white-space: normal;
        }}

        .stButton > button {{
            min-height: 46px;
            padding: 0.62rem 0.55rem;
            font-size: 0.82rem;
            touch-action: manipulation;
        }}

        .stButton > button:active {{
            transform: scale(0.985);
        }}

        .stButton > button:disabled {{
            transform: none;
        }}

        .stDataFrame,
        [data-testid="stDataFrame"] {{
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }}

        .js-plotly-plot,
        .plot-container,
        .plotly,
        .svg-container {{
            max-width: 100%;
            overflow: hidden;
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

        .st-key-rankings_section .section-head,
        .st-key-states_section .section-head {{
            text-align: center;
        }}

        .st-key-rankings_section .section-kicker,
        .st-key-states_section .section-kicker {{
            text-align: center;
        }}

        .st-key-rankings_section .section-copy,
        .st-key-states_section .section-copy {{
            margin-left: auto;
            margin-right: auto;
        }}

        .range-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .profile-metric-grid,
        .premium-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .profile-hero-modern,
        .premium-hero-modern,
        .capture-medals-top,
        .pricing-grid {{
            grid-template-columns: 1fr;
        }}

        .capture-medal-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .capture-medal-card {{
            min-height: 150px;
            padding: 0.72rem;
        }}

        .readiness-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }}

        .st-key-filters_panel [data-testid="stHorizontalBlock"],
        .st-key-chart_panel [data-testid="stHorizontalBlock"],
        .st-key-states_section [data-testid="stHorizontalBlock"],
        .st-key-curation_filter_shell [data-testid="stHorizontalBlock"],
        .st-key-curation_review_shell [data-testid="stHorizontalBlock"] {{
            flex-wrap: wrap;
        }}

        .ranking-toggles,
        .st-key-filter_toggle_bar {{
            justify-content: center;
            margin: 0.15rem auto 0.85rem;
            width: 100%;
        }}

        .st-key-filter_toggle_bar > [data-testid="stHorizontalBlock"],
        .st-key-filter_toggle_bar > div > [data-testid="stHorizontalBlock"],
        .st-key-filter_toggle_bar > div > div > [data-testid="stHorizontalBlock"] {{
            justify-content: center;
            flex-wrap: wrap;
            width: 100%;
            overflow: visible;
            gap: 0.72rem;
        }}

        .st-key-filter_switch_mean,
        .st-key-filter_switch_monthly {{
            min-width: 0;
            width: min(100%, 310px);
            margin-left: auto;
            margin-right: auto;
            justify-content: center;
        }}

        .st-key-filter_switch_mean [data-testid="stWidgetLabel"] p,
        .st-key-filter_switch_monthly [data-testid="stWidgetLabel"] p {{
            text-align: center;
        }}

        .st-key-filter_states div[data-testid="stButtonGroup"] {{
            justify-content: center;
            width: 100%;
            gap: 0.48rem;
        }}

        .st-key-filter_states [data-baseweb="button-group"] {{
            justify-content: center;
            width: 100%;
        }}

        .st-key-filters_panel [data-testid="stWidgetLabel"] {{
            justify-content: center;
            text-align: center;
            width: 100%;
        }}

        .st-key-filters_panel [data-testid="stWidgetLabel"] p {{
            text-align: center;
            width: 100%;
        }}

        .st-key-filters_panel div[data-baseweb="input"] {{
            width: 100%;
            max-width: 100%;
        }}

        .st-key-state_sort_control {{
            justify-content: center;
            padding-bottom: 0.85rem;
            width: 100%;
        }}

        .st-key-state_sort_control [data-testid="stWidgetLabel"],
        .st-key-state_sort_control div[role="radiogroup"] {{
            justify-content: center;
            width: 100%;
            text-align: center;
        }}

        .st-key-state_sort_control div[role="radiogroup"] {{
            display: grid !important;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 0.42rem;
        }}

        .st-key-state_sort_control div[role="radiogroup"] label {{
            min-width: 0 !important;
            width: 100% !important;
            justify-content: center;
            padding-left: 0.35rem !important;
            padding-right: 0.35rem !important;
        }}

        .st-key-state_sort_control div[role="radiogroup"] label p {{
            width: 100%;
            text-align: center;
            white-space: normal;
            line-height: 1.12;
        }}
    }}

    @media (max-width: 480px) {{
        .block-container {{
            padding-left: 0.65rem;
            padding-right: 0.65rem;
            padding-bottom: 2.6rem !important;
        }}

        .profile-metric-grid,
        .premium-grid,
        .achievement-grid,
        .readiness-grid,
        .skeleton-grid {{
            grid-template-columns: 1fr;
        }}

        .capture-medals-section {{
            padding: 0.86rem;
            border-radius: 20px;
        }}

        .capture-medals-summary {{
            padding: 0.78rem;
        }}

        .capture-medal-grid {{
            gap: 0.62rem;
        }}

        .capture-medal-card {{
            min-height: 148px;
        }}

        .capture-medal-icon-wrap {{
            width: 52px;
            height: 52px;
            margin-bottom: 0.55rem;
        }}

        .capture-medal-icon-wrap svg {{
            width: 34px;
            height: 34px;
        }}

        .profile-identity {{
            align-items: flex-start;
        }}

        .profile-avatar {{
            width: 76px;
            height: 76px;
        }}

        .profile-meta span {{
            width: 100%;
            text-align: center;
        }}

        .activity-row {{
            grid-template-columns: 1fr;
        }}

        .activity-row em {{
            grid-column: auto;
        }}

        .auth-page {{
            margin-top: 0.15rem;
        }}

        .auth-brand {{
            align-items: flex-start;
            justify-content: flex-start;
            width: min(100%, 520px);
        }}

        .auth-brand-orb {{
            width: 44px;
            height: 44px;
        }}

        .st-key-auth_card_shell {{
            padding: 0.85rem;
        }}

        .st-key-auth_card_shell .stTabs [data-baseweb="tab"] {{
            min-height: 42px;
            font-size: 0.76rem;
            line-height: 1.15;
            white-space: normal;
        }}

        .hero,
        .section,
        .st-key-podium_section,
        .st-key-chart_section,
        .st-key-rankings_section,
        .st-key-states_section,
        .st-key-ranges_section {{
            border-radius: 22px;
            padding: 0.9rem;
        }}

        .st-key-chart_panel,
        .st-key-filters_panel,
        .st-key-ranking_general_panel,
        .st-key-ranking_average_panel,
        .st-key-distribution_panel,
        .st-key-curation_filter_shell,
        .st-key-curation_queue_shell,
        .st-key-curation_review_shell {{
            padding: 0.82rem;
        }}

        .hero-title {{
            font-size: clamp(2rem, 13vw, 3rem);
        }}

        .hero-copy,
        .page-copy {{
            font-size: 0.92rem;
            line-height: 1.55;
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

        .rb-table {{
            min-width: 0;
            font-size: 0.72rem;
        }}

        .page-note {{
            min-height: 48px;
            font-size: 0.72rem;
            line-height: 1.2;
        }}

        .state-grid,
        .range-grid {{
            grid-template-columns: 1fr;
        }}

        .state-card {{
            padding: 0.9rem;
        }}

        .state-top {{
            align-items: flex-start;
        }}

        .state-name-line {{
            flex-wrap: nowrap;
            gap: 0.34rem;
        }}

        .state-uf {{
            font-size: 1.38rem;
        }}

        .state-share {{
            font-size: 0.78rem;
        }}

        .state-metrics {{
            grid-template-columns: 1fr;
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
            width: min(100%, 310px);
            min-width: 0;
            min-height: 44px;
            padding: 9px 16px;
            margin-left: auto;
            margin-right: auto;
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


def render_sidebar(profile, page_options, default_page):
    plan = "Premium" if profile.get("is_premium") else "Free"
    nickname = escape(str(profile.get("nickname") or profile.get("email") or "Treinador"))
    st.sidebar.markdown(
        f"""
        <div class="sidebar-profile">
            <div class="sidebar-avatar">BR</div>
            <div>
                <div class="sidebar-name">{nickname}</div>
                <div class="sidebar-plan">{plan}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    current = st.sidebar.radio(
        "Navegacao",
        page_options,
        index=page_options.index(default_page),
    )
    st.sidebar.caption("Tema escuro fixo · PokéGO Brasil")
    return current


def render_hero(base, historical_data):
    jogadores = base["id_jogador"].nunique()
    capturas = historical_data["catches"].sum()
    estados = base["state"].nunique()

    # Inline SVGs keep the stat icons visible in Streamlit's generated HTML; CSS below forces display, stroke and z-index.
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
                            <span class="stat-icon-fallback stat-icon-users-fallback"></span>
                            <svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 24 24" style="display:block; width:32px; height:32px; stroke:#f4c95d; fill:none; overflow:visible;" fill="none" stroke="#f4c95d" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M16 21v-1.6a4.4 4.4 0 0 0-4.4-4.4H7.4A4.4 4.4 0 0 0 3 19.4V21" />
                                <circle cx="9.5" cy="7.4" r="3.7" />
                                <path d="M21 21v-1.4a3.8 3.8 0 0 0-3.1-3.7" />
                                <path d="M16.2 4.1a3.55 3.55 0 0 1 0 6.8" />
                                <path d="M4.8 19.5h9.4" />
                            </svg>
                        </div>
                        <div class="stat-label">Jogadores monitorados</div>
                        <div class="stat-value">{format_int(jogadores)}</div>
                    </article>
                    <article class="stat-card">
                        <div class="stat-icon" aria-hidden="true">
                            <span class="stat-icon-fallback stat-icon-chart-fallback"></span>
                            <svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 24 24" style="display:block; width:32px; height:32px; stroke:#f4c95d; fill:none; overflow:visible;" fill="none" stroke="#f4c95d" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M4 19V5" />
                                <path d="M4 19h16" />
                                <path d="M8 15v-4" />
                                <path d="M12 15V8" />
                                <path d="M16 15v-6" />
                                <path d="M7.2 7.7 10 5l3 2 4-4" />
                                <path d="M16.7 3H20v3.3" />
                            </svg>
                        </div>
                        <div class="stat-label">Capturas analisadas</div>
                        <div class="stat-value">{format_hero_stat_compact(capturas)}</div>
                    </article>
                    <article class="stat-card">
                        <div class="stat-icon" aria-hidden="true">
                            <span class="stat-icon-fallback stat-icon-map-fallback"></span>
                            <svg xmlns="http://www.w3.org/2000/svg" width="34" height="34" viewBox="0 0 24 24" style="display:block; width:32px; height:32px; stroke:#f4c95d; fill:none; overflow:visible;" fill="none" stroke="#f4c95d" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M12 21s6-5.4 6-11a6 6 0 0 0-12 0c0 5.6 6 11 6 11z" />
                                <circle cx="12" cy="10" r="2.35" />
                                <path d="M4.5 20.2c1.5-1 3.2-1.5 5.1-1.5" />
                                <path d="M14.4 18.7c1.9 0 3.6.5 5.1 1.5" />
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
            <div class="podium-avatar"><span class="podium-avatar-fallback"></span>{avatar}</div>
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


def downsample_timeseries(data, max_points=220):
    if len(data) <= max_points:
        return data
    indexes = np.linspace(0, len(data) - 1, max_points).round().astype(int)
    return data.iloc[sorted(set(indexes))]


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
                default="1a",
                selection_mode="single",
            )

        render_selected_chips(selected_players)

        if not selected_players:
            ui_html('<div class="empty-state">Selecione pelo menos um jogador para visualizar a evolução.</div>')
            return

        plot_data = filter_by_period(data[data["nickname"].isin(selected_players)], period)
        colors = ["#f4c95d", "#8ccf5f", "#6bb8ff", "#ff8a65", "#b892ff", "#4fd1c5", "#f59e0b", "#ef6f91", "#c7e36d", "#9fb7ff"]

        fig = go.Figure()
        for index, player in enumerate(selected_players):
            df_player = plot_data[plot_data["nickname"] == player].sort_values("date")
            df_player = downsample_timeseries(df_player)
            trace_color = colors[index % len(colors)]
            fig.add_trace(go.Scatter(
                x=df_player["date"],
                y=df_player["catches"],
                mode="lines+markers",
                name=player,
                line=dict(width=3, color=trace_color),
                marker=dict(size=6, line=dict(width=1.3, color="rgba(255,255,255,0.38)")),
                hovertemplate="<b>%{fullData.name}</b><br>%{x|%d/%m/%Y}<br>%{y:,.0f} capturas<extra></extra>",
                hoverlabel=dict(
                    bgcolor="#10140f",
                    bordercolor=trace_color,
                    font=dict(color="#f6f1d5", size=13),
                ),
            ))

        fig.update_traces(
            hoverlabel=dict(
                bgcolor="#10140f",
                bordercolor="#f4c95d",
                font_color="#f6f1d5",
                font_size=13,
            )
        )
        fig.update_layout(
            template="plotly_dark",
            height=460,
            margin=dict(l=10, r=10, t=34, b=8),
            paper_bgcolor="#070c0a",
            plot_bgcolor="#070c0a",
            hovermode="closest",
            showlegend=False,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                bgcolor="rgba(7,12,10,0.82)",
                bordercolor="rgba(246,241,213,0.10)",
                borderwidth=1,
                font=dict(size=12, color="#f6f1d5"),
            ),
            font=dict(color="#f6f1d5", family="Inter, Segoe UI, Arial"),
            xaxis=dict(
                showgrid=True,
                gridcolor="rgba(246,241,213,0.10)",
                zeroline=False,
                showspikes=False,
            ),
            yaxis=dict(showgrid=True, gridcolor="rgba(246,241,213,0.10)", zeroline=False, tickformat=","),
            hoverlabel=dict(
                bgcolor="rgba(12,16,14,0.98)",
                bordercolor="#6e8f5d",
                font=dict(color="#f6f1d5", size=13),
            ),
        )
        st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False, "responsive": True, "scrollZoom": False})


def open_player_profile(nickname):
    selected = str(nickname or "").strip()
    if not selected:
        return
    st.session_state["selected_player_nickname"] = selected
    st.session_state["current_page"] = "player_profile"
    st.session_state["last_rankings_anchor"] = "rankings"
    request_scroll_to_top()


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
            raw_value = row[column]
            value = escape(str(raw_value))
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


def render_mobile_ranking_cards(data, key_prefix, public_profile_index):
    if data.empty:
        ui_html('<div class="mobile-ranking-cards"><div class="empty-state">Nenhum resultado encontrado com os filtros atuais.</div></div>')
        return

    for row_index, (_, row) in enumerate(data.iterrows()):
        rank = int(row["#"]) if "#" in row else row_index + 1
        nickname = str(row.get("Jogador") or row.get("nickname") or "").strip()
        state = str(row.get("Estado") or row.get("state") or "-").strip() or "-"
        has_profile = normalize_nickname_match_key(nickname) in public_profile_index
        profile_key_part = "profile" if has_profile else "plain"
        tier_key_part = "top" if rank <= 3 else "standard"

        if "Capturas" in row:
            metric_label = "capturas"
            metric_value = str(row.get("Capturas") or "-")
            days_value = row.get("Dias ativo")
            sub_text = f"{int(days_value)} dias ativo" if pd.notna(days_value) else ""
            extra_text = ""
        else:
            metric_label = "média diária"
            metric_value = str(row.get("Média") or row.get("MÃ©dia") or "-")
            days_value = row.get("Dias")
            sub_text = f"{int(days_value)} dias no período" if pd.notna(days_value) else ""
            period = str(row.get("Período") or row.get("PerÃ­odo") or "").strip()
            extra_text = period

        extra_html = f'<div class="mobile-ranking-extra">{escape(extra_text)}</div>' if extra_text else ""
        with st.container(key=f"{key_prefix}_mobile_card_item_{profile_key_part}_{tier_key_part}_{row_index}"):
            with st.container(
                key=f"{key_prefix}_mobile_card_header_{row_index}",
                horizontal=True,
                horizontal_alignment="left",
                vertical_alignment="center",
                gap="small",
            ):
                ui_html(f'<div class="mobile-ranking-rank">#{rank}</div>')
                if has_profile:
                    with st.container(key=f"{key_prefix}_mobile_player_link_{row_index}", width="content"):
                        st.button(
                            nickname,
                            key=f"{key_prefix}_mobile_player_{row_index}_{normalize_nickname_match_key(nickname)}",
                            help=f"Abrir perfil público de {nickname}",
                            on_click=open_player_profile,
                            args=(nickname,),
                        )
                else:
                    ui_html(
                        f'<span class="mobile-ranking-player" title="Perfil ainda não disponível">'
                        f'{escape(nickname)}</span>'
                    )
                ui_html(f'<span class="mobile-ranking-state">{escape(state)}</span>')
            with st.container(key=f"{key_prefix}_mobile_card_body_{row_index}"):
                ui_html(f"""
                    <div class="mobile-ranking-body">
                        <div class="mobile-ranking-meta"><span>{escape(metric_label)}</span></div>
                        <div class="mobile-ranking-metric">{escape(metric_value)}</div>
                        <div class="mobile-ranking-sub">{escape(sub_text)}</div>
                        {extra_html}
                    </div>
                """)


def render_interactive_ranking_table(data, key_prefix, public_profile_index):
    if data.empty:
        ui_html('<div class="empty-state">Nenhum resultado encontrado com os filtros atuais.</div>')
        return

    with st.container(key=f"{key_prefix}_native_table"):
        columns = list(data.columns)
        width_map = {
            "#": 0.10,
            "Jogador": 0.32,
            "Estado": 0.15,
            "Capturas": 0.22,
            "Dias ativo": 0.21,
            "Média": 0.16,
            "Período": 0.22,
            "Dias": 0.15,
        }
        column_widths = [width_map.get(str(column), 0.18) for column in columns]

        with st.container(key=f"{key_prefix}_native_header"):
            header_cols = st.columns(column_widths, vertical_alignment="center")
            for col, label in zip(header_cols, columns):
                with col:
                    st.caption(str(label))

        for row_index, (_, row) in enumerate(data.iterrows()):
            rank = int(row["#"]) if "#" in row else row_index + 1
            row_cols = st.columns(column_widths, vertical_alignment="center")
            for col, column in zip(row_cols, columns):
                raw_value = row[column]
                with col:
                    if column == "#":
                        medal_class = " medal" if rank <= 3 else ""
                        ui_html(f'<span class="rank-pill{medal_class}">{rank}</span>')
                    elif column == "Jogador":
                        nickname = str(raw_value or "").strip()
                        if normalize_nickname_match_key(nickname) in public_profile_index:
                            st.button(
                                nickname,
                                key=f"{key_prefix}_player_{row_index}_{normalize_nickname_match_key(nickname)}",
                                help=f"Abrir perfil público de {nickname}",
                                on_click=open_player_profile,
                                args=(nickname,),
                            )
                        else:
                            ui_html(f'<span class="desktop-ranking-player" title="Perfil ainda não disponível">{escape(nickname)}</span>')
                    elif column == "Estado":
                        ui_html(f'<span class="desktop-state-badge">{escape(str(raw_value))}</span>')
                    elif column in {"Capturas", "Dias ativo", "Média", "Dias"}:
                        ui_html(f'<span class="desktop-ranking-value">{escape(str(raw_value))}</span>')
                    elif column == "Período":
                        ui_html(f'<span class="desktop-ranking-period">{escape(str(raw_value))}</span>')
                    else:
                        st.write(str(raw_value))


def clamp_page_index(value, page_count):
    page_count = max(1, int(page_count or 1))
    try:
        page = int(value)
    except (TypeError, ValueError):
        page = 0
    return max(0, min(page, page_count - 1))


def init_pagination_state(page_key, page_count=1, signature=None):
    signature_key = f"{page_key}_signature"
    if signature is not None and st.session_state.get(signature_key) != signature:
        st.session_state[signature_key] = signature
        st.session_state[page_key] = 0

    page = clamp_page_index(st.session_state.get(page_key, 0), page_count)
    st.session_state[page_key] = page
    return page


def change_pagination_page(page_key, page_count, delta):
    changed_at_key = f"{page_key}_changed_at"
    now = time.monotonic()
    last_changed_at = float(st.session_state.get(changed_at_key, 0) or 0)
    if now - last_changed_at < PAGINATION_DEBOUNCE_SECONDS:
        return

    current = clamp_page_index(st.session_state.get(page_key, 0), page_count)
    st.session_state[page_key] = clamp_page_index(current + delta, page_count)
    st.session_state[changed_at_key] = now


def render_pagination_controls(page_key, page_count, key_prefix):
    current = init_pagination_state(page_key, page_count)
    page_count = max(1, int(page_count or 1))

    with st.container(key=f"{key_prefix}_pagination"):
        prev_col, page_col, next_col = st.columns([0.30, 0.40, 0.30], vertical_alignment="center")
        with prev_col:
            st.button(
                "Anterior",
                key=f"{key_prefix}_prev",
                disabled=current <= 0,
                on_click=change_pagination_page,
                args=(page_key, page_count, -1),
            )
        with page_col:
            ui_html(f'<div class="page-note">Página {current + 1} de {page_count}</div>')
        with next_col:
            st.button(
                "Próxima",
                key=f"{key_prefix}_next",
                disabled=current >= page_count - 1,
                on_click=change_pagination_page,
                args=(page_key, page_count, 1),
            )
    return current


def render_paginated_table(title, data, key, public_profile_index=None):
    st.markdown(f"#### {title}")
    page_size = 10
    page_count = max(1, int(np.ceil(len(data) / page_size)))
    page_key = f"{key}_page"
    if data.empty:
        data_signature = ("empty", title)
    else:
        data_signature = (
            len(data),
            tuple(str(column) for column in data.columns),
            int(pd.util.hash_pandas_object(data, index=True).sum()),
        )
    init_pagination_state(page_key, page_count, signature=data_signature)
    current_page_index = render_pagination_controls(page_key, page_count, key)

    start = current_page_index * page_size
    page = data.iloc[start:start + page_size]
    if public_profile_index is not None:
        with st.container(key=f"{key}_desktop_table"):
            render_interactive_ranking_table(page, key, public_profile_index)
        render_mobile_ranking_cards(page, key, public_profile_index)
    else:
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


def format_percent_value(value):
    try:
        numeric_value = round(float(value), 1)
    except (TypeError, ValueError):
        return "0%"

    if numeric_value.is_integer():
        return f"{int(numeric_value)}%"
    return f"{numeric_value:.1f}%"


def format_position_value(value):
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return "#-"

    if not np.isfinite(numeric_value):
        return "#-"
    return f"#{int(round(numeric_value))}"


def render_state_cards(stats):
    if stats.empty:
        ui_html('<div class="empty-state">Nenhum estado encontrado com os filtros atuais.</div>')
        return

    cards = []
    for _, row in stats.iterrows():
        state_share = format_percent_value(row.get("Representatividade", 0))
        average_position = format_position_value(row.get("Posição média", 0))
        cards.append(f"""
            <article class="state-card">
                <div class="state-top">
                    <div class="state-name-line">
                        <div class="state-uf">{escape(str(row["Estado"]))}</div>
                        <div class="state-share">• {state_share}</div>
                    </div>
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
                    <span class="state-average-position">Posição média: <strong>{average_position}</strong></span>
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


def format_datetime_value(value):
    if value in (None, ""):
        return "-"
    try:
        return pd.to_datetime(value).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(value)


def format_date_value(value):
    if value in (None, ""):
        return "-"
    try:
        return pd.to_datetime(value).strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def format_signed_compact(value):
    value = float(value or 0)
    prefix = "+" if value > 0 else ""
    return f"{prefix}{format_compact(value)}"


def format_hero_stat_compact(value):
    value = float(value or 0)
    abs_value = abs(value)
    units = (
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    )
    for divisor, suffix in units:
        if abs_value >= divisor:
            compact = value / divisor
            text = f"{compact:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    return format_int(value)


def medal_icon_svg(icon_type):
    icons = {
        "target": """
            <circle cx="50" cy="50" r="34" opacity="0.28"></circle>
            <circle cx="50" cy="50" r="22" opacity="0.58"></circle>
            <circle cx="50" cy="50" r="9"></circle>
        """,
        "map": """
            <path d="M16 18l22-9 24 9 22-9v70l-22 9-24-9-22 9V18z" opacity="0.42"></path>
            <path d="M38 9h8v70h-8zM62 18h8v70h-8z"></path>
        """,
        "bolt": """
            <path d="M56 4L18 57h29l-7 39 43-59H54L56 4z"></path>
        """,
        "spark": """
            <path d="M50 4l9 32 33 9-33 9-9 32-9-32-33-9 33-9 9-32z"></path>
            <path d="M18 70l4 12 12 4-12 4-4 12-4-12-12-4 12-4 4-12z" opacity="0.7"></path>
        """,
        "shine": """
            <rect x="46" y="5" width="8" height="25" rx="4"></rect>
            <rect x="46" y="70" width="8" height="25" rx="4"></rect>
            <rect x="5" y="46" width="25" height="8" rx="4"></rect>
            <rect x="70" y="46" width="25" height="8" rx="4"></rect>
            <circle cx="50" cy="50" r="12"></circle>
        """,
        "radar": """
            <path d="M50 8a42 42 0 1042 42H78a28 28 0 11-28-28V8z" opacity="0.42"></path>
            <path d="M50 24a26 26 0 1026 26H62a12 12 0 11-12-12V24z" opacity="0.72"></path>
            <path d="M50 50l33-28 7 8-33 28z"></path>
            <circle cx="50" cy="50" r="8"></circle>
        """,
        "orbit": """
            <ellipse cx="50" cy="50" rx="43" ry="16" transform="rotate(24 50 50)" opacity="0.34"></ellipse>
            <ellipse cx="50" cy="50" rx="43" ry="16" transform="rotate(-24 50 50)" opacity="0.34"></ellipse>
            <circle cx="50" cy="50" r="12"></circle>
            <circle cx="78" cy="34" r="7"></circle>
        """,
        "chart": """
            <rect x="14" y="57" width="12" height="29" rx="3"></rect>
            <rect x="42" y="38" width="12" height="48" rx="3"></rect>
            <rect x="70" y="18" width="12" height="68" rx="3"></rect>
            <path d="M14 44l28-22 20 12 24-25v19l-22 21-20-12-30 24V44z" opacity="0.48"></path>
        """,
        "evolution": """
            <rect x="12" y="58" width="22" height="22" rx="4" opacity="0.72"></rect>
            <rect x="64" y="20" width="24" height="24" rx="5"></rect>
            <path d="M31 55c17-5 27-16 35-34h-15V9h36v36H75V30c-10 20-24 33-44 40V55z"></path>
        """,
        "streak": """
            <path d="M50 96c24-10 32-30 24-48-8 7-15 6-15-5 0-14-9-26-23-37 4 21-18 31-18 56 0 17 13 29 32 34z"></path>
            <path d="M50 82c10-5 14-14 9-23-4 4-9 4-9-3 0-7-4-12-10-18 1 13-9 20-9 32 0 8 8 13 19 12z" opacity="0.62"></path>
        """,
        "shield": """
            <path d="M50 6l36 14v25c0 25-14 40-36 49-22-9-36-24-36-49V20L50 6z"></path>
            <path d="M31 48l13 13 27-31v19L45 76 31 62V48z" opacity="0.55"></path>
        """,
        "trophy": """
            <path d="M30 10h40v24c0 15-9 26-20 26S30 49 30 34V10z"></path>
            <path d="M18 17h12v12c0 10-5 17-14 19-4-20 2-31 2-31zM70 17h12s6 11 2 31c-9-2-14-9-14-19V17z" opacity="0.62"></path>
            <path d="M43 60h14v17h17v13H26V77h17V60z"></path>
        """,
        "flame": """
            <path d="M51 96c25-8 35-26 29-46-6 8-14 10-19 6 4-17-8-35-27-50 4 27-18 32-18 59 0 20 16 30 35 31z"></path>
            <path d="M51 82c10-4 16-12 13-23-4 5-10 6-13 2 1-9-4-17-14-25 2 15-8 21-8 34 0 9 8 13 22 12z" opacity="0.58"></path>
        """,
        "star": """
            <path d="M50 5l13 29 32 4-24 22 7 32-28-17-28 17 7-32L5 38l32-4L50 5z"></path>
        """,
        "diamond": """
            <path d="M25 8h50l18 28-43 58L7 36 25 8z"></path>
            <path d="M7 36h86L50 94 7 36z" opacity="0.38"></path>
        """,
        "crystal": """
            <path d="M50 4l31 22-9 54-22 16-22-16-9-54L50 4z"></path>
            <path d="M19 26h62L50 96 19 26z" opacity="0.36"></path>
        """,
        "crown": """
            <path d="M8 28l20 20 22-38 22 38 20-20-10 50H18L8 28z"></path>
            <rect x="18" y="78" width="64" height="12" rx="4"></rect>
        """,
    }
    paths = icons.get(icon_type, icons["target"])
    return f"""
        <svg class="medal-solid-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="#f4c95d" stroke="none" style="display:block !important;width:38px !important;height:38px !important;fill:#f4c95d !important;stroke:none !important;visibility:visible !important;opacity:1 !important;position:relative;z-index:6;overflow:visible;" aria-hidden="true">
            {paths}
        </svg>
    """


def lock_icon_svg():
    return """
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke="#f4c95d" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:block;width:16px;height:16px;stroke:#f4c95d;fill:none;visibility:visible;opacity:1;" aria-hidden="true">
            <rect x="5" y="10" width="14" height="10" rx="2"></rect>
            <path d="M8 10V7a4 4 0 018 0v3"></path>
        </svg>
    """


def render_capture_medals_section(total_captures):
    progress = calculate_medal_progress(total_captures)
    total = progress["total_captures"]
    if total <= 0:
        ui_html("""
            <section class="capture-medals-section">
                <div class="section-kicker">Capturas</div>
                <h2 class="capture-medals-title">Medalhas de Captura</h2>
                <div class="empty-state compact">Dados de capturas ainda nao disponiveis para este perfil.</div>
            </section>
        """)
        return

    next_medal = progress["next_medal"]
    if next_medal:
        next_html = f"""
            <div class="capture-next">
                Proxima medalha:<br>
                <strong>{format_int(next_medal['threshold'])} capturas</strong><br>
                Faltam {format_int(progress['missing_to_next'])} capturas
            </div>
        """
    else:
        next_html = """
            <div class="capture-next">
                Colecao completa:<br>
                <strong>35 medalhas desbloqueadas</strong><br>
                Novos marcos podem ser adicionados no futuro
            </div>
        """

    status_labels = {
        "unlocked": "Desbloqueada",
        "current": "Em progresso",
        "locked": "Bloqueada",
    }
    cards = []
    for medal in progress["medals"]:
        status = medal["status"]
        latest_class = " latest" if medal.get("is_latest") else ""
        lock_html = f'<div class="capture-medal-lock">{lock_icon_svg()}</div>' if status == "locked" else ""
        cards.append(f"""
            <article class="capture-medal-card {escape(medal['tier'])} {escape(status)}{latest_class}" title="{escape(medal['title'])}">
                {lock_html}
                <div class="capture-medal-icon-wrap {escape(medal['shape_type'])} medal-icon-{escape(medal['icon_type'])}">
                    {medal_icon_svg(medal['icon_type'])}
                </div>
                <div class="capture-medal-title">{escape(medal['title'])}</div>
                <div class="capture-medal-threshold">{format_int(medal['threshold'])} capturas</div>
                <div class="capture-medal-status">{status_labels[status]}</div>
            </article>
        """)

    ui_html(f"""
        <section class="capture-medals-section">
            <div class="capture-medals-top">
                <div>
                    <div class="section-kicker">Capturas</div>
                    <h2 class="capture-medals-title">Medalhas de Captura</h2>
                    <p class="capture-medals-copy">
                        Marcos desbloqueados a cada 100.000 capturas. A proxima medalha acompanha o progresso atual do jogador.
                    </p>
                </div>
                <div class="capture-medals-summary">
                    <div class="capture-medals-count"><span>{progress['unlocked_count']}</span>/{CAPTURE_MEDAL_COUNT}</div>
                    <div class="profile-location">desbloqueadas</div>
                    {next_html}
                    <div class="capture-medal-progress"><div style="width:{progress['progress_pct']}%"></div></div>
                </div>
            </div>
            <div class="capture-medal-grid">{"".join(cards)}</div>
        </section>
    """)


def normalize_admin_achievements(profile):
    raw_items = (
        (profile or {}).get("admin_achievements")
        or (profile or {}).get("manual_achievements")
        or (profile or {}).get("achievements")
        or []
    )
    if isinstance(raw_items, str):
        raw_items = [raw_items] if raw_items.strip() else []

    achievements = []
    for item in raw_items:
        if isinstance(item, dict):
            title = str(item.get("title") or item.get("nome") or "").strip()
            copy = str(item.get("description") or item.get("descricao") or "Conquista atribuida pela curadoria.").strip()
            code = str(item.get("code") or title[:2] or "BR").strip()
        else:
            title = str(item or "").strip()
            copy = "Conquista atribuida pela curadoria."
            code = title[:2] or "BR"
        if title:
            achievements.append({
                "title": title,
                "description": copy,
                "code": code[:2].upper(),
            })
    return achievements


def render_admin_achievements_panel(profile):
    achievements = normalize_admin_achievements(profile)
    if not achievements:
        return """
            <div class="achievement-empty">
                Nenhuma conquista especial atribuida ainda.
            </div>
        """

    cards = []
    for achievement in achievements:
        cards.append(f"""
            <article class="achievement-card">
                <div class="achievement-badge">{escape(achievement['code'])}</div>
                <div>
                    <div class="achievement-title">{escape(achievement['title'])}</div>
                    <div class="achievement-copy">{escape(achievement['description'])}</div>
                </div>
            </article>
        """)
    return f'<div class="achievement-grid">{"".join(cards)}</div>'


def get_query_param_value(name):
    value = st.query_params.get(name, "")
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def load_public_profile_index_safely():
    try:
        return get_public_profile_index_cached()
    except Exception:
        return {}


def resolve_selected_public_profile(public_profile_index):
    requested_nickname = (
        str(st.session_state.get("selected_player_nickname") or "").strip()
        or get_query_param_value("player")
    )
    if not requested_nickname:
        return None

    profile = public_profile_index.get(normalize_nickname_match_key(requested_nickname))
    if not profile:
        st.session_state.pop("selected_player_nickname", None)
        return None

    st.session_state["selected_player_nickname"] = str(profile.get("nickname") or requested_nickname).strip()
    st.session_state["current_page"] = "player_profile"
    return profile


def clear_player_profile_navigation():
    st.session_state.pop("selected_player_nickname", None)
    st.session_state["current_page"] = "dashboard"
    st.session_state["last_rankings_anchor"] = "rankings"
    params = dict(st.query_params)
    params.pop("player", None)
    st.query_params.clear()
    for key, value in params.items():
        st.query_params[key] = value


def calculate_activity_streak(history):
    if not history:
        return 0
    dates = sorted({
        pd.to_datetime(row.get("created_at")).date()
        for row in history
        if row.get("created_at") not in (None, "")
    }, reverse=True)
    if not dates:
        return 0
    streak = 1
    previous = dates[0]
    for current in dates[1:]:
        if (previous - current).days == 1:
            streak += 1
            previous = current
            continue
        if (previous - current).days > 1:
            break
    return streak


def build_profile_insights(profile, stats, history, entitlement, dashboard_data):
    nickname = str(profile.get("nickname") or "").strip()
    state = str(profile.get("estado") or "").strip().upper()
    insights = {
        "rank": "-",
        "latest_catches": 0,
        "monthly_delta": 0,
        "daily_average": 0,
        "activity_streak": calculate_activity_streak(history),
        "progress_pct": 0,
        "medals": [],
        "activities": history[:5] if history else [],
    }

    if entitlement.monthly_limit:
        insights["progress_pct"] = min(100, round((entitlement.used_this_month / entitlement.monthly_limit) * 100))

    player_rows = pd.DataFrame()
    if nickname and dashboard_data is not None and not dashboard_data.empty:
        candidates = dashboard_data[dashboard_data["nickname"].astype(str).str.lower() == nickname.lower()]
        if state:
            state_candidates = candidates[candidates["state"].astype(str).str.upper() == state]
            if not state_candidates.empty:
                candidates = state_candidates
        player_rows = candidates.sort_values("date")

        if not player_rows.empty:
            latest = player_rows.iloc[-1]
            insights["latest_catches"] = int(latest.get("catches") or 0)

            base = get_best_catches(dashboard_data)
            ranked = base.reset_index(drop=True)
            matched = ranked[ranked["nickname"].astype(str).str.lower() == nickname.lower()]
            if state:
                state_matched = matched[matched["state"].astype(str).str.upper() == state]
                if not state_matched.empty:
                    matched = state_matched
            if not matched.empty:
                insights["rank"] = f"#{int(matched.index[0]) + 1}"

            max_date = player_rows["date"].max()
            current_window = player_rows[player_rows["date"] >= max_date - pd.Timedelta(days=30)]
            previous_window = player_rows[
                (player_rows["date"] < max_date - pd.Timedelta(days=30))
                & (player_rows["date"] >= max_date - pd.Timedelta(days=60))
            ]
            if len(current_window) >= 2:
                insights["monthly_delta"] = int(current_window["catches"].iloc[-1] - current_window["catches"].iloc[0])
            elif not previous_window.empty:
                insights["monthly_delta"] = int(player_rows["catches"].iloc[-1] - previous_window["catches"].iloc[-1])

            if len(player_rows) >= 2:
                days = max(1, int((player_rows["date"].iloc[-1] - player_rows["date"].iloc[0]).days))
                insights["daily_average"] = max(0, int((player_rows["catches"].iloc[-1] - player_rows["catches"].iloc[0]) / days))

    medals = []
    if bool(profile.get("is_premium")):
        medals.append(("Premium", "Assinatura ativa"))
    if profile_has_location(profile):
        medals.append(("Perfil completo", "Localidade registrada"))
    if int(stats.get("aprovados") or 0) > 0:
        medals.append(("Validado", "Registro aprovado"))
    if int(stats.get("total") or 0) >= 10:
        medals.append(("Consistente", "10+ inputs enviados"))
    if insights["rank"] != "-" and int(str(insights["rank"]).replace("#", "")) <= 10:
        medals.append(("Top 10", "Entre os líderes nacionais"))
    if insights["activity_streak"] >= 3:
        medals.append(("Streak", f"{insights['activity_streak']} dias de atividade"))
    insights["medals"] = medals[:6] or [("Primeiro passo", "Envie seu primeiro registro")]
    return insights


def build_public_player_insights(public_profile, dashboard_data):
    nickname = str(public_profile.get("nickname") or "").strip()
    player_key = normalize_nickname_match_key(nickname)
    insights = {
        "nickname": nickname or "Jogador",
        "location": "Localidade nao informada",
        "plan": "Premium" if public_profile.get("is_premium") else "Free",
        "rank": "-",
        "state": str(public_profile.get("estado") or "").strip().upper() or "-",
        "latest_catches": 0,
        "daily_average": 0,
        "monthly_delta": 0,
        "records": 0,
        "first_date": None,
        "last_date": None,
        "history": pd.DataFrame(),
        "activities": [],
        "medals": [("Em breve", "Aguardando metricas competitivas publicas")],
    }

    location_parts = [
        str(public_profile.get("cidade") or "").strip(),
        str(public_profile.get("estado") or "").strip(),
        str(public_profile.get("pais") or "").strip(),
    ]
    location = " · ".join(part for part in location_parts if part)
    if location:
        insights["location"] = location

    if not player_key or dashboard_data is None or dashboard_data.empty:
        return insights

    nickname_keys = dashboard_data["nickname"].map(normalize_nickname_match_key)
    player_rows = dashboard_data[nickname_keys == player_key].sort_values("date").copy()
    if player_rows.empty:
        return insights

    latest = player_rows.iloc[-1]
    first = player_rows.iloc[0]
    latest_catches = int(latest.get("catches") or 0)
    insights["history"] = player_rows
    insights["activities"] = player_rows.tail(5).iloc[::-1].to_dict("records")
    insights["records"] = int(len(player_rows))
    insights["state"] = str(latest.get("state") or insights["state"]).strip().upper() or "-"
    insights["latest_catches"] = latest_catches
    insights["first_date"] = first.get("date")
    insights["last_date"] = latest.get("date")

    base = get_best_catches(dashboard_data)
    ranked_keys = base["nickname"].map(normalize_nickname_match_key)
    matched = base[ranked_keys == player_key]
    if not matched.empty:
        insights["rank"] = f"#{int(matched.iloc[0].get('position') or 0)}"

    if len(player_rows) >= 2:
        days = max(1, int((player_rows["date"].iloc[-1] - player_rows["date"].iloc[0]).days))
        insights["daily_average"] = max(0, int((latest_catches - int(first.get("catches") or 0)) / days))

        max_date = player_rows["date"].max()
        current_window = player_rows[player_rows["date"] >= max_date - pd.Timedelta(days=30)]
        previous_window = player_rows[
            (player_rows["date"] < max_date - pd.Timedelta(days=30))
            & (player_rows["date"] >= max_date - pd.Timedelta(days=60))
        ]
        if len(current_window) >= 2:
            insights["monthly_delta"] = int(current_window["catches"].iloc[-1] - current_window["catches"].iloc[0])
        elif not previous_window.empty:
            insights["monthly_delta"] = int(player_rows["catches"].iloc[-1] - previous_window["catches"].iloc[-1])

    medals = []
    rank_number = int(str(insights["rank"]).replace("#", "") or 0) if insights["rank"] != "-" else 0
    if rank_number and rank_number <= 10:
        medals.append(("Top 10", "Entre os lideres nacionais"))
    elif rank_number and rank_number <= 50:
        medals.append(("Top 50", "Destaque no ranking nacional"))
    if latest_catches >= 1_000_000:
        medals.append(("1M+", "Mais de 1 milhao de capturas"))
    if insights["records"] >= 6:
        medals.append(("Historico", "Serie publica com 6+ atualizacoes"))
    if public_profile.get("is_premium"):
        medals.append(("Premium", "Plano premium ativo"))
    if location:
        medals.append(("Perfil publico", "Localidade competitiva informada"))
    medals.append(("Medalhas futuras", "Novas conquistas entram com as proximas metricas"))
    insights["medals"] = medals[:6]
    return insights


def render_public_player_profile(public_profile, dashboard_data):
    insights = build_public_player_insights(public_profile, dashboard_data)
    avatar = trainer_avatar(insights["nickname"], int(str(insights["rank"]).replace("#", "") or 1) if insights["rank"] != "-" else 1)
    achievements_html = render_admin_achievements_panel(public_profile)
    activities_html = "".join(
        f"""
        <div class="activity-row">
            <span>{format_date_value(row.get("date"))}</span>
            <strong>{format_int(row.get("catches") or 0)} capturas</strong>
            <em>{escape(str(row.get("state") or insights["state"]))}</em>
        </div>
        """
        for row in insights["activities"]
    ) or '<div class="empty-state compact">Nenhuma atualizacao publica encontrada para este jogador.</div>'

    if st.button("Voltar para ranking", key="public_player_back", on_click=clear_player_profile_navigation):
        st.rerun()

    ui_html(f"""
        <section class="profile-hero-modern section-anchor" id="perfil-jogador">
            <div class="profile-identity">
                <div class="profile-avatar">{avatar}</div>
                <div>
                    <div class="eyebrow">Perfil publico do jogador</div>
                    <h1 class="profile-name">{escape(insights["nickname"])}</h1>
                    <div class="profile-location">{escape(insights["location"])}</div>
                    <div class="profile-meta">
                        <span>{escape(insights["plan"])}</span>
                        <span>Entrada {format_date_value(public_profile.get("created_at"))}</span>
                        <span>Atualizado {format_date_value(insights["last_date"])}</span>
                    </div>
                </div>
            </div>
        </section>
        <div class="profile-metric-grid">
            <article class="profile-metric">
                <div class="profile-metric-label">Ranking atual</div>
                <div class="profile-metric-value">{escape(insights["rank"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Capturas</div>
                <div class="profile-metric-value">{format_compact(insights["latest_catches"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Media diaria geral</div>
                <div class="profile-metric-value">{format_compact(insights["daily_average"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Media mensal geral</div>
                <div class="profile-metric-value">{format_signed_compact(insights["monthly_delta"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Estado</div>
                <div class="profile-metric-value">{escape(insights["state"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Atualizacoes publicas</div>
                <div class="profile-metric-value">{format_int(insights["records"])}</div>
            </article>
        </div>
    """)

    render_capture_medals_section(insights["latest_catches"])

    history = insights["history"]
    if isinstance(history, pd.DataFrame) and len(history) >= 2:
        fig = go.Figure()
        fig.add_trace(go.Scattergl(
            x=history["date"],
            y=history["catches"],
            mode="lines+markers",
            name=insights["nickname"],
            line=dict(width=3, color="#f4c95d"),
            marker=dict(size=6, color="#7fa35a", line=dict(width=1.2, color="rgba(255,255,255,0.34)")),
            hovertemplate="<b>%{fullData.name}</b><br>%{x|%d/%m/%Y}<br>%{y:,.0f} capturas<extra></extra>",
        ))
        fig.update_layout(
            template="plotly_dark",
            height=380,
            margin=dict(l=10, r=10, t=30, b=8),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(16,17,12,0.28)",
            font=dict(color="#f0efff", family="Inter, Segoe UI, Arial"),
            xaxis=dict(showgrid=True, gridcolor="rgba(240,218,159,0.08)", zeroline=False),
            yaxis=dict(showgrid=True, gridcolor="rgba(240,218,159,0.08)", zeroline=False, tickformat=","),
            hoverlabel=dict(bgcolor="#241b13", bordercolor="#e2b84f", font_size=13),
        )
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False, "responsive": True, "scrollZoom": False})
    else:
        ui_html('<div class="empty-state compact">Evolucao historica sera exibida quando houver pelo menos duas atualizacoes publicas.</div>')

    ui_html(f"""
        <div class="premium-grid">
            <div class="premium-panel">
                <div class="premium-card-label">Conquistas especiais</div>
                {achievements_html}
            </div>
            <div class="premium-panel">
                <div class="premium-card-label">Ultimas atualizacoes</div>
                <div class="activity-list">{activities_html}</div>
            </div>
        </div>
    """)


def curation_status_label(status: str) -> str:
    return {
        "pendente": "pending",
        "validado": "approved",
        "rejeitado": "rejected",
    }.get(str(status or "").lower(), str(status or "-"))


def _format_optional_int(value):
    if value in (None, ""):
        return "-"
    try:
        return format_int(value)
    except Exception:
        return str(value)


def _format_optional_delta(value):
    if value in (None, ""):
        return "-"
    try:
        return format_signed_compact(value)
    except Exception:
        return str(value)


def render_monthly_import_section(profile):
    ui_html("""
        <section class="section-anchor" id="importacao-mensal-ranking">
            <div class="section-head">
                <div class="section-kicker">Curadoria</div>
                <h2>Importacao Mensal de Ranking</h2>
                <p class="section-copy">
                    Analise a planilha antes de gravar, vincule jogadores existentes e crie snapshots mensais sem duplicar cadastros.
                </p>
            </div>
        </section>
    """)

    last_result = st.session_state.pop("monthly_import_last_result", None)
    if last_result:
        if last_result.get("success"):
            st.success(
                "Importacao concluida. "
                f"ID: {last_result.get('importacao_id')} | "
                f"Snapshots: {last_result.get('snapshots_criados', last_result.get('snapshots_desfeitos', 0))} | "
                f"Novos jogadores: {last_result.get('novos_jogadores', 0)} | "
                f"Linhas ignoradas: {last_result.get('linhas_ignoradas', 0)}"
            )
        else:
            st.error("; ".join(last_result.get("errors", ["Nao foi possivel processar a importacao."])))

    import_tab, history_tab = st.tabs(["Analisar XLSX", "Historico de importacoes"])

    with import_tab:
        with st.container(key="monthly_import_upload_shell"):
            upload_col, date_col, action_col = st.columns([0.48, 0.24, 0.28], vertical_alignment="bottom")
            with upload_col:
                uploaded_file = st.file_uploader(
                    "Planilha XLSX",
                    type=["xlsx"],
                    key="monthly_ranking_xlsx",
                )
            with date_col:
                data_referencia = st.date_input(
                    "Data de referencia",
                    value=date.today().replace(day=1),
                    max_value=date.today(),
                    key="monthly_import_reference_date",
                )
            with action_col:
                analyze_clicked = st.button(
                    "Analisar planilha",
                    type="primary",
                    width="stretch",
                    disabled=uploaded_file is None,
                    key="monthly_import_analyze_button",
                )

        if analyze_clicked and uploaded_file is not None:
            try:
                analysis = analyze_monthly_import(
                    uploaded_file,
                    data_referencia,
                    arquivo_nome=getattr(uploaded_file, "name", "ranking.xlsx"),
                )
                st.session_state.monthly_import_analysis = analysis.to_dict()
                st.session_state.monthly_import_last_result = None
                st.rerun()
            except Exception as exc:
                st.error(f"Nao foi possivel analisar a planilha: {exc}")

        analysis_payload = st.session_state.get("monthly_import_analysis")
        if analysis_payload:
            lines = analysis_payload.get("linhas", [])
            errors = analysis_payload.get("errors", [])
            if errors:
                st.error("; ".join(errors))

            preview_df = pd.DataFrame([
                {
                    "Linha": line.get("linha_numero"),
                    "Nickname XLSX": line.get("nickname_xlsx"),
                    "Estado": line.get("estado_xlsx"),
                    "Capturas XLSX": _format_optional_int(line.get("capturas_xlsx")),
                    "Jogador no Banco": line.get("jogador_banco") or "Nao encontrado",
                    "Player ID": line.get("player_id") or "-",
                    "Ultimo Valor": _format_optional_int(line.get("ultimo_valor")),
                    "Novo Valor": _format_optional_int(line.get("novo_valor")),
                    "Diferenca": _format_optional_delta(line.get("diferenca")),
                    "Status": line.get("status"),
                    "Mensagem": line.get("mensagem"),
                }
                for line in lines
            ])

            total = len(lines)
            validas = sum(1 for line in lines if line.get("can_import"))
            erros = sum(1 for line in lines if line.get("status_validacao") == "erro")
            alertas = sum(1 for line in lines if line.get("status_validacao") == "alerta")
            novos = sum(1 for line in lines if line.get("can_import") and line.get("acao") == "criar_jogador")
            existentes = sum(1 for line in lines if line.get("can_import") and line.get("acao") == "usar_existente")

            ui_html(f"""
                <div class="profile-metric-grid">
                    <article class="profile-metric">
                        <div class="profile-metric-label">Linhas</div>
                        <div class="profile-metric-value">{format_int(total)}</div>
                    </article>
                    <article class="profile-metric">
                        <div class="profile-metric-label">Validas</div>
                        <div class="profile-metric-value">{format_int(validas)}</div>
                    </article>
                    <article class="profile-metric">
                        <div class="profile-metric-label">Existentes</div>
                        <div class="profile-metric-value">{format_int(existentes)}</div>
                    </article>
                    <article class="profile-metric">
                        <div class="profile-metric-label">Novos</div>
                        <div class="profile-metric-value">{format_int(novos)}</div>
                    </article>
                    <article class="profile-metric">
                        <div class="profile-metric-label">Alertas</div>
                        <div class="profile-metric-value">{format_int(alertas)}</div>
                    </article>
                    <article class="profile-metric">
                        <div class="profile-metric-label">Erros</div>
                        <div class="profile-metric-value">{format_int(erros)}</div>
                    </article>
                </div>
            """)

            st.dataframe(
                preview_df,
                hide_index=True,
                use_container_width=True,
                height=min(560, 94 + max(1, len(preview_df)) * 38),
            )

            confirm_col, clear_col = st.columns([0.28, 0.72], vertical_alignment="center")
            with confirm_col:
                confirm_clicked = st.button(
                    "Confirmar importacao",
                    type="primary",
                    width="stretch",
                    disabled=bool(errors) or erros > 0 or validas == 0,
                    key="monthly_import_confirm_button",
                )
            with clear_col:
                if st.button("Limpar analise", key="monthly_import_clear_button"):
                    st.session_state.pop("monthly_import_analysis", None)
                    st.rerun()

            if confirm_clicked:
                result = confirm_monthly_import(analysis_payload, str(profile.get("id") or ""))
                if result.get("success"):
                    clear_dashboard_caches()
                    clear_curation_caches()
                    st.session_state.pop("monthly_import_analysis", None)
                st.session_state.monthly_import_last_result = result
                st.rerun()
        else:
            ui_html('<div class="empty-state compact">Envie uma planilha XLSX para ver a previa antes de confirmar.</div>')

    with history_tab:
        result = list_monthly_imports(str(profile.get("id") or ""), limit=30)
        if not result.get("success"):
            st.warning("; ".join(result.get("errors", ["Nao foi possivel carregar o historico de importacoes."])))
            return
        imports = result.get("imports", [])
        if not imports:
            ui_html('<div class="empty-state compact">Nenhuma importacao mensal registrada ainda.</div>')
            return

        imports_df = pd.DataFrame(imports)
        history_view = pd.DataFrame({
            "ID": imports_df["id"],
            "Arquivo": imports_df["arquivo_nome"],
            "Data referencia": imports_df["data_referencia"].map(format_date_value),
            "Status": imports_df["status"],
            "Linhas": imports_df["total_linhas"].map(format_int),
            "Snapshots": imports_df["snapshots_criados"].map(format_int),
            "Existentes": imports_df["jogadores_existentes"].map(format_int),
            "Novos": imports_df["jogadores_criados"].map(format_int),
            "Ignoradas": imports_df["linhas_ignoradas"].map(format_int),
            "Confirmada em": imports_df["confirmed_at"].map(format_datetime_value),
            "Desfeita em": imports_df["undone_at"].map(format_datetime_value),
        })
        st.dataframe(
            history_view,
            hide_index=True,
            use_container_width=True,
            height=min(520, 94 + len(history_view) * 38),
        )

        labels = [
            f"#{row['id']} · {row['data_referencia']} · {row['arquivo_nome']} · {row['status']}"
            for row in imports
        ]
        selected_label = st.selectbox("Importacao para desfazer", labels, key="monthly_import_undo_select")
        selected_import = imports[labels.index(selected_label)]
        undo_disabled = selected_import.get("status") != "confirmado"
        if st.button(
            "Desfazer importacao selecionada",
            disabled=undo_disabled,
            key="monthly_import_undo_button",
        ):
            result = undo_monthly_import(int(selected_import["id"]), str(profile.get("id") or ""))
            if result.get("success"):
                clear_dashboard_caches()
                clear_curation_caches()
            st.session_state.monthly_import_last_result = result
            st.rerun()


def render_curation_page(profile):
    if not user_can_moderate(profile):
        st.error("Acesso restrito a administradores e moderadores.")
        return

    ui_html("""
        <section class="page-hero admin-hero">
            <div class="eyebrow">Admin</div>
            <h1 class="page-title">Curadoria</h1>
            <p class="page-copy">
                Revise registros pendentes, aprove entradas válidas e mantenha o histórico de auditoria.
            </p>
        </section>
    """)

    render_feedback(
        st.session_state.pop("curation_last_result", None),
        "Curadoria atualizada.",
    )

    render_monthly_import_section(profile)

    status_options = {
        "pending": "pendente",
        "approved": "validado",
        "rejected": "rejeitado",
    }
    order_options = {
        "Mais antigos": ("created_at", "asc"),
        "Mais recentes": ("created_at", "desc"),
        "Maior valor": ("catches", "desc"),
        "Menor valor": ("catches", "asc"),
        "Nickname": ("nickname", "asc"),
        "Email": ("email", "asc"),
    }

    with st.container(key="curation_filter_shell"):
        filters_left, filters_mid, filters_right = st.columns([0.44, 0.24, 0.32], vertical_alignment="bottom")
        with filters_left:
            search = st.text_input("Busca", placeholder="Nickname, email, nome ou observação", key="curation_search")
        with filters_mid:
            selected_status_label = st.selectbox("Status", list(status_options.keys()), index=0, key="curation_status")
        with filters_right:
            selected_order_label = st.selectbox("Ordenar por", list(order_options.keys()), index=0, key="curation_order")

    page_size = 10
    page_key = "curation_page"
    status = status_options[selected_status_label]
    order_by, order_direction = order_options[selected_order_label]
    curation_signature = (status, search.strip(), order_by, order_direction)
    page_index = init_pagination_state(page_key, 1, signature=curation_signature)

    result = get_curation_queue(
        str(profile.get("id")),
        status,
        search.strip(),
        order_by,
        order_direction,
        page_index,
        page_size,
    )
    if not result.get("success"):
        st.error("; ".join(result.get("errors", ["Nao foi possivel carregar a curadoria."])))
        return

    total = int(result.get("total", 0))
    records = result.get("records", [])
    page_count = max(1, int(np.ceil(total / page_size)))
    clamped_page_index = init_pagination_state(page_key, page_count, signature=curation_signature)
    if clamped_page_index != page_index:
        page_index = clamped_page_index
        result = get_curation_queue(
            str(profile.get("id")),
            status,
            search.strip(),
            order_by,
            order_direction,
            page_index,
            page_size,
        )
        if not result.get("success"):
            st.error("; ".join(result.get("errors", ["Nao foi possivel carregar a curadoria."])))
            return
        records = result.get("records", [])

    pending_total = total if status == "pendente" and not search.strip() else None
    if pending_total is None:
        pending_total = int(get_curation_queue(str(profile.get("id")), "pendente", "", "created_at", "asc", 0, 1).get("total", 0))

    ui_html(f"""
        <div class="profile-metric-grid">
            <article class="profile-metric">
                <div class="profile-metric-label">Pendentes</div>
                <div class="profile-metric-value">{format_int(pending_total)}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Resultado atual</div>
                <div class="profile-metric-value">{format_int(total)}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Página</div>
                <div class="profile-metric-value">{page_index + 1}/{page_count}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Status</div>
                <div class="profile-metric-value">{escape(selected_status_label)}</div>
            </article>
        </div>
    """)

    if not records:
        ui_html('<div class="empty-state">Nenhum registro encontrado para os filtros atuais.</div>')
        return

    queue_df = pd.DataFrame(records)
    queue_view = pd.DataFrame({
        "ID": queue_df["id"],
        "Usuario": queue_df["usuario_nome"].fillna("-"),
        "Email": queue_df["usuario_email"].fillna("-"),
        "Nickname": queue_df["nickname"].fillna("-"),
        "Data": queue_df["data_referencia"].astype(str),
        "Valor enviado": queue_df["catches"].map(format_int),
        "Tipo": queue_df["periodo_tipo"],
        "Status": queue_df["status"].map(curation_status_label),
        "Observacoes": queue_df["observacao"].fillna(""),
        "Timestamp": queue_df["created_at"].map(format_datetime_value),
    })

    with st.container(key="curation_queue_shell"):
        st.dataframe(
            queue_view,
            hide_index=True,
            use_container_width=True,
            height=min(500, 92 + len(queue_view) * 38),
        )

        render_pagination_controls(page_key, page_count, "curation")

    labels = [
        f"#{row['id']} · {row.get('nickname') or '-'} · {row.get('usuario_email') or '-'} · {format_int(row['catches'])}"
        for row in records
    ]
    selected_label = st.selectbox("Registro para revisar", labels, key="curation_selected_record")
    selected_record = records[labels.index(selected_label)]
    record_id = int(selected_record["id"])
    can_review = selected_record["status"] == "pendente"

    with st.container(key="curation_review_shell"):
        left, right = st.columns([0.54, 0.46], vertical_alignment="top")
        with left:
            st.markdown("#### Detalhes")
            st.write(f"Usuario: {selected_record.get('usuario_nome') or '-'}")
            st.write(f"Email: {selected_record.get('usuario_email') or '-'}")
            st.write(f"Nickname: {selected_record.get('nickname') or '-'}")
            st.write(f"Data: {selected_record.get('data_referencia')}")
            st.write(f"Valor enviado: {format_int(selected_record.get('catches', 0))}")
            st.write(f"Tipo: {selected_record.get('periodo_tipo')}")
        with right:
            with st.form(f"curation_action_form_{record_id}"):
                admin_note = st.text_area("Observação da curadoria", max_chars=500, height=126)
                action_col_approve, action_col_reject = st.columns(2)
                with action_col_approve:
                    approve_clicked = st.form_submit_button("Aprovar", type="primary", disabled=not can_review)
                with action_col_reject:
                    reject_clicked = st.form_submit_button("Rejeitar", disabled=not can_review)

        if approve_clicked:
            result = approve_record(
                record_id,
                admin_note=admin_note,
                admin_user_id=profile.get("id"),
                require_admin=True,
            )
            if result.get("success"):
                clear_dashboard_caches()
                clear_curation_caches()
            st.session_state.curation_last_result = result
            st.rerun()

        if reject_clicked:
            result = reject_record(
                record_id,
                admin_note=admin_note,
                admin_user_id=profile.get("id"),
                require_admin=True,
            )
            if result.get("success"):
                clear_curation_caches()
            st.session_state.curation_last_result = result
            st.rerun()


def render_profile_page(profile, session: AuthSession):
    try:
        overview = get_profile_overview_cached(profile["id"], str(profile.get("updated_at") or ""))
    except Exception as exc:
        st.error(f"Nao foi possivel carregar o perfil. Verifique as migrations do Supabase: {exc}")
        return

    profile = overview["profile"] or profile
    entitlement = overview["entitlement"]
    stats = overview["stats"] or {}
    history = overview["history"]
    is_premium = bool(profile.get("is_premium"))
    premium_label = "Premium" if is_premium else "Free"
    dashboard_snapshot = pd.DataFrame()
    if profile.get("nickname"):
        try:
            dashboard_snapshot = get_data(get_data_fingerprint_cached())
        except Exception:
            dashboard_snapshot = pd.DataFrame()
    insights = build_profile_insights(profile, stats, history, entitlement, dashboard_snapshot)
    avatar = trainer_avatar(profile.get("nickname") or profile.get("email") or "BR", 1)
    location = " · ".join(
        item for item in [
            str(profile.get("cidade") or "").strip(),
            str(profile.get("estado") or "").strip(),
            str(profile.get("pais") or "").strip(),
        ]
        if item
    ) or "Localidade pendente"
    used = entitlement.used_this_month
    limit = entitlement.monthly_limit
    remaining = entitlement.remaining_this_month
    progress_pct = insights["progress_pct"]
    achievements_html = render_admin_achievements_panel(profile)
    activity_html = "".join(
        f"""
        <div class="activity-row">
            <span>{format_date_value(row.get("created_at"))}</span>
            <strong>{escape(str(row.get("nickname") or profile.get("nickname") or "-"))}</strong>
            <em>{format_int(row.get("catches") or 0)} capturas · {curation_status_label(row.get("status"))}</em>
        </div>
        """
        for row in insights["activities"]
    ) or '<div class="empty-state compact">Nenhuma atividade recente.</div>'

    ui_html(f"""
        <section class="profile-hero-modern">
            <div class="profile-identity">
                <div class="profile-avatar">{avatar}</div>
                <div>
                    <div class="eyebrow">Conta competitiva</div>
                    <h1 class="profile-name">{escape(str(profile.get("nickname") or "Treinador"))}</h1>
                    <div class="profile-location">{escape(location)}</div>
                    <div class="profile-meta">
                        <span>Entrada {format_date_value(profile.get("created_at"))}</span>
                        <span>{escape(premium_label)}</span>
                        <span>{escape(insights["rank"])}</span>
                    </div>
                </div>
            </div>
            <div class="plan-progress">
                <div class="plan-progress-top">
                    <span>Uso mensal</span>
                    <strong>{used}/{limit}</strong>
                </div>
                <div class="progress-track"><div class="progress-fill" style="width:{progress_pct}%"></div></div>
                <div class="plan-progress-foot">{remaining} inputs restantes no plano atual</div>
            </div>
        </section>
        <div class="profile-metric-grid">
            <article class="profile-metric">
                <div class="profile-metric-label">Capturas registradas</div>
                <div class="profile-metric-value">{format_compact(insights["latest_catches"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Ranking atual</div>
                <div class="profile-metric-value">{escape(insights["rank"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Média mensal geral</div>
                <div class="profile-metric-value">{format_signed_compact(insights["monthly_delta"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Média diária geral</div>
                <div class="profile-metric-value">{format_compact(insights["daily_average"])}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Inputs enviados</div>
                <div class="profile-metric-value">{format_int(stats.get("total", 0))}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Streak</div>
                <div class="profile-metric-value">{format_int(insights["activity_streak"])}d</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Aprovados</div>
                <div class="profile-metric-value">{format_int(stats.get("aprovados", 0))}</div>
            </article>
            <article class="profile-metric">
                <div class="profile-metric-label">Pendentes</div>
                <div class="profile-metric-value">{format_int(stats.get("pendentes", 0))}</div>
            </article>
        </div>
    """)

    render_capture_medals_section(insights["latest_catches"])

    tab_names = ["Resumo", "Editar perfil", "Enviar dados", "Historico", "Sessao"]
    tabs = st.tabs(tab_names)

    with tabs[0]:
        left, right = st.columns([0.52, 0.48], vertical_alignment="top")
        with left:
            ui_html(f"""
                <div class="premium-panel">
                    <div class="premium-card-label">Conquistas especiais</div>
                    {achievements_html}
                </div>
            """)
        with right:
            ui_html(f"""
                <div class="premium-panel">
                    <div class="premium-card-label">Últimas atividades</div>
                    <div class="activity-list">{activity_html}</div>
                </div>
            """)

    with tabs[1]:
        left, right = st.columns([0.52, 0.48], vertical_alignment="top")
        with left:
            with st.container(key="profile_edit_shell"):
                with st.form("profile_edit_form"):
                    nickname = st.text_input("Nickname", value=str(profile.get("nickname") or ""), max_chars=40)
                    current_country = str(profile.get("pais") or COUNTRIES[0])
                    country_index = COUNTRIES.index(current_country) if current_country in COUNTRIES else 0
                    pais = st.selectbox("País", COUNTRIES, index=country_index)
                    current_state = str(profile.get("estado") or "SP").upper()
                    state_index = BRAZILIAN_STATES.index(current_state) if current_state in BRAZILIAN_STATES else BRAZILIAN_STATES.index("SP")
                    estado = st.selectbox("Estado", BRAZILIAN_STATES, index=state_index)
                    cidade = st.text_input("Cidade", value=str(profile.get("cidade") or ""), max_chars=80)
                    st.text_input("Email", value=str(profile.get("email") or ""), disabled=True)
                    submitted = st.form_submit_button("Salvar perfil", type="primary")
                if submitted:
                    normalized_profile, profile_errors = validate_profile_fields(nickname, pais, estado, cidade)
                    if profile_errors:
                        st.error("; ".join(profile_errors))
                        return
                    try:
                        updated = update_user_profile(
                            profile["id"],
                            profile.get("nome") or normalized_profile["nickname"],
                            normalized_profile["nickname"],
                            normalized_profile["pais"],
                            normalized_profile["estado"],
                            normalized_profile["cidade"],
                        )
                        if updated:
                            st.session_state.current_profile = updated
                            clear_profile_caches()
                        st.success("Perfil atualizado.")
                    except Exception:
                        st.error("Nao foi possivel atualizar o perfil agora.")
        with right:
            st.markdown("#### Dados da conta")
            st.write(f"Email validado: {'sim' if profile.get('email_verified') else 'pendente'}")
            st.write(f"Nickname: {profile.get('nickname') or '-'}")
            st.write(f"Localidade: {profile.get('cidade') or '-'} · {profile.get('estado') or '-'} · {profile.get('pais') or '-'}")
            st.write(f"Data de registro: {format_datetime_value(profile.get('created_at'))}")
            st.write(f"Ultimo acesso: {format_datetime_value(profile.get('last_seen_at') or profile.get('last_login_at'))}")
            st.write(f"Total de inputs enviados: {format_int(stats.get('total', 0))}")

    with tabs[2]:
        render_public_submission_page(profile)

    with tabs[3]:
        if history:
            history_df = pd.DataFrame(history)
            visible_columns = [
                "id",
                "nickname",
                "state",
                "data_referencia",
                "catches",
                "periodo_tipo",
                "status",
                "created_at",
                "reviewed_at",
                "curadoria_observacao",
            ]
            visible_columns = [column for column in visible_columns if column in history_df.columns]
            st.dataframe(
                history_df[visible_columns],
                hide_index=True,
                use_container_width=True,
                height=min(520, 92 + len(history_df) * 36),
            )
        else:
            ui_html('<div class="empty-state">Nenhum envio encontrado para sua conta.</div>')

    with tabs[4]:
        with st.container(key="session_shell"):
            left, right = st.columns([0.62, 0.38], vertical_alignment="center")
            with left:
                st.caption("Sessao Supabase ativa.")
                st.write(f"Expira em aproximadamente {max(0, session.expires_in // 60)} minutos.")
                st.write("Tokens sao validados periodicamente com o Supabase Auth e renovados antes de expirar.")
            with right:
                if st.button("Sair da conta", type="primary", key="profile_logout_button"):
                    logout_current_user()

def render_premium_page(profile):
    is_premium = bool(profile.get("is_premium"))
    free_limit = int(get_setting("FREE_MONTHLY_INPUT_LIMIT", "5") or 5)
    premium_limit = int(get_setting("PREMIUM_MONTHLY_INPUT_LIMIT", "50") or 50)
    price_cents = int(get_setting("PREMIUM_PRICE_CENTS", "1990") or 1990)
    currency = get_setting("PREMIUM_CURRENCY", "BRL") or "BRL"
    price_label = f"{currency} {price_cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    current_provider = get_setting("PAYMENT_PROVIDER", "manual") or "manual"
    premium_features = [
        "10x mais inputs mensais",
        "Todas estatísticas do jogo",
        "Metas personalizadas",
        "Análise histórica",
        "Métricas avançadas",
        "Sistema de medalhas",
        "Evolução por categoria",
        "Comparações temporais",
        "Insights automáticos",
        "Painel premium exclusivo",
        "Funcionalidades antecipadas",
    ]
    feature_html = "".join(f"<li>{escape(item)}</li>" for item in premium_features)
    status_label = "Premium ativo" if is_premium else "Pronto para upgrade"

    ui_html(f"""
        <section class="premium-hero-modern">
            <div>
                <div class="eyebrow">Assinatura PokéGO Brasil</div>
                <h1 class="page-title">Premium para quem acompanha evolução de verdade</h1>
                <p class="page-copy">
                    Uma camada SaaS para transformar registros em metas, estatísticas pessoais,
                    comparações históricas e retenção competitiva.
                </p>
            </div>
            <div class="premium-price-card">
                <div class="premium-card-label">{escape(status_label)}</div>
                <div class="premium-price">{escape(price_label)}</div>
                <div class="premium-card-copy">Plano mensal previsto. Ativação por webhook após confirmação do provedor.</div>
            </div>
        </section>
        <div class="pricing-grid">
            <article class="pricing-card">
                <div class="pricing-kicker">Free</div>
                <div class="pricing-title">Essencial</div>
                <div class="pricing-limit">{free_limit} inputs/mês</div>
                <ul>
                    <li>Limite mensal básico</li>
                    <li>Apenas capturas</li>
                    <li>Dashboard global</li>
                    <li>Histórico pessoal essencial</li>
                </ul>
            </article>
            <article class="pricing-card highlighted">
                <div class="pricing-kicker">Premium</div>
                <div class="pricing-title">Competitivo</div>
                <div class="pricing-limit">{premium_limit} inputs/mês</div>
                <ul>{feature_html}</ul>
            </article>
        </div>
        <div class="premium-grid">
            <article class="premium-card">
                <div class="premium-card-label">Retenção</div>
                <div class="premium-card-title">Metas e progresso</div>
                <div class="premium-card-copy">Barras, streaks, medalhas e objetivos mensais para criar hábito de atualização.</div>
            </article>
            <article class="premium-card">
                <div class="premium-card-label">Análise</div>
                <div class="premium-card-title">Histórico rico</div>
                <div class="premium-card-copy">Comparações por período, categoria e evolução individual conforme novas métricas entrarem.</div>
            </article>
            <article class="premium-card">
                <div class="premium-card-label">SaaS</div>
                <div class="premium-card-title">Assinatura real</div>
                <div class="premium-card-copy">Checkout externo, pagamentos, webhook, status premium e limites por plano já estão separados por camada.</div>
            </article>
        </div>
    """)

    with st.container(key="premium_cta_shell"):
        if is_premium:
            st.success("Seu plano Premium esta ativo.")
        else:
            st.markdown("#### Ativar Premium")
            st.write("O checkout usa o provedor configurado e a liberacao premium ocorre por webhook assinado.")
            if st.button("Fazer upgrade para Premium", type="primary", key="premium_upgrade_button"):
                try:
                    checkout = create_upgrade_checkout(profile)
                    st.session_state.last_checkout = {
                        "url": checkout.checkout_url,
                        "provider": checkout.provider,
                        "reference": checkout.payment.get("external_reference"),
                    }
                except Exception as exc:
                    st.error(f"Nao foi possivel iniciar o checkout: {exc}")

            checkout = st.session_state.get("last_checkout")
            if checkout:
                if checkout.get("url"):
                    st.link_button("Ir para checkout externo", checkout["url"], type="primary")
                else:
                    st.info("Checkout externo ainda nao configurado. Defina PAYMENT_CHECKOUT_URL e o provedor desejado.")
                st.caption(f"Referencia: {checkout.get('reference')} | Provedor: {checkout.get('provider')}")

    ui_html(f"""
        <div class="saas-readiness">
            <div class="premium-card-label">Arquitetura pronta</div>
            <div class="readiness-grid">
                <span>Provider atual: {escape(current_provider)}</span>
                <span>Cakto/Cacto adapter</span>
                <span>Webhook assinado</span>
                <span>Ativação premium</span>
                <span>Limite por plano</span>
                <span>Upgrade/downgrade por status</span>
            </div>
        </div>
    """)


inject_css()
initial_page_param = str(st.query_params.get("page", "")).strip().lower()
if initial_page_param in {RESET_PASSWORD_PAGE, "redefinir-senha", "reset_password"}:
    render_reset_password_page()
    render_footer()
    st.stop()

session, profile = require_authenticated_user()
public_profile_index = load_public_profile_index_safely()
selected_public_player = resolve_selected_public_profile(public_profile_index)
page_param = str(st.query_params.get("page", "")).strip().lower()
premium_enabled_for_user = ENABLE_PREMIUM or bool(profile.get("is_premium"))
page_options = ["Dashboard", "Perfil"]
if premium_enabled_for_user:
    page_options.append("Premium")
if user_can_moderate(profile):
    page_options.append("Curadoria")
if selected_public_player:
    page_options.append("Perfil do jogador")

if page_param in {"perfil", "profile", "enviar", "enviar-dados", "submit"}:
    default_page = "Perfil"
elif page_param in {"premium", "upgrade"} and premium_enabled_for_user:
    default_page = "Premium"
elif page_param in {"curadoria", "admin"} and "Curadoria" in page_options:
    default_page = "Curadoria"
elif selected_public_player:
    default_page = "Perfil do jogador"
else:
    default_page = "Dashboard"

current_page = render_sidebar(profile, page_options, default_page)
if st.session_state.get(LAST_RENDERED_PAGE_KEY) != current_page:
    request_scroll_to_top()
st.session_state[LAST_RENDERED_PAGE_KEY] = current_page

render_navbar()
scroll_to_top_once()

if current_page == "Perfil":
    render_profile_page(profile, session)
    render_footer()
    st.stop()

if current_page == "Premium":
    if not premium_enabled_for_user:
        st.info("Premium em breve.")
        render_footer()
        st.stop()
    render_premium_page(profile)
    render_footer()
    st.stop()

if current_page == "Curadoria":
    render_curation_page(profile)
    render_footer()
    st.stop()

if current_page == "Perfil do jogador":
    if not selected_public_player:
        st.info("Perfil publico ainda nao disponivel para este jogador.")
        if st.button("Voltar para ranking", key="public_player_missing_back", on_click=clear_player_profile_navigation):
            st.rerun()
        render_footer()
        st.stop()
    with st.spinner("Carregando perfil publico..."):
        fingerprint = get_data_fingerprint_cached()
        df = get_data(fingerprint)
    render_public_player_profile(selected_public_player, df)
    render_footer()
    st.stop()

dashboard_placeholder = st.empty()
with dashboard_placeholder.container():
    ui_html("""
        <div class="skeleton-grid">
            <div class="skeleton-card"></div>
            <div class="skeleton-card"></div>
            <div class="skeleton-card"></div>
        </div>
    """)
with st.spinner("Carregando ranking..."):
    fingerprint = get_data_fingerprint_cached()
    df = get_data(fingerprint)
    base_all = get_best_catches(df)
dashboard_placeholder.empty()

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
            render_paginated_table(
                "Ranking geral por capturas totais",
                build_general_ranking(filtered_df),
                "ranking_general",
                public_profile_index,
            )

    with average_col:
        with st.container(key="ranking_average_panel"):
            render_paginated_table(
                "Ranking por média diária",
                build_average_ranking(filtered_df, somente_melhor, apenas_mensais),
                "ranking_average",
                public_profile_index,
            )

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
    render_state_cards(build_state_stats(filtered_base, state_order, base_all))

with st.container(key="ranges_section"):
    ui_html('<div id="faixas" class="section-anchor"></div>')
    section_header("Distribuição", "Faixas de capturas", "Quantidade de jogadores acima dos principais marcos de captura.")
    with st.container(key="distribution_panel"):
        render_distribution(build_distribution(filtered_base))

render_footer()
