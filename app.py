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
    margin-bottom: 35px;
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
