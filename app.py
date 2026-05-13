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
.title-center {
    text-align: center;
    font-size: 38px;
    font-weight: bold;
    margin-bottom: 25px;
    color: #146b3a;
}
</style>
""", unsafe_allow_html=True)

# ======================
# LOAD DATA
# ======================
@st.cache_data
def get_data():
    return load_data()

df = get_data()

# ======================
# TITULO
# ======================
st.markdown('<div class="title-center">Dashboard de Jogadores by Enzo Sartorelli</div>', unsafe_allow_html=True)

# ======================
# FILTROS
# ======================
st.subheader("🎯 Filtros")

col_f1, col_f2, col_f3, col_f4 = st.columns([2,2,1,1])

states = sorted(df["state"].dropna().unique())

with col_f1:
    selected_states = st.multiselect("📍 Estado", states)

df_filtered = df.copy()

if selected_states:
    df_filtered = df_filtered[df_filtered["state"].isin(selected_states)]

players = sorted(df_filtered["nickname"].dropna().unique())

with col_f2:
    selected_players = st.multiselect("👤 Jogadores", players)

if selected_players:
    df_filtered = df_filtered[df_filtered["nickname"].isin(selected_players)]

with col_f3:
    somente_melhor = st.checkbox("✅ Melhor média")

with col_f4:
    apenas_mensais = st.checkbox("📅 Apenas mensais")

df = df_filtered

# ======================
# LAYOUT
# ======================
col1, col2 = st.columns(2)

# ======================
# 🏆 RANKING 1
# ======================
with col1:
    st.subheader("🏆 Maior Catch por Jogador")

    idx = df.groupby("id_jogador")["catches"].idxmax()

    ranking = df.loc[idx][["nickname","state","catches","date"]]
    ranking = ranking.sort_values("catches", ascending=False)

    ranking["ranking"] = range(1, len(ranking)+1)

    ranking["catches"] = ranking["catches"].apply(lambda x: f"{int(x):,}".replace(",", "."))
    ranking["date"] = ranking["date"].dt.date

    ranking = ranking[["ranking","nickname","state","catches","date"]]

    ranking.columns = ["Ranking","Jogador","Estado","Catches","Data"]

    st.dataframe(ranking, use_container_width=True, height=500, hide_index=True)

# ======================
# 📈 RANKING 2
# ======================
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

                d1 = group.loc[i,"date"]
                d2 = group.loc[j,"date"]

                c1 = group.loc[i,"catches"]
                c2 = group.loc[j,"catches"]

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
            df_media = df_media.sort_values("media", ascending=False).groupby("nickname").head(1)

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
# 📊 GRÁFICO
# ======================
st.divider()
st.subheader("📊 Evolução do Jogador")

player = st.selectbox("Selecione um jogador", sorted(df["nickname"].unique()))

df_p = df[df["nickname"]==player].sort_values("date")

if len(df_p)>0:

    df_p["diff"] = df_p["catches"].diff().fillna(0)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df_p["date"],
        y=df_p["catches"],
        mode="lines+markers",
        line=dict(color="#146b3a", width=3),
        marker=dict(size=8),
        customdata=df_p["diff"],
        hovertemplate=
        "<b>Data:</b> %{x}<br>" +
        "<b>Total:</b> %{y:,}<br>" +
        "<b>Ganho:</b> %{customdata:,}<extra></extra>"
    ))

    fig.update_layout(template="plotly_white", height=450)

    st.plotly_chart(fig, use_container_width=True)

# ======================
# 📊 ESTATÍSTICAS
# ======================
st.divider()
st.subheader("📊 Estatísticas Gerais")

idx = df.groupby("id_jogador")["catches"].idxmax()
base = df.loc[idx][["id_jogador","nickname","state","catches"]]

base = base.sort_values("catches", ascending=False)
base["position"] = range(1,len(base)+1)

# KPI
c1,c2,c3,c4 = st.columns(4)

c1.metric("Estados", base["state"].nunique())
c2.metric("Jogadores", base["id_jogador"].nunique())
c3.metric("Soma Top", f"{int(base['catches'].sum()):,}".replace(",","."))
c4.metric("Soma Total", f"{int(df['catches'].sum()):,}".replace(",", "."))

# tabela estado
dados = []

total = len(base)

for estado, group in base.groupby("state"):

    qtd = len(group)
    perc = qtd/total

    avg_catch = group["catches"].mean()
    avg_pos = group["position"].mean()
    best_pos = group["position"].min()

    best_player = group.loc[group["position"].idxmin(),"nickname"]

    dados.append({
        "Estado": estado,
        "Qtd Jogadores": qtd,
        "%": f"{perc:.0%}",
        "Média Catches": int(avg_catch),
        "Média Ranking": round(avg_pos,2),
        "Melhor Ranking": f"{best_pos} 👤 {best_player}"
    })

df_estado = pd.DataFrame(dados)

# ✅ ORDEM ALFABÉTICA
df_estado = df_estado.sort_values("Estado")

# format
df_estado["Média Catches"] = df_estado["Média Catches"].apply(
    lambda x: f"{x:,}".replace(",",".")
)

st.dataframe(df_estado, use_container_width=True, height=400, hide_index=True)

# =========================
# 📊 DISTRIBUIÇÃO DE CATCHES
# =========================

st.divider()
st.subheader("📊 Distribuição de Jogadores por Faixa de Catches")

# ✅ base correta (maior catch por jogador)
idx = df.groupby("id_jogador")["catches"].idxmax()
base_dist = df.loc[idx][["id_jogador", "nickname", "catches"]]

# =========================
# FAIXAS
# =========================
faixas = [
    500000,600000,700000,800000,900000,
    1000000,1100000,1200000,1300000,1400000,
    1500000,1750000,2000000,2250000,2500000,
    2750000,3000000
]

resultados = []

total_jogadores = len(base_dist)

for i in range(len(faixas)-1):

    inferior = faixas[i]
    superior = faixas[i+1]

    # jogadores na faixa
    faixa_df = base_dist[
        (base_dist["catches"] >= inferior) &
        (base_dist["catches"] < superior)
    ]

    # jogadores acima
    acima_df = base_dist[base_dist["catches"] >= superior]

    resultados.append({
        "Faixa": f"{inferior:,} - {superior:,}".replace(",", "."),
        "Jogadores na Faixa": len(faixa_df),
        "Jogadores Acima": len(acima_df)
    })

df_faixas = pd.DataFrame(resultados)

# =========================
# FORMATAR
# =========================
st.dataframe(
    df_faixas,
    use_container_width=True,
    hide_index=True,
    height=450
)